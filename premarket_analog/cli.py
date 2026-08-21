"""premarket-analog: scan historical price action for a premarket-gap analog
pattern and report how it has historically resolved.

Usage:
    premarket-analog AAPL --peers MSFT,GOOGL,AMZN
    printf "AAPL\\nMSFT\\nGOOGL\\nAMZN\\nNVDA\\n" | premarket-analog --format json
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from .data import DataUnavailable, get_price_history
from .pattern import PatternConfig, compute_indicators, forward_returns, scan, summarize_horizon
from .report import build_report, to_json, to_markdown

API_KEY_ENV_VAR = "ALPHAVANTAGE_API_KEY"


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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="premarket-analog",
        description="Backtest a premarket gap-up analog pattern against price history.",
    )
    parser.add_argument(
        "ticker",
        nargs="?",
        help=(
            "Primary ticker to analyze. If omitted, tickers are read from stdin "
            "(newline- or comma-separated) — e.g. piped in from a screener."
        ),
    )
    parser.add_argument(
        "--peers",
        help="Comma-separated peer tickers to run the same scan against, for comparison.",
    )
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
    parser.add_argument(
        "--horizons", default="1,5,20", help="Comma-separated forward-return horizons in trading days (default 1,5,20)."
    )
    parser.add_argument(
        "--min-occurrences",
        type=int,
        default=10,
        help="Occurrence count below which a horizon's stats are flagged as statistically thin (default 10).",
    )
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", help="Write the report to this file instead of stdout.")
    parser.add_argument(
        "--api-key",
        help=f"Alpha Vantage API key. Defaults to the {API_KEY_ENV_VAR} env var; "
        "falls back to yfinance if unset or unavailable.",
    )
    return parser


def _analyze_ticker(
    ticker: str,
    role: str,
    pattern: PatternConfig,
    horizons: tuple[int, ...],
    min_occurrences: int,
    api_key: str | None,
) -> dict[str, Any]:
    try:
        history = get_price_history(ticker, api_key=api_key)
    except DataUnavailable as exc:
        return {"ticker": ticker, "role": role, "error": str(exc)}

    df = history.df
    min_bars_needed = max(pattern.sma_periods, default=0)
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


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        pattern = PatternConfig.from_overrides(
            config_path=args.pattern_config,
            gap_pct_min=args.gap_pct_min,
            rsi_min=args.rsi_min,
            rsi_max=args.rsi_max,
            volume_multiple=args.volume_multiple,
            volume_window=args.volume_window,
        )
    except (OSError, ValueError) as exc:
        parser.error(f"invalid --pattern-config: {exc}")
        return 2

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
                "pipe a newline/comma-separated list, e.g.: echo AAPL,MSFT | premarket-analog"
            )
            return 2
        jobs = [(t, "batch") for t in stdin_tickers]

    results = [
        _analyze_ticker(ticker, role, pattern, horizons, args.min_occurrences, api_key)
        for ticker, role in jobs
    ]

    report = build_report(pattern.to_dict(), horizons, args.min_occurrences, results)
    rendered = to_json(report) if args.format == "json" else to_markdown(report)

    if args.output:
        with open(args.output, "w") as f:
            f.write(rendered)
            f.write("\n")
    else:
        print(rendered)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
