import pandas as pd
import pytest

from premarket_analog import screener as screener_module
from premarket_analog.data import DataUnavailable, PriceHistory
from premarket_analog.pattern import PatternConfig
from premarket_analog.screener import LiveQuote, screen_candidates, screen_ticker


def _dummy_history() -> PriceHistory:
    idx = pd.bdate_range("2024-01-02", periods=5)
    df = pd.DataFrame(
        {
            "open": [100.0] * 5,
            "high": [101.0] * 5,
            "low": [99.0] * 5,
            "close": [100.0] * 5,
            "volume": [1000.0] * 5,
        },
        index=idx,
    )
    return PriceHistory(ticker="TEST", df=df, source="yfinance")


def _enriched_with_rsi(rsi_value: float | None):
    def fake_compute_indicators(df, pattern):
        out = df.copy()
        out["rsi"] = rsi_value
        return out

    return fake_compute_indicators


def test_screen_ticker_matches_when_gap_and_rsi_both_pass(monkeypatch):
    monkeypatch.setattr(screener_module, "get_price_history", lambda t, api_key=None: _dummy_history())
    monkeypatch.setattr(screener_module, "compute_indicators", _enriched_with_rsi(60.0))
    monkeypatch.setattr(
        screener_module, "fetch_live_quote", lambda t: LiveQuote(ticker=t, price=103.0, previous_close=100.0)
    )
    pattern = PatternConfig(gap_pct_min=2.0, rsi_range=(50, 70))

    result = screen_ticker("TEST", pattern)

    assert result["gap_pct"] == pytest.approx(3.0)
    assert result["gap_match"] is True
    assert result["prior_rsi"] == 60.0
    assert result["rsi_match"] is True
    assert result["matched"] is True
    assert result["note"] == screener_module.VOLUME_UNAVAILABLE_NOTE


def test_screen_ticker_fails_when_gap_too_small(monkeypatch):
    monkeypatch.setattr(screener_module, "get_price_history", lambda t, api_key=None: _dummy_history())
    monkeypatch.setattr(screener_module, "compute_indicators", _enriched_with_rsi(60.0))
    monkeypatch.setattr(
        screener_module, "fetch_live_quote", lambda t: LiveQuote(ticker=t, price=100.5, previous_close=100.0)
    )
    pattern = PatternConfig(gap_pct_min=2.0, rsi_range=(50, 70))

    result = screen_ticker("TEST", pattern)

    assert result["gap_match"] is False
    assert result["matched"] is False


def test_screen_ticker_fails_when_rsi_out_of_band(monkeypatch):
    monkeypatch.setattr(screener_module, "get_price_history", lambda t, api_key=None: _dummy_history())
    monkeypatch.setattr(screener_module, "compute_indicators", _enriched_with_rsi(85.0))
    monkeypatch.setattr(
        screener_module, "fetch_live_quote", lambda t: LiveQuote(ticker=t, price=103.0, previous_close=100.0)
    )
    pattern = PatternConfig(gap_pct_min=2.0, rsi_range=(50, 70))

    result = screen_ticker("TEST", pattern)

    assert result["gap_match"] is True
    assert result["rsi_match"] is False
    assert result["matched"] is False


def test_screen_ticker_propagates_history_error(monkeypatch):
    def failing_history(t, api_key=None):
        raise DataUnavailable("no data")

    monkeypatch.setattr(screener_module, "get_price_history", failing_history)
    result = screen_ticker("BADTICKER", PatternConfig())
    assert result == {"ticker": "BADTICKER", "error": "no data"}


def test_screen_ticker_propagates_quote_error(monkeypatch):
    monkeypatch.setattr(screener_module, "get_price_history", lambda t, api_key=None: _dummy_history())
    monkeypatch.setattr(screener_module, "compute_indicators", _enriched_with_rsi(60.0))

    def failing_quote(t):
        raise DataUnavailable("no quote")

    monkeypatch.setattr(screener_module, "fetch_live_quote", failing_quote)
    result = screen_ticker("TEST", PatternConfig())
    assert result == {"ticker": "TEST", "error": "no quote"}


def test_screen_candidates_runs_each_ticker(monkeypatch):
    monkeypatch.setattr(screener_module, "get_price_history", lambda t, api_key=None: _dummy_history())
    monkeypatch.setattr(screener_module, "compute_indicators", _enriched_with_rsi(60.0))
    monkeypatch.setattr(
        screener_module, "fetch_live_quote", lambda t: LiveQuote(ticker=t, price=101.0, previous_close=100.0)
    )
    results = screen_candidates(["AAA", "BBB"], PatternConfig())
    assert [r["ticker"] for r in results] == ["AAA", "BBB"]
