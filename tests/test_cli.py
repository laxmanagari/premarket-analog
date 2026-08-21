from premarket_analog.cli import _normalize_argv, _parse_tickers, build_arg_parser


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


def test_normalize_argv_defaults_bare_ticker_to_backtest():
    assert _normalize_argv(["AAPL", "--peers", "MSFT"]) == ["backtest", "AAPL", "--peers", "MSFT"]


def test_normalize_argv_leaves_explicit_subcommand_alone():
    assert _normalize_argv(["screen", "AAPL"]) == ["screen", "AAPL"]
    assert _normalize_argv(["backtest", "AAPL"]) == ["backtest", "AAPL"]


def test_normalize_argv_leaves_help_alone():
    assert _normalize_argv(["--help"]) == ["--help"]


def test_normalize_argv_defaults_empty_to_backtest():
    assert _normalize_argv([]) == ["backtest"]
