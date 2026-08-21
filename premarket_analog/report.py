"""Renders scan results into Markdown or JSON reports."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .screener import VOLUME_UNAVAILABLE_NOTE


def build_report(
    pattern_dict: dict[str, Any],
    horizons: tuple[int, ...],
    min_occurrences: int,
    ticker_results: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pattern": pattern_dict,
        "horizons": list(horizons),
        "min_occurrences_for_significance": min_occurrences,
        "results": ticker_results,
    }


def _fmt_pct(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.{decimals}f}%"


def to_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Premarket Analog Scan Report")
    lines.append("")
    lines.append(f"Generated: {report['generated_at']}")
    lines.append("")

    p = report["pattern"]
    lo, hi = p["rsi_range"]
    lines.append("## Pattern Definition")
    lines.append("")
    lines.append(f"- Gap up ≥ **{p['gap_pct_min']}%** (day's open vs. prior close)")
    lines.append(f"- Prior-day RSI({p['rsi_period']}) in **[{lo}, {hi}]**")
    lines.append(
        f"- Day's volume ≥ **{p['volume_multiple']}×** its trailing "
        f"{p['volume_window']}-day average"
    )
    lines.append(
        f"- Forward horizons: {', '.join(str(h) + 'd' for h in report['horizons'])} "
        "trading days, measured close-to-close from the signal day"
    )
    lines.append("")

    for entry in report["results"]:
        lines.extend(_render_ticker_section(entry, report["min_occurrences_for_significance"]))

    if len(report["results"]) > 1:
        lines.extend(_render_comparison_table(report["results"], report["horizons"]))

    return "\n".join(lines)


def _render_ticker_section(entry: dict[str, Any], min_occurrences: int) -> list[str]:
    lines: list[str] = []
    role_label = {"primary": "primary", "peer": "peer", "batch": ""}.get(entry["role"], "")
    header = f"## {entry['ticker']}" + (f" ({role_label})" if role_label else "")
    lines.append(header)
    lines.append("")

    if entry.get("error"):
        lines.append(f"**Error:** {entry['error']}")
        lines.append("")
        return lines

    dr = entry["date_range"]
    lines.append(
        f"- Data source: `{entry['data_source']}` | History covered: "
        f"**{dr['start']} → {dr['end']}** ({dr['trading_days']} trading days)"
    )
    lines.append(f"- Pattern matches found: **{entry['match_count']}**")
    lines.append("")

    lines.append("| Horizon | Count | Win Rate | Avg Return | Median Return | P25 | P75 | Std Dev |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for h, stats in entry["horizons"].items():
        if stats["count"] == 0:
            lines.append(f"| +{h}d | 0 | n/a | n/a | n/a | n/a | n/a | n/a |")
            continue
        d = stats["distribution"]
        lines.append(
            f"| +{h}d | {stats['count']} | {stats['win_rate_pct']:.1f}% | "
            f"{_fmt_pct(stats['avg_return_pct'])} | {_fmt_pct(stats['median_return_pct'])} | "
            f"{_fmt_pct(d['p25_pct'])} | {_fmt_pct(d['p75_pct'])} | {d['std_dev_pct']:.2f}pp |"
        )
    lines.append("")

    if entry["warnings"]:
        for w in entry["warnings"]:
            lines.append(f"> ⚠️ {w}")
        lines.append("")

    return lines


def _render_comparison_table(results: list[dict[str, Any]], horizons: list[int]) -> list[str]:
    lines = ["## Comparison Across Tickers", ""]
    for h in horizons:
        lines.append(f"### +{h}d")
        lines.append("")
        lines.append("| Ticker | Count | Win Rate | Avg Return | Median Return |")
        lines.append("|---|---|---|---|---|")
        for entry in results:
            if entry.get("error"):
                lines.append(f"| {entry['ticker']} | — | — | — | — |")
                continue
            stats = entry["horizons"].get(h) or entry["horizons"].get(str(h))
            if not stats or stats["count"] == 0:
                lines.append(f"| {entry['ticker']} | 0 | n/a | n/a | n/a |")
                continue
            lines.append(
                f"| {entry['ticker']} | {stats['count']} | {stats['win_rate_pct']:.1f}% | "
                f"{_fmt_pct(stats['avg_return_pct'])} | {_fmt_pct(stats['median_return_pct'])} |"
            )
        lines.append("")
    return lines


def to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, default=str)


def build_screen_report(pattern_dict: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pattern": pattern_dict,
        "results": results,
        "matched_tickers": [r["ticker"] for r in results if r.get("matched")],
    }


def to_screen_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Live Premarket Screen")
    lines.append("")
    lines.append(f"Generated: {report['generated_at']}")
    lines.append("")

    p = report["pattern"]
    lo, hi = p["rsi_range"]
    lines.append("## Pattern Checked")
    lines.append("")
    lines.append(f"- Gap up ≥ **{p['gap_pct_min']}%** (current price vs. prior close)")
    lines.append(f"- Prior-day RSI({p['rsi_period']}) in **[{lo}, {hi}]**")
    lines.append("")

    lines.append("| Ticker | Prior Close | Current | Gap % | Prior RSI | Match |")
    lines.append("|---|---|---|---|---|---|")
    for r in report["results"]:
        if r.get("error"):
            lines.append(f"| {r['ticker']} | — | — | — | — | error: {r['error']} |")
            continue
        rsi_str = f"{r['prior_rsi']:.1f}" if r["prior_rsi"] is not None else "n/a"
        match_str = "✅" if r["matched"] else ""
        lines.append(
            f"| {r['ticker']} | {r['previous_close']:.2f} | {r['current_price']:.2f} | "
            f"{r['gap_pct']:+.2f}% | {rsi_str} | {match_str} |"
        )
    lines.append("")

    matched = report["matched_tickers"]
    if matched:
        lines.append(f"**Live matches:** {', '.join(matched)}")
    else:
        lines.append("**Live matches:** none of the candidates currently match the pattern.")
    lines.append("")
    lines.append(f"> ⚠️ {VOLUME_UNAVAILABLE_NOTE}")

    return "\n".join(lines)
