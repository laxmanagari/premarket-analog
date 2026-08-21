"""premarket-analog: scan historical price action for a premarket-gap analog
pattern, and optionally check candidates against it live before today's close.

Usage:
    premarket-analog backtest AAPL --peers MSFT,GOOGL,AMZN
    printf "AAPL\\nMSFT\\nGOOGL\\nAMZN\\nNVDA\\n" | premarket-analog backtest --format json
    printf "AAPL\\nMSFT\\nGOOGL\\n" | premarket-analog screen

`backtest` is also the default subcommand: `premarket-analog AAPL ...` still
works without typing `backtest` explicitly.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from .data import DataUnavailable, get_price_history
from .pattern import PatternConfig, compute_indicators, forward_returns, scan, summarize_horizon
from .report import build_report, build_screen_report, to_json, to_markdown, to_screen_markdown
from .screener import screen_candidates

API_KEY_ENV_VAR = "ALPHAVANTAGE_API_KEY"
SUBCOMMANDS = ("backtest", "screen")


def _parse_tickers(raw: str) -> list[str]:
    parts = [p.strip().upper() for chunk in raw.splitlines() for p in chunk.split(",")]
    seen: set[str] = set()
    ordered: list[str] = []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered


def _read_stdin_tickers() -> list[str]:
    if sys.stdin.isatty():
        return []
    return _parse_tickers(sys.stdin.read())


def _add_pattern_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--gap-pct-min", type=float, help="Minimum overnight gap %% (default 2.0).")
    parser.add_argument("--rsi-min", type=float, help="Minimum prior-day RSI(14) (default 50).")
    parser.add_argument("--rsi-max", type=float, help="Maximum prior-day RSI(14) (default 70).")
    parser.add_argument(
        "--volume-multiple", type=float, help="Minimum volume vs. trailing average (default 1.5)."
    )
    parser.add_argument(
        "--volume-window", type=int, help="Trailing window (days) for the average volume baseline (default 20)."
    )
    parser.add_argument("--pattern-config", help="Path to a JSON file overriding default pattern parameters.")


def _add_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", help="Write the report to this file instead of stdout.")


def _add_data_source_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--api-key",
        help=f"Alpha Vantage API key. Defaults to the {API_KEY_ENV_VAR} env var; "
        "falls back to yfinance if unset or unavailable.",
    )
    parser.add_argument(
        "--data-dir",
        help="Directory of pre-fetched Alpha Vantage TIME_SERIES_DAILY(_ADJUSTED) JSON "
        "files, one per ticker as {data_dir}/{TICKER}.json. When set, price history is "
        "loaded directly from these files instead of any network call -- for "
        "environments (e.g. a sandboxed cloud agent) where an MCP connector can reach "
        "Alpha Vantage but this process can't reach the open internet.",
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="premarket-analog",
        description="Backtest a premarket gap-up analog pattern against price history, "
        "or screen candidates against it live.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    backtest = subparsers.add_parser(
        "backtest",
        help="Backtest the pattern against full historical price data (occurrence stats, forward returns).",
    )
    backtest.add_argument(
        "ticker",
        nargs="?",
        help=(
            "Primary ticker to analyze. If omitted, tickers are read from stdin "
            "(newline- or comma-separated) — e.g. piped in from a screener."
        ),
    )
    backtest.add_argument(
        "--peers",
        help="Comma-separated peer tickers to run the same scan against, for comparison.",
    )
    _add_pattern_args(backtest)
    backtest.add_argument(
        "--horizons", default="1,5,20", help="Comma-separated forward-return horizons in trading days (default 1,5,20)."
    )
    backtest.add_argument(
        "--min-occurrences",
        type=int,
        default=10,
        help="Occurrence count below which a horizon's stats are flagged as statistically thin (default 10).",
    )
    _add_data_source_args(backtest)
    _add_output_args(backtest)

    screen = subparsers.add_parser(
        "screen",
        help="Check whether candidate tickers currently match the pattern live (gap %% + prior-day RSI), "
        "ahead of today's close.",
    )
    screen.add_argument(
        "tickers",
        nargs="*",
        help="Candidate tickers to check. If omitted, read from stdin (newline- or comma-separated).",
    )
    _add_pattern_args(screen)
    _add_data_source_args(screen)
    screen.add_argument(
        "--quotes-file",
        help="Path to a JSON manifest of pre-fetched live quotes: "
        '{"TICKER": {"price": ..., "previous_close": ...}, ...}. When set, live quotes '
        "are loaded from this file instead of yfinance -- for environments where this "
        "process can't reach yfinance directly (pair with --data-dir).",
    )
    _add_output_args(screen)

    return parser


def _analyze_ticker(
    ticker: str,
    role: str,
    pattern: PatternConfig,
    horizons: tuple[int, ...],
    min_occurrences: int,
    api_key: str | None,
    data_dir: str | None = None,
) -> dict[str, Any]:
    try:
        history = get_price_history(ticker, api_key=api_key, data_dir=data_dir)
    except DataUnavailable as exc:
        return {"ticker": ticker, "role": role, "error": str(exc)}

    df = history.df
    # Only RSI/volume need enough bars to be meaningful; sma50/sma200 are
    # informational columns that are simply NaN until enough history accumulates,
    # so they shouldn't gate whether a scan can run at all (e.g. a --data-dir file
    # with only ~100 days, which is all Alpha Vantage's free "compact" tier gives).
    min_bars_needed = max(pattern.rsi_period, pattern.volume_window) + 2
    if len(df) < min_bars_needed:
        return {
            "ticker": ticker,
            "role": role,
            "error": f"only {len(df)} bars of history available, need at least {min_bars_needed}",
        }

    enriched = compute_indicators(df, pattern)
    matches = scan(enriched, pattern)
    returns_by_horizon, excluded_by_horizon = forward_returns(enriched, matches, horizons)

    horizon_stats = {h: summarize_horizon(returns_by_horizon[h]) for h in horizons}

    warnings: list[str] = []
    for h in horizons:
        stats = horizon_stats[h]
        if stats["count"] < min_occurrences:
            warnings.append(
                f"+{h}d horizon has only {stats['count']} resolved occurrence(s) "
                f"(< {min_occurrences}) — treat these stats as statistically thin, "
                "not a reliable edge."
            )
        if excluded_by_horizon[h] > 0:
            warnings.append(
                f"+{h}d horizon excluded {excluded_by_horizon[h]} match(es) too close to the "
                "end of available history to resolve."
            )
    warnings.append(
        "A pattern's historical performance reflects the regime it was observed in "
        "(e.g. 2021-2023) and is not guaranteed to hold in a different market regime."
    )

    return {
        "ticker": ticker,
        "role": role,
        "data_source": history.source,
        "date_range": {
            "start": df.index.min().strftime("%Y-%m-%d"),
            "end": df.index.max().strftime("%Y-%m-%d"),
            "trading_days": int(len(df)),
        },
        "match_count": int(len(matches)),
        "horizons": horizon_stats,
        "warnings": warnings,
    }


def _build_pattern(parser: argparse.ArgumentParser, args: argparse.Namespace) -> PatternConfig:
    try:
        return PatternConfig.from_overrides(
            config_path=args.pattern_config,
            gap_pct_min=args.gap_pct_min,
            rsi_min=args.rsi_min,
            rsi_max=args.rsi_max,
            volume_multiple=args.volume_multiple,
            volume_window=args.volume_window,
        )
    except (OSError, ValueError) as exc:
        parser.error(f"invalid --pattern-config: {exc}")
        raise SystemExit(2)  # parser.error() already exits; unreachable in practice


def _write_output(rendered: str, output_path: str | None) -> None:
    if output_path:
        with open(output_path, "w") as f:
            f.write(rendered)
            f.write("\n")
    else:
        print(rendered)


def _run_backtest(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    pattern = _build_pattern(parser, args)

    try:
        horizons = tuple(int(h.strip()) for h in args.horizons.split(",") if h.strip())
    except ValueError:
        parser.error(f"invalid --horizons value: {args.horizons!r}")
        return 2

    api_key = args.api_key or os.environ.get(API_KEY_ENV_VAR)

    jobs: list[tuple[str, str]] = []
    if args.ticker:
        jobs.append((args.ticker.upper(), "primary"))
        for peer in _parse_tickers(args.peers) if args.peers else []:
            jobs.append((peer, "peer"))
    else:
        if args.peers:
            print(
                "[premarket-analog] --peers is ignored when tickers are piped via stdin.",
                file=sys.stderr,
            )
        stdin_tickers = _read_stdin_tickers()
        if not stdin_tickers:
            parser.error(
                "no ticker given and none piped via stdin. Provide a ticker argument or "
                "pipe a newline/comma-separated list, e.g.: echo AAPL,MSFT | premarket-analog backtest"
            )
            return 2
        jobs = [(t, "batch") for t in stdin_tickers]

    results = [
        _analyze_ticker(ticker, role, pattern, horizons, args.min_occurrences, api_key, args.data_dir)
        for ticker, role in jobs
    ]

    report = build_report(pattern.to_dict(), horizons, args.min_occurrences, results)
    rendered = to_json(report) if args.format == "json" else to_markdown(report)
    _write_output(rendered, args.output)
    return 0


def _run_screen(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    pattern = _build_pattern(parser, args)
    api_key = args.api_key or os.environ.get(API_KEY_ENV_VAR)

    tickers = [t.upper() for t in args.tickers] if args.tickers else _read_stdin_tickers()
    if not tickers:
        parser.error(
            "no candidate tickers given and none piped via stdin. Provide tickers as "
            "arguments or pipe a newline/comma-separated list, e.g.: echo AAPL,MSFT | premarket-analog screen"
        )
        return 2

    results = screen_candidates(
        tickers, pattern, api_key=api_key, data_dir=args.data_dir, quotes_file=args.quotes_file
    )
    report = build_screen_report(pattern.to_dict(), results)
    rendered = to_json(report) if args.format == "json" else to_screen_markdown(report)
    _write_output(rendered, args.output)
    return 0


def _normalize_argv(argv: list[str]) -> list[str]:
    """Inserts the implicit default subcommand `backtest` when the caller didn't
    name one, e.g. `premarket-analog AAPL` still works without `backtest AAPL`."""
    if not argv or (argv[0] not in SUBCOMMANDS and argv[0] not in ("-h", "--help")):
        return ["backtest", *argv]
    return argv


def main(argv: list[str] | None = None) -> int:
    argv = _normalize_argv(sys.argv[1:] if argv is None else list(argv))

    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.command == "screen":
        return _run_screen(parser, args)
    return _run_backtest(parser, args)


if __name__ == "__main__":
    raise SystemExit(main())
