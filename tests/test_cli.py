from premarket_analog.cli import _parse_tickers


def test_parse_tickers_handles_mixed_separators_case_and_dupes():
    raw = "aapl,msft\nGOOGL\n\namzn, AAPL\n"
    assert _parse_tickers(raw) == ["AAPL", "MSFT", "GOOGL", "AMZN"]


def test_parse_tickers_empty_string():
    assert _parse_tickers("") == []


def test_parse_tickers_strips_whitespace():
    assert _parse_tickers("  aapl  ,  msft  ") == ["AAPL", "MSFT"]
