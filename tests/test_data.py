import json

import pandas as pd
import pytest

from premarket_analog import data as data_module
from premarket_analog.data import (
    AlphaVantageUnavailable,
    DataUnavailable,
    get_price_history,
    load_alpha_vantage_file,
)


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


def _write_daily_payload(path, adjusted: bool) -> None:
    if adjusted:
        series = {
            "2024-01-03": {
                "1. open": "10.0",
                "2. high": "11.0",
                "3. low": "9.0",
                "4. close": "10.0",
                "5. adjusted close": "5.0",  # simulates a 2:1 split adjustment
                "6. volume": "1000",
            },
            "2024-01-02": {
                "1. open": "8.0",
                "2. high": "9.0",
                "3. low": "7.0",
                "4. close": "8.0",
                "5. adjusted close": "4.0",
                "6. volume": "500",
            },
        }
    else:
        series = {
            "2024-01-03": {
                "1. open": "10.0",
                "2. high": "11.0",
                "3. low": "9.0",
                "4. close": "10.0",
                "5. volume": "1000",
            },
            "2024-01-02": {
                "1. open": "8.0",
                "2. high": "9.0",
                "3. low": "7.0",
                "4. close": "8.0",
                "5. volume": "500",
            },
        }
    path.write_text(json.dumps({"Time Series (Daily)": series}))


def test_load_alpha_vantage_file_scales_ohlc_when_adjusted_close_present(tmp_path):
    path = tmp_path / "AAPL.json"
    _write_daily_payload(path, adjusted=True)

    df = load_alpha_vantage_file(path)

    # ratio = adjusted_close / close = 0.5 for both rows here
    assert df.loc["2024-01-03", "close"] == pytest.approx(5.0)
    assert df.loc["2024-01-03", "open"] == pytest.approx(5.0)
    assert df.loc["2024-01-02", "close"] == pytest.approx(4.0)


def test_load_alpha_vantage_file_leaves_ohlc_unscaled_without_adjusted_close(tmp_path):
    path = tmp_path / "AAPL.json"
    _write_daily_payload(path, adjusted=False)

    df = load_alpha_vantage_file(path)

    assert df.loc["2024-01-03", "close"] == pytest.approx(10.0)
    assert df.loc["2024-01-03", "open"] == pytest.approx(10.0)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_load_alpha_vantage_file_sorted_ascending(tmp_path):
    path = tmp_path / "AAPL.json"
    _write_daily_payload(path, adjusted=False)

    df = load_alpha_vantage_file(path)

    assert list(df.index.strftime("%Y-%m-%d")) == ["2024-01-02", "2024-01-03"]


def test_get_price_history_uses_data_dir_without_network(tmp_path, monkeypatch):
    _write_daily_payload(tmp_path / "AAPL.json", adjusted=False)

    def unexpected_call(*a, **k):
        raise AssertionError("should not hit the network when data_dir is set")

    monkeypatch.setattr(data_module, "_fetch_alpha_vantage", unexpected_call)
    monkeypatch.setattr(data_module, "_fetch_yfinance", unexpected_call)

    result = get_price_history("AAPL", api_key="unused-because-data-dir-wins", data_dir=str(tmp_path))

    assert result.source == "alpha_vantage_file"
    assert len(result.df) == 2


def test_get_price_history_missing_data_dir_file_raises(tmp_path):
    with pytest.raises(DataUnavailable):
        get_price_history("MISSING", data_dir=str(tmp_path))
