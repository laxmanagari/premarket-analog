import pandas as pd

from premarket_analog.cli import _normalize_argv, _parse_tickers, _scan_ticker_for_pool, build_arg_parser
from premarket_analog.data import DataUnavailable, PriceHistory
from premarket_analog.pattern import PatternConfig


def test_parse_tickers_handles_mixed_separators_case_and_dupes():
    raw = "aapl,msft\nGOOGL\n\namzn, AAPL\n"
    assert _parse_tickers(raw) == ["AAPL", "MSFT", "GOOGL", "AMZN"]


def test_parse_tickers_empty_string():
    assert _parse_tickers("") == []


def test_parse_tickers_strips_whitespace():
    assert _parse_tickers("  aapl  ,  msft  ") == ["AAPL", "MSFT"]


def test_backtest_subcommand_parses_ticker_and_peers():
    parser = build_arg_parser()
    args = parser.parse_args(["backtest", "AAPL", "--peers", "MSFT,GOOGL"])
    assert args.command == "backtest"
    assert args.ticker == "AAPL"
    assert args.peers == "MSFT,GOOGL"


def test_screen_subcommand_parses_tickers():
    parser = build_arg_parser()
    args = parser.parse_args(["screen", "AAPL", "MSFT"])
    assert args.command == "screen"
    assert args.tickers == ["AAPL", "MSFT"]


def test_backtest_subcommand_parses_data_dir():
    parser = build_arg_parser()
    args = parser.parse_args(["backtest", "AAPL", "--data-dir", "/tmp/av"])
    assert args.data_dir == "/tmp/av"


def test_screen_subcommand_parses_data_dir_and_quotes_file():
    parser = build_arg_parser()
    args = parser.parse_args(
        ["screen", "AAPL", "--data-dir", "/tmp/av", "--quotes-file", "/tmp/av/quotes.json"]
    )
    assert args.data_dir == "/tmp/av"
    assert args.quotes_file == "/tmp/av/quotes.json"


def test_data_dir_defaults_to_none():
    parser = build_arg_parser()
    args = parser.parse_args(["backtest", "AAPL"])
    assert args.data_dir is None


def test_pool_subcommand_parses_explicit_tickers():
    parser = build_arg_parser()
    args = parser.parse_args(["pool", "AAPL", "MSFT", "GOOGL"])
    assert args.command == "pool"
    assert args.tickers == ["AAPL", "MSFT", "GOOGL"]


def test_pool_subcommand_tickers_optional():
    parser = build_arg_parser()
    args = parser.parse_args(["pool"])
    assert args.tickers == []


def test_pool_subcommand_parses_pattern_and_output_args():
    parser = build_arg_parser()
    args = parser.parse_args(["pool", "AAPL", "--gap-pct-min", "3", "--format", "json"])
    assert args.gap_pct_min == 3.0
    assert args.format == "json"


def test_scan_ticker_for_pool_returns_error_on_missing_data(monkeypatch):
    import premarket_analog.cli as cli_module

    def failing(ticker, api_key=None, data_dir=None):
        raise DataUnavailable("no data")

    monkeypatch.setattr(cli_module, "get_price_history", failing)
    returns, error = _scan_ticker_for_pool("BADTICKER", PatternConfig(), (1, 5, 20), None, None)
    assert returns is None
    assert error == "no data"


def test_scan_ticker_for_pool_returns_data_on_success(monkeypatch):
    import premarket_analog.cli as cli_module

    idx = pd.bdate_range("2024-01-02", periods=40)
    df = pd.DataFrame(
        {
            "open": [100.0] * 40,
            "high": [101.0] * 40,
            "low": [99.0] * 40,
            "close": [100.0] * 40,
            "volume": [1000.0] * 40,
        },
        index=idx,
    )
    monkeypatch.setattr(
        cli_module, "get_price_history", lambda ticker, api_key=None, data_dir=None: PriceHistory(
            ticker=ticker, df=df, source="yfinance"
        )
    )
    returns, error = _scan_ticker_for_pool("AAPL", PatternConfig(), (1, 5, 20), None, None)
    assert error is None
    assert set(returns.keys()) == {1, 5, 20}


def test_normalize_argv_defaults_bare_ticker_to_backtest():
    assert _normalize_argv(["AAPL", "--peers", "MSFT"]) == ["backtest", "AAPL", "--peers", "MSFT"]


def test_normalize_argv_leaves_explicit_subcommand_alone():
    assert _normalize_argv(["screen", "AAPL"]) == ["screen", "AAPL"]
    assert _normalize_argv(["backtest", "AAPL"]) == ["backtest", "AAPL"]


def test_normalize_argv_leaves_help_alone():
    assert _normalize_argv(["--help"]) == ["--help"]


def test_normalize_argv_defaults_empty_to_backtest():
    assert _normalize_argv([]) == ["backtest"]
