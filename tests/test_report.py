from premarket_analog.catalyst import Article
from premarket_analog.report import (
    _bar,
    _verdict,
    build_catalyst_report,
    to_catalyst_markdown,
    to_markdown,
    _render_ticker_section,
)


def _stats(count, win_rate, avg_return):
    return {
        "count": count,
        "win_rate_pct": win_rate,
        "avg_return_pct": avg_return,
        "median_return_pct": avg_return,
        "distribution": {"min_pct": -1.0, "p25_pct": -0.5, "p75_pct": 1.0, "max_pct": 2.0, "std_dev_pct": 1.0},
    }


def test_verdict_thin_sample_is_neutral_even_if_numbers_look_good():
    stats = _stats(count=2, win_rate=100.0, avg_return=15.0)
    assert _verdict(stats, min_occurrences=10) == "⚪"


def test_verdict_green_for_solid_edge():
    stats = _stats(count=100, win_rate=60.0, avg_return=2.0)
    assert _verdict(stats, min_occurrences=10) == "🟢"


def test_verdict_red_for_negative_avg():
    stats = _stats(count=100, win_rate=52.0, avg_return=-1.0)
    assert _verdict(stats, min_occurrences=10) == "🔴"


def test_verdict_red_for_low_win_rate():
    stats = _stats(count=100, win_rate=40.0, avg_return=0.5)
    assert _verdict(stats, min_occurrences=10) == "🔴"


def test_verdict_yellow_for_mixed():
    stats = _stats(count=100, win_rate=50.0, avg_return=0.5)
    assert _verdict(stats, min_occurrences=10) == "🟡"


def test_bar_scales_with_percentage():
    assert _bar(0.0, width=10) == "░" * 10
    assert _bar(100.0, width=10) == "█" * 10
    assert _bar(50.0, width=10).count("█") == 5


def test_bar_clamps_out_of_range_values():
    assert _bar(150.0, width=10) == "█" * 10
    assert _bar(-20.0, width=10) == "░" * 10


def test_to_markdown_summary_section_present_and_thin_sample_neutral():
    report = {
        "generated_at": "2026-08-21T00:00:00Z",
        "pattern": {
            "gap_pct_min": 2.0,
            "rsi_period": 14,
            "rsi_range": (50.0, 70.0),
            "volume_multiple": 1.5,
            "volume_window": 20,
        },
        "horizons": [1],
        "min_occurrences_for_significance": 10,
        "results": [
            {
                "ticker": "AAPL",
                "role": "primary",
                "data_source": "yfinance",
                "date_range": {"start": "2020-01-01", "end": "2026-08-20", "trading_days": 1000},
                "match_count": 3,
                "horizons": {1: _stats(count=3, win_rate=100.0, avg_return=10.0)},
                "warnings": [],
            }
        ],
    }
    md = to_markdown(report)
    assert "## Summary" in md
    assert "⚪" in md  # thin sample (count=3 < min_occurrences=10) must not be green


def test_catalyst_report_with_articles():
    articles = [Article(title="X raises guidance", source="Reuters", url="http://x", time_published="t", summary="s", relevance_score=0.9)]
    context = {"ticker": "AAPL", "articles": articles, "earnings": None, "note": "relevant news found"}
    report = build_catalyst_report([context])
    md = to_catalyst_markdown(report)
    assert "X raises guidance" in md
    assert "Reuters" in md
    assert "paraphrase" in md.lower()


def test_catalyst_report_no_clear_catalyst():
    context = {"ticker": "AAPL", "articles": [], "earnings": None, "note": "no clear catalyst found"}
    report = build_catalyst_report([context])
    md = to_catalyst_markdown(report)
    assert "No clear catalyst found" in md


def test_catalyst_section_renders_even_when_technical_data_errors():
    """A ticker can have working catalyst data (news) but failing price data
    (e.g. missing --data-dir file) -- the two are independent data sources,
    so the catalyst section must still show up rather than being swallowed
    by the technical-data error's early return."""
    entry = {
        "ticker": "AAPL",
        "role": "primary",
        "catalyst": {
            "articles": [
                Article(title="Beats estimates", source="Reuters", url="http://x", time_published="t", summary="s", relevance_score=0.9)
            ],
            "earnings": None,
            "note": "relevant news found",
        },
        "error": "no cached data file at /tmp/x/AAPL.json for 'AAPL'",
    }
    lines = _render_ticker_section(entry, min_occurrences=10)
    text = "\n".join(lines)
    assert "### Catalyst" in text
    assert "Beats estimates" in text
    assert "**Error:**" in text


def test_catalyst_report_error():
    context = {"ticker": "BADTICKER", "error": "no data"}
    report = build_catalyst_report([context])
    md = to_catalyst_markdown(report)
    assert "no data" in md
