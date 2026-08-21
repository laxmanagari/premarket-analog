"""Price history retrieval: Alpha Vantage primary, yfinance fallback."""

from __future__ import annotations

import sys
from dataclasses import dataclass

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
    source: str  # "alpha_vantage" or "yfinance"


def _fetch_alpha_vantage(ticker: str, api_key: str) -> pd.DataFrame:
    params = {
        "function": "TIME_SERIES_DAILY_ADJUSTED",
        "symbol": ticker,
        "outputsize": "full",
        "apikey": api_key,
    }
    resp = requests.get(ALPHA_VANTAGE_URL, params=params, timeout=30)
    resp.raise_for_status()
    payload = resp.json()

    ts_key = "Time Series (Daily)"
    if ts_key not in payload:
        reason = (
            payload.get("Note")
            or payload.get("Error Message")
            or payload.get("Information")
            or f"unexpected response shape: {list(payload.keys())}"
        )
        raise AlphaVantageUnavailable(reason)

    raw = payload[ts_key]
    if not raw:
        raise AlphaVantageUnavailable("empty time series")

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
            "6. volume": "volume",
        }
    )
    df = df.astype(float)

    # Scale OHLC by the split/dividend adjustment ratio so gap/return math is
    # consistent across corporate actions, matching yfinance's auto_adjust behavior.
    ratio = df["adj_close"] / df["close"]
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col] * ratio

    return df[REQUIRED_COLUMNS]


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


def get_price_history(ticker: str, api_key: str | None = None) -> PriceHistory:
    """Fetch daily OHLCV for `ticker`. Tries Alpha Vantage first if `api_key` is
    set, then falls back to yfinance on any failure (missing key, rate limit,
    premium-only endpoint, bad symbol, network error)."""
    ticker = ticker.upper().strip()

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
