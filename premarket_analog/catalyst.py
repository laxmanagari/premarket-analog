"""Fetches raw catalyst material for a ticker -- recent relevant news (Alpha
Vantage NEWS_SENTIMENT), falling back to an earnings-date check (Alpha
Vantage EARNINGS_CALENDAR) if no relevant news is found.

This module only fetches and structures data (title, source, url, summary,
relevance); it does not write a narrative. Turning "these are the top 3
relevant articles" into a 2-3 sentence plain-language paraphrase of what's
actually driving the move is a language task, not a data-plumbing one -- it's
left to whoever is consuming this (a human reading the CLI's output, or an
agent orchestrating a run) as the tool's own README documents.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from .data import ALPHA_VANTAGE_URL, AlphaVantageUnavailable, DataUnavailable, _increment_api_call_count
from .ratelimit import wait_for_slot

MIN_RELEVANCE = 0.15
MAX_ARTICLES = 3


@dataclass
class Article:
    title: str
    source: str
    url: str
    time_published: str
    summary: str
    relevance_score: float


def _start_of_today_av_format() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT0000")


def _extract_relevant_articles(feed: list[dict], ticker: str) -> list[Article]:
    scored: list[Article] = []
    for item in feed:
        relevance = 0.0
        for ts in item.get("ticker_sentiment", []):
            if ts.get("ticker", "").upper() == ticker.upper():
                try:
                    relevance = float(ts.get("relevance_score", 0.0))
                except (TypeError, ValueError):
                    relevance = 0.0
                break
        if relevance < MIN_RELEVANCE:
            continue
        scored.append(
            Article(
                title=item.get("title", ""),
                source=item.get("source", ""),
                url=item.get("url", ""),
                time_published=item.get("time_published", ""),
                summary=item.get("summary", ""),
                relevance_score=relevance,
            )
        )
    scored.sort(key=lambda a: a.relevance_score, reverse=True)
    return scored[:MAX_ARTICLES]


def _fetch_news_sentiment_rest(ticker: str, api_key: str, limit: int) -> list[Article]:
    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": ticker,
        "time_from": _start_of_today_av_format(),
        "sort": "RELEVANCE",
        "limit": str(limit),
        "apikey": api_key,
    }
    wait_for_slot()
    resp = requests.get(ALPHA_VANTAGE_URL, params=params, timeout=30)
    _increment_api_call_count()
    resp.raise_for_status()
    payload = resp.json()

    if "feed" not in payload:
        reason = payload.get("Note") or payload.get("Error Message") or payload.get("Information") or str(payload)
        raise AlphaVantageUnavailable(reason)

    return _extract_relevant_articles(payload["feed"], ticker)


def _load_news_sentiment_file(path: Path, ticker: str) -> list[Article]:
    with open(path) as f:
        payload = json.load(f)
    if "feed" not in payload:
        raise DataUnavailable(f"cached news file at {path} has no 'feed' key")
    return _extract_relevant_articles(payload["feed"], ticker)


def fetch_news_sentiment(
    ticker: str, api_key: str | None = None, data_dir: str | Path | None = None, limit: int = 10
) -> list[Article]:
    """Returns up to 3 recent, relevant articles for `ticker`, sorted by
    relevance. Empty list means no sufficiently relevant news was found (not
    an error) -- the caller should fall back to `fetch_earnings_date`."""
    ticker = ticker.upper().strip()

    if data_dir is not None:
        path = Path(data_dir) / f"{ticker}_news.json"
        if not path.exists():
            raise DataUnavailable(f"no cached news file at {path} for {ticker!r}")
        return _load_news_sentiment_file(path, ticker)

    if not api_key:
        raise DataUnavailable("NEWS_SENTIMENT requires an Alpha Vantage API key (no yfinance equivalent)")

    return _fetch_news_sentiment_rest(ticker, api_key, limit)


def _parse_earnings_csv(text: str, ticker: str) -> dict | None:
    reader = csv.DictReader(io.StringIO(text))
    today = datetime.now(timezone.utc).date().isoformat()
    for row in reader:
        if row.get("symbol", "").upper() == ticker.upper() and row.get("reportDate") == today:
            return dict(row)
    return None


def _fetch_earnings_calendar_rest(ticker: str, api_key: str) -> dict | None:
    params = {"function": "EARNINGS_CALENDAR", "symbol": ticker, "horizon": "3month", "apikey": api_key}
    wait_for_slot()
    resp = requests.get(ALPHA_VANTAGE_URL, params=params, timeout=30)
    _increment_api_call_count()
    resp.raise_for_status()
    return _parse_earnings_csv(resp.text, ticker)


def _load_earnings_calendar_file(path: Path, ticker: str) -> dict | None:
    with open(path) as f:
        text = f.read()
    return _parse_earnings_csv(text, ticker)


def fetch_earnings_date(ticker: str, api_key: str | None = None, data_dir: str | Path | None = None) -> dict | None:
    """Returns the earnings-calendar row for `ticker` if today is its
    reportDate, else None. Used as a fallback when NEWS_SENTIMENT turns up
    nothing relevant, since an earnings date alone is a plausible catalyst
    even before news coverage catches up."""
    ticker = ticker.upper().strip()

    if data_dir is not None:
        path = Path(data_dir) / f"{ticker}_earnings.csv"
        if not path.exists():
            raise DataUnavailable(f"no cached earnings file at {path} for {ticker!r}")
        return _load_earnings_calendar_file(path, ticker)

    if not api_key:
        raise DataUnavailable("EARNINGS_CALENDAR requires an Alpha Vantage API key (no yfinance equivalent)")

    return _fetch_earnings_calendar_rest(ticker, api_key)


def get_catalyst_context(
    ticker: str, api_key: str | None = None, data_dir: str | Path | None = None
) -> dict:
    """Structured raw catalyst material for one ticker: relevant articles if
    any were found, else an earnings-date check, else an explicit "no clear
    catalyst found" -- never a guess. Returns a dict with `ticker`, `articles`
    (list of Article, possibly empty), `earnings` (dict or None), and `note`
    (a short explanation of which path applies), or `error` on failure."""
    ticker = ticker.upper().strip()
    try:
        articles = fetch_news_sentiment(ticker, api_key=api_key, data_dir=data_dir)
    except (DataUnavailable, AlphaVantageUnavailable) as exc:
        return {"ticker": ticker, "error": str(exc)}

    if articles:
        return {"ticker": ticker, "articles": articles, "earnings": None, "note": "relevant news found"}

    try:
        earnings = fetch_earnings_date(ticker, api_key=api_key, data_dir=data_dir)
    except (DataUnavailable, AlphaVantageUnavailable) as exc:
        return {"ticker": ticker, "error": str(exc)}

    if earnings:
        return {
            "ticker": ticker,
            "articles": [],
            "earnings": earnings,
            "note": "no relevant news; today matches an earnings report date",
        }

    return {
        "ticker": ticker,
        "articles": [],
        "earnings": None,
        "note": "no clear catalyst found",
    }
