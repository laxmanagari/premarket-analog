"""Live (premarket) pattern screening: checks whether a candidate ticker's
*current* gap and prior-day RSI match the pattern right now, ahead of today's
close. This is distinct from pattern.scan(), which backtests the pattern
against closed historical days.

Volume confirmation is intentionally excluded here: free live-quote data
(yfinance's fast_info) only exposes the most recently *completed* session's
volume, not volume accumulated so far in the current session, so a "volume
ratio" computed from it would just restate yesterday's already-known volume
rather than measure today's premarket activity. The historical backtest
(pattern.py) still applies the volume condition properly, since full daily
bars are legitimate there.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from .data import DataUnavailable, get_price_history
from .pattern import PatternConfig, compute_indicators

VOLUME_UNAVAILABLE_NOTE = (
    "Volume confirmation not checked live: free premarket quote data only exposes the "
    "last completed session's volume, not today's volume-so-far, so it can't reliably "
    "signal a premarket volume surge. Gap % and prior-day RSI are checked; volume is "
    "still enforced in the historical backtest."
)


@dataclass
class LiveQuote:
    ticker: str
    price: float
    previous_close: float


def fetch_live_quote(ticker: str) -> LiveQuote:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise DataUnavailable(
            "yfinance is not installed; run `pip install yfinance`"
        ) from exc

    fast_info = yf.Ticker(ticker).fast_info
    # FastInfo.get() unreliably returns None even for present keys; bracket
    # access is what actually works against yfinance's FastInfo mapping.
    try:
        price = fast_info["last_price"]
        previous_close = fast_info["previous_close"]
    except KeyError:
        raise DataUnavailable(f"no live quote available for {ticker!r}") from None

    if price is None or previous_close is None:
        raise DataUnavailable(f"no live quote available for {ticker!r}")

    return LiveQuote(ticker=ticker, price=float(price), previous_close=float(previous_close))


def screen_ticker(ticker: str, pattern: PatternConfig, api_key: str | None = None) -> dict[str, Any]:
    """Checks one ticker's current gap % and prior-day RSI against the pattern.
    Returns a result dict; on any data failure, returns {"ticker", "error"}."""
    ticker = ticker.upper().strip()

    try:
        history = get_price_history(ticker, api_key=api_key)
    except DataUnavailable as exc:
        return {"ticker": ticker, "error": str(exc)}

    enriched = compute_indicators(history.df, pattern)
    last = enriched.iloc[-1]
    prior_rsi = float(last["rsi"]) if pd.notna(last["rsi"]) else None

    try:
        quote = fetch_live_quote(ticker)
    except DataUnavailable as exc:
        return {"ticker": ticker, "error": str(exc)}

    gap_pct = (quote.price - quote.previous_close) / quote.previous_close * 100
    rsi_lo, rsi_hi = pattern.rsi_range
    gap_match = gap_pct >= pattern.gap_pct_min
    rsi_match = prior_rsi is not None and rsi_lo <= prior_rsi <= rsi_hi

    return {
        "ticker": ticker,
        "last_close_date": history.df.index.max().strftime("%Y-%m-%d"),
        "current_price": quote.price,
        "previous_close": quote.previous_close,
        "gap_pct": gap_pct,
        "gap_match": gap_match,
        "prior_rsi": prior_rsi,
        "rsi_match": rsi_match,
        "matched": gap_match and rsi_match,
        "note": VOLUME_UNAVAILABLE_NOTE,
    }


def screen_candidates(
    tickers: list[str], pattern: PatternConfig, api_key: str | None = None
) -> list[dict[str, Any]]:
    return [screen_ticker(t, pattern, api_key=api_key) for t in tickers]
