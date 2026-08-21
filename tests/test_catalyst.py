import json
from datetime import datetime, timezone

import pytest

from premarket_analog import catalyst as catalyst_module
from premarket_analog.catalyst import (
    Article,
    _extract_relevant_articles,
    fetch_earnings_date,
    fetch_news_sentiment,
    get_catalyst_context,
)
from premarket_analog.data import DataUnavailable


def _feed_item(ticker: str, relevance: float, title: str = "Some headline") -> dict:
    return {
        "title": title,
        "source": "Example Wire",
        "url": f"https://example.com/{title.replace(' ', '-')}",
        "time_published": "20260821T090000",
        "summary": "Example summary text.",
        "ticker_sentiment": [{"ticker": ticker, "relevance_score": str(relevance)}],
    }


def test_extract_relevant_articles_filters_by_relevance():
    feed = [_feed_item("AAPL", 0.9), _feed_item("AAPL", 0.05)]  # second below MIN_RELEVANCE
    articles = _extract_relevant_articles(feed, "AAPL")
    assert len(articles) == 1
    assert articles[0].relevance_score == pytest.approx(0.9)


def test_extract_relevant_articles_ignores_other_tickers():
    feed = [_feed_item("MSFT", 0.95)]
    articles = _extract_relevant_articles(feed, "AAPL")
    assert articles == []


def test_extract_relevant_articles_sorts_desc_and_caps_at_three():
    feed = [_feed_item("AAPL", r, title=f"headline {r}") for r in [0.2, 0.9, 0.5, 0.8, 0.3]]
    articles = _extract_relevant_articles(feed, "AAPL")
    assert len(articles) == 3
    assert [a.relevance_score for a in articles] == [0.9, 0.8, 0.5]


def test_fetch_news_sentiment_requires_api_key_or_data_dir():
    with pytest.raises(DataUnavailable):
        fetch_news_sentiment("AAPL")


def test_fetch_news_sentiment_loads_from_data_dir(tmp_path):
    payload = {"feed": [_feed_item("AAPL", 0.8)]}
    (tmp_path / "AAPL_news.json").write_text(json.dumps(payload))

    articles = fetch_news_sentiment("AAPL", data_dir=str(tmp_path))
    assert len(articles) == 1
    assert isinstance(articles[0], Article)


def test_fetch_news_sentiment_missing_data_dir_file_raises(tmp_path):
    with pytest.raises(DataUnavailable):
        fetch_news_sentiment("AAPL", data_dir=str(tmp_path))


def test_fetch_news_sentiment_rest_path(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"feed": [_feed_item("AAPL", 0.7)]}

    monkeypatch.setattr(catalyst_module, "wait_for_slot", lambda: 0.0)
    monkeypatch.setattr(catalyst_module.requests, "get", lambda *a, **k: FakeResponse())
    from premarket_analog import data as data_module

    data_module.reset_api_call_count()
    articles = fetch_news_sentiment("AAPL", api_key="fake-key")
    assert len(articles) == 1
    assert data_module.get_api_call_count() == 1


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def test_fetch_earnings_date_matches_today(tmp_path):
    csv_text = (
        "symbol,name,reportDate,fiscalDateEnding,estimate,currency\n"
        f"AAPL,Apple Inc,{_today_iso()},2026-09-30,1.50,USD\n"
    )
    (tmp_path / "AAPL_earnings.csv").write_text(csv_text)

    result = fetch_earnings_date("AAPL", data_dir=str(tmp_path))
    assert result is not None
    assert result["symbol"] == "AAPL"


def test_fetch_earnings_date_no_match_returns_none(tmp_path):
    csv_text = "symbol,name,reportDate,fiscalDateEnding,estimate,currency\nAAPL,Apple Inc,2099-01-01,2099-03-31,1.50,USD\n"
    (tmp_path / "AAPL_earnings.csv").write_text(csv_text)

    result = fetch_earnings_date("AAPL", data_dir=str(tmp_path))
    assert result is None


def test_get_catalyst_context_prefers_news(tmp_path):
    payload = {"feed": [_feed_item("AAPL", 0.8)]}
    (tmp_path / "AAPL_news.json").write_text(json.dumps(payload))

    context = get_catalyst_context("AAPL", data_dir=str(tmp_path))
    assert context["note"] == "relevant news found"
    assert len(context["articles"]) == 1
    assert context["earnings"] is None


def test_get_catalyst_context_falls_back_to_earnings(tmp_path):
    (tmp_path / "AAPL_news.json").write_text(json.dumps({"feed": []}))
    csv_text = (
        "symbol,name,reportDate,fiscalDateEnding,estimate,currency\n"
        f"AAPL,Apple Inc,{_today_iso()},2026-09-30,1.50,USD\n"
    )
    (tmp_path / "AAPL_earnings.csv").write_text(csv_text)

    context = get_catalyst_context("AAPL", data_dir=str(tmp_path))
    assert context["articles"] == []
    assert context["earnings"] is not None
    assert "earnings" in context["note"]


def test_get_catalyst_context_no_clear_catalyst(tmp_path):
    (tmp_path / "AAPL_news.json").write_text(json.dumps({"feed": []}))
    csv_text = "symbol,name,reportDate,fiscalDateEnding,estimate,currency\nAAPL,Apple Inc,2099-01-01,2099-03-31,1.50,USD\n"
    (tmp_path / "AAPL_earnings.csv").write_text(csv_text)

    context = get_catalyst_context("AAPL", data_dir=str(tmp_path))
    assert context["note"] == "no clear catalyst found"
    assert context["articles"] == []
    assert context["earnings"] is None


def test_get_catalyst_context_propagates_news_error(tmp_path):
    context = get_catalyst_context("AAPL", data_dir=str(tmp_path))
    assert "error" in context
