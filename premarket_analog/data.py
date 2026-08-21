"""Price history retrieval: Alpha Vantage primary, yfinance fallback, or a
local cache of pre-fetched Alpha Vantage JSON (for environments where direct
outbound access to Alpha Vantage's REST API or yfinance's Yahoo Finance
backend is network-restricted, e.g. a sandboxed cloud agent that only has
Alpha Vantage via an MCP connector). See `load_alpha_vantage_file` and the
`data_dir` parameter of `get_price_history`.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests

ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"

REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]


class DataUnavailable(Exception):
    """Raised when no data source could produce price history for a ticker."""


class AlphaVantageUnavailable(Exception):
    """Raised when Alpha Vantage cannot serve the request (rate limit, premium-only
    endpoint, bad symbol, etc.) so the caller can fall back to yfinance."""


@dataclass
class PriceHistory:
    ticker: str
    df: pd.DataFrame
    source: str  # "alpha_vantage", "alpha_vantage_file", or "yfinance"


_api_call_count = 0


def get_api_call_count() -> int:
    """Total number of real Alpha Vantage REST requests made so far in this
    process (a single TIME_SERIES_DAILY_ADJUSTED call per ticker -- loading
    from --data-dir or falling back to yfinance never increments this)."""
    return _api_call_count


def reset_api_call_count() -> None:
    global _api_call_count
    _api_call_count = 0


def _dataframe_from_daily_series(raw: dict) -> pd.DataFrame:
    """Parses the "Time Series (Daily)" object shared by Alpha Vantage's
    TIME_SERIES_DAILY and TIME_SERIES_DAILY_ADJUSTED endpoints. If adjusted-close
    is present (the _ADJUSTED variant), OHLC is scaled by the split/dividend
    adjustment ratio to match yfinance's auto_adjust behavior; otherwise OHLC is
    returned as-is (the plain endpoint has no adjusted figures to scale by)."""
    df = pd.DataFrame.from_dict(raw, orient="index")
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    df = df.rename(
        columns={
            "1. open": "open",
            "2. high": "high",
            "3. low": "low",
            "4. close": "close",
            "5. adjusted close": "adj_close",
            "5. volume": "volume",
            "6. volume": "volume",
        }
    )
    df = df.astype(float)

    if "adj_close" in df.columns:
        ratio = df["adj_close"] / df["close"]
        for col in ["open", "high", "low", "close"]:
            df[col] = df[col] * ratio

    return df[REQUIRED_COLUMNS]


def _parse_alpha_vantage_payload(payload: dict) -> pd.DataFrame:
    ts_key = "Time Series (Daily)"
    if ts_key not in payload:
        reason = (
            payload.get("Note")
            or payload.get("Error Message")
            or payload.get("Information")
            or (payload.get("error", {}).get("message") if isinstance(payload.get("error"), dict) else None)
            or f"unexpected response shape: {list(payload.keys())}"
        )
        raise AlphaVantageUnavailable(reason)

    raw = payload[ts_key]
    if not raw:
        raise AlphaVantageUnavailable("empty time series")

    return _dataframe_from_daily_series(raw)


def _fetch_alpha_vantage(ticker: str, api_key: str) -> pd.DataFrame:
    global _api_call_count
    params = {
        "function": "TIME_SERIES_DAILY_ADJUSTED",
        "symbol": ticker,
        "outputsize": "full",
        "apikey": api_key,
    }
    resp = requests.get(ALPHA_VANTAGE_URL, params=params, timeout=30)
    _api_call_count += 1  # count the request itself, even if AV returns an error payload
    resp.raise_for_status()
    return _parse_alpha_vantage_payload(resp.json())


def load_alpha_vantage_file(path: Path) -> pd.DataFrame:
    """Loads a locally cached Alpha Vantage TIME_SERIES_DAILY(_ADJUSTED) JSON
    response -- the same shape the REST API and its MCP-tool equivalent both
    return -- from disk, for environments where fetching it directly isn't
    possible."""
    with open(path) as f:
        payload = json.load(f)
    return _parse_alpha_vantage_payload(payload)


def _fetch_yfinance(ticker: str) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise DataUnavailable(
            "yfinance is not installed; run `pip install yfinance` or set "
            "ALPHAVANTAGE_API_KEY"
        ) from exc

    df = yf.download(
        ticker,
        period="max",
        auto_adjust=True,
        progress=False,
        multi_level_index=False,
    )
    if df is None or df.empty:
        raise DataUnavailable(f"yfinance returned no data for {ticker!r}")

    df = df.rename(columns=str.lower)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise DataUnavailable(f"yfinance response missing columns: {missing}")

    return df[REQUIRED_COLUMNS].astype(float)


def get_price_history(
    ticker: str, api_key: str | None = None, data_dir: str | Path | None = None
) -> PriceHistory:
    """Fetch daily OHLCV for `ticker`.

    - If `data_dir` is given, looks for a pre-fetched `{data_dir}/{TICKER}.json`
      Alpha Vantage response and loads it directly -- no network call at all.
      This is for environments (e.g. a sandboxed cloud agent) where an MCP
      connector can reach Alpha Vantage but the process itself can't reach the
      open internet; something else is expected to have saved that file first.
      A missing file is a hard error, not a silent fallback to network calls
      that are presumably also unreachable there.
    - Otherwise, tries Alpha Vantage's REST API first if `api_key` is set, then
      falls back to yfinance on any failure (missing key, rate limit,
      premium-only endpoint, bad symbol, network error).
    """
    ticker = ticker.upper().strip()

    if data_dir is not None:
        path = Path(data_dir) / f"{ticker}.json"
        if not path.exists():
            raise DataUnavailable(f"no cached data file at {path} for {ticker!r}")
        df = load_alpha_vantage_file(path)
        return PriceHistory(ticker=ticker, df=df, source="alpha_vantage_file")

    if api_key:
        try:
            df = _fetch_alpha_vantage(ticker, api_key)
            return PriceHistory(ticker=ticker, df=df, source="alpha_vantage")
        except (AlphaVantageUnavailable, requests.RequestException) as exc:
            print(
                f"[premarket-analog] Alpha Vantage unavailable for {ticker} "
                f"({exc}); falling back to yfinance.",
                file=sys.stderr,
            )

    df = _fetch_yfinance(ticker)
    return PriceHistory(ticker=ticker, df=df, source="yfinance")
