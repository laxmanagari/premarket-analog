"""Pattern definition, historical scanning, and forward-return analysis."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .indicators import rolling_avg_volume, rsi, sma

DEFAULT_HORIZONS = (1, 5, 20)


@dataclass
class PatternConfig:
    """Defines a premarket gap-up scan. All thresholds are inclusive lower/upper
    bounds unless noted.

    gap_pct_min:      minimum overnight gap, (open - prev_close) / prev_close * 100
    rsi_range:        (min, max) band for RSI(14) as of the prior day's close —
                       this is what a premarket scanner would actually know before
                       today's open
    volume_multiple:  minimum ratio of the signal day's volume to the trailing
                       `volume_window`-day average volume (ending the prior day).
                       Note: since this tool works from daily bars, this is a
                       full-day proxy for "elevated volume" rather than a true
                       premarket-only volume read.
    """

    gap_pct_min: float = 2.0
    rsi_range: tuple[float, float] = (50.0, 70.0)
    volume_multiple: float = 1.5
    volume_window: int = 20
    rsi_period: int = 14
    sma_periods: tuple[int, ...] = (50, 200)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def default(cls) -> "PatternConfig":
        return cls()

    @classmethod
    def from_overrides(
        cls,
        config_path: str | None = None,
        gap_pct_min: float | None = None,
        rsi_min: float | None = None,
        rsi_max: float | None = None,
        volume_multiple: float | None = None,
        volume_window: int | None = None,
    ) -> "PatternConfig":
        """Build a pattern starting from defaults, layering a JSON config file,
        then explicit CLI overrides on top (CLI wins)."""
        values = cls.default().to_dict()

        if config_path:
            with open(config_path) as f:
                file_values = json.load(f)
            if "rsi_range" in file_values:
                file_values["rsi_range"] = tuple(file_values["rsi_range"])
            if "sma_periods" in file_values:
                file_values["sma_periods"] = tuple(file_values["sma_periods"])
            values.update(file_values)

        if gap_pct_min is not None:
            values["gap_pct_min"] = gap_pct_min
        rsi_min = rsi_min if rsi_min is not None else values["rsi_range"][0]
        rsi_max = rsi_max if rsi_max is not None else values["rsi_range"][1]
        values["rsi_range"] = (rsi_min, rsi_max)
        if volume_multiple is not None:
            values["volume_multiple"] = volume_multiple
        if volume_window is not None:
            values["volume_window"] = volume_window

        return cls(**values)


def compute_indicators(df: pd.DataFrame, pattern: PatternConfig) -> pd.DataFrame:
    """Adds indicator + signal columns to a copy of the OHLCV frame."""
    out = df.copy()
    out["rsi"] = rsi(out["close"], pattern.rsi_period)
    for period in pattern.sma_periods:
        out[f"sma{period}"] = sma(out["close"], period)
    out["avg_volume"] = rolling_avg_volume(out["volume"], pattern.volume_window)

    out["prev_close"] = out["close"].shift(1)
    out["gap_pct"] = (out["open"] - out["prev_close"]) / out["prev_close"] * 100

    # What a premarket scanner would know *before* today's open: yesterday's
    # RSI and the average volume trailing up through yesterday.
    out["rsi_prior"] = out["rsi"].shift(1)
    out["avg_volume_prior"] = out["avg_volume"].shift(1)
    out["volume_ratio"] = out["volume"] / out["avg_volume_prior"]

    return out


def scan(df_with_indicators: pd.DataFrame, pattern: PatternConfig) -> pd.DataFrame:
    """Returns the subset of rows (dates) matching the pattern definition."""
    df = df_with_indicators
    rsi_lo, rsi_hi = pattern.rsi_range
    match = (
        (df["gap_pct"] >= pattern.gap_pct_min)
        & (df["rsi_prior"] >= rsi_lo)
        & (df["rsi_prior"] <= rsi_hi)
        & (df["volume_ratio"] >= pattern.volume_multiple)
    )
    return df[match].copy()


def forward_returns(
    df_with_indicators: pd.DataFrame,
    matches: pd.DataFrame,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> tuple[dict[int, list[dict[str, Any]]], dict[int, int]]:
    """For each matched date, compute the pct return from that day's close to
    the close `h` trading days later, for each horizon `h`. Matches too close
    to the end of the available history to reach a given horizon are counted
    in `excluded` rather than silently dropped."""
    close = df_with_indicators["close"]
    position = {date: i for i, date in enumerate(df_with_indicators.index)}

    returns: dict[int, list[dict[str, Any]]] = {h: [] for h in horizons}
    excluded: dict[int, int] = {h: 0 for h in horizons}

    for date in matches.index:
        i = position[date]
        entry_price = close.iloc[i]
        for h in horizons:
            j = i + h
            if j < len(close):
                exit_price = close.iloc[j]
                pct = (exit_price / entry_price - 1) * 100
                returns[h].append({"date": date.strftime("%Y-%m-%d"), "return_pct": float(pct)})
            else:
                excluded[h] += 1

    return returns, excluded


def summarize_horizon(returns_list: list[dict[str, Any]]) -> dict[str, Any]:
    """Occurrence count, win rate, average/median return, and the return
    distribution for one horizon's set of matched-and-resolved returns."""
    if not returns_list:
        return {
            "count": 0,
            "win_rate_pct": None,
            "avg_return_pct": None,
            "median_return_pct": None,
            "distribution": None,
        }

    vals = np.array([r["return_pct"] for r in returns_list], dtype=float)
    count = int(len(vals))

    return {
        "count": count,
        "win_rate_pct": float((vals > 0).mean() * 100),
        "avg_return_pct": float(vals.mean()),
        "median_return_pct": float(np.median(vals)),
        "distribution": {
            "min_pct": float(vals.min()),
            "p25_pct": float(np.percentile(vals, 25)),
            "p75_pct": float(np.percentile(vals, 75)),
            "max_pct": float(vals.max()),
            "std_dev_pct": float(vals.std(ddof=1)) if count > 1 else 0.0,
        },
    }
