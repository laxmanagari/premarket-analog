import numpy as np
import pandas as pd

from premarket_analog.indicators import rolling_avg_volume, rsi, sma


def test_rsi_all_gains_is_100():
    # A strictly increasing series has no losses in the lookback -> RSI = 100.
    close = pd.Series(np.arange(1, 30, dtype=float))
    result = rsi(close, period=14)
    assert result.iloc[-1] == 100.0


def test_rsi_all_losses_is_0():
    close = pd.Series(np.arange(30, 1, -1, dtype=float))
    result = rsi(close, period=14)
    assert result.iloc[-1] == 0.0


def test_rsi_bounded_0_100():
    rng = np.random.default_rng(42)
    close = pd.Series(100 + np.cumsum(rng.normal(0, 1, 200)))
    result = rsi(close, period=14).dropna()
    assert (result >= 0).all()
    assert (result <= 100).all()


def test_sma_matches_manual_mean():
    close = pd.Series([1, 2, 3, 4, 5], dtype=float)
    result = sma(close, period=3)
    assert np.isnan(result.iloc[0])
    assert np.isnan(result.iloc[1])
    assert result.iloc[2] == 2.0  # mean(1,2,3)
    assert result.iloc[4] == 4.0  # mean(3,4,5)


def test_rolling_avg_volume_window():
    volume = pd.Series([10, 20, 30, 40, 50], dtype=float)
    result = rolling_avg_volume(volume, window=2)
    assert np.isnan(result.iloc[0])
    assert result.iloc[1] == 15.0
    assert result.iloc[4] == 45.0
