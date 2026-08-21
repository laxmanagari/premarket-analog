"""Technical indicator calculations used by the pattern scanner."""

from __future__ import annotations

import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI, computed via an exponential moving average approximation."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    result = 100 - (100 / (1 + rs))
    # When there are no losses in the lookback, RSI is defined as 100.
    result = result.where(avg_loss != 0, 100.0)
    return result


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()


def rolling_avg_volume(volume: pd.Series, window: int) -> pd.Series:
    return volume.rolling(window=window, min_periods=window).mean()
