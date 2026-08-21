import pandas as pd
import pytest

from premarket_analog import data as data_module
from premarket_analog.data import AlphaVantageUnavailable, get_price_history


def _dummy_df():
    idx = pd.bdate_range("2024-01-02", periods=3)
    return pd.DataFrame(
        {"open": [1.0, 2.0, 3.0], "high": [1, 2, 3], "low": [1, 2, 3], "close": [1, 2, 3], "volume": [10, 20, 30]},
        index=idx,
    )


def test_no_api_key_goes_straight_to_yfinance(monkeypatch):
    calls = {"av": 0, "yf": 0}

    def fake_yf(ticker):
        calls["yf"] += 1
        return _dummy_df()

    monkeypatch.setattr(data_module, "_fetch_alpha_vantage", lambda *a, **k: calls.__setitem__("av", calls["av"] + 1))
    monkeypatch.setattr(data_module, "_fetch_yfinance", fake_yf)

    result = get_price_history("AAPL", api_key=None)
    assert result.source == "yfinance"
    assert calls["av"] == 0
    assert calls["yf"] == 1


def test_alpha_vantage_success_skips_yfinance(monkeypatch):
    calls = {"yf": 0}
    monkeypatch.setattr(data_module, "_fetch_alpha_vantage", lambda ticker, api_key: _dummy_df())
    monkeypatch.setattr(data_module, "_fetch_yfinance", lambda ticker: calls.__setitem__("yf", 1))

    result = get_price_history("AAPL", api_key="fake-key")
    assert result.source == "alpha_vantage"
    assert calls["yf"] == 0


def test_alpha_vantage_failure_falls_back_to_yfinance(monkeypatch):
    def failing_av(ticker, api_key):
        raise AlphaVantageUnavailable("rate limited")

    monkeypatch.setattr(data_module, "_fetch_alpha_vantage", failing_av)
    monkeypatch.setattr(data_module, "_fetch_yfinance", lambda ticker: _dummy_df())

    result = get_price_history("AAPL", api_key="fake-key")
    assert result.source == "yfinance"


def test_ticker_is_uppercased_and_stripped(monkeypatch):
    monkeypatch.setattr(data_module, "_fetch_yfinance", lambda ticker: _dummy_df())
    result = get_price_history("  aapl  ", api_key=None)
    assert result.ticker == "AAPL"
