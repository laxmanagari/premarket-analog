"""Sliding-window rate limiting for Alpha Vantage calls (real free-tier limit:
5 calls/minute, 25 calls/day). One core function (`_advance_window`) implements
the algorithm against a plain list of call timestamps; two thin wrappers reuse
it depending on where the caller lives:

- `wait_for_slot` -- in-process, module-level state, used automatically by
  every direct REST call this package makes (data.py, catalyst.py).
- `wait_for_slot_persisted` -- file-backed state, for the `rate-guard` CLI
  subcommand: a cloud-routine agent making Alpha Vantage calls itself via MCP
  tools (not through this package's Python) can shell out to it before each
  call so the *agent's* call sequence respects the same sliding window.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

DEFAULT_MAX_CALLS = 5
DEFAULT_WINDOW_SECONDS = 60.0


def _advance_window(
    timestamps: list[float],
    max_calls: int,
    window_seconds: float,
    sleep_fn=time.sleep,
    now_fn=time.time,
) -> tuple[list[float], float]:
    """Given the timestamps of recent calls, blocks (if needed) so that
    recording one more call now would not exceed `max_calls` within the
    trailing `window_seconds`, then returns the updated timestamp list (with
    the new call appended) and how long it slept."""
    now = now_fn()
    cutoff = now - window_seconds
    timestamps = [t for t in timestamps if t > cutoff]

    slept = 0.0
    if len(timestamps) >= max_calls:
        oldest = timestamps[0]
        wait = (oldest + window_seconds) - now
        if wait > 0:
            sleep_fn(wait)
            slept = wait
        now = now_fn()
        cutoff = now - window_seconds
        timestamps = [t for t in timestamps if t > cutoff]

    timestamps.append(now)
    return timestamps, slept


_window_state: list[float] = []


def wait_for_slot(
    max_calls: int = DEFAULT_MAX_CALLS,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
    sleep_fn=time.sleep,
    now_fn=time.time,
) -> float:
    """In-process sliding-window guard shared by every real Alpha Vantage
    REST call this package makes directly. Returns how long it slept."""
    global _window_state
    _window_state, slept = _advance_window(_window_state, max_calls, window_seconds, sleep_fn, now_fn)
    return slept


def reset_window() -> None:
    global _window_state
    _window_state = []


def wait_for_slot_persisted(
    state_path: str | Path,
    max_calls: int = DEFAULT_MAX_CALLS,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
    sleep_fn=time.sleep,
    now_fn=time.time,
) -> float:
    """File-backed sliding-window guard: reads recent call timestamps from
    `state_path`, blocks if needed, then writes the updated list back. Meant
    for a caller outside this process (e.g. a cloud-routine agent shelling
    out via the `rate-guard` CLI subcommand between its own MCP tool calls)."""
    path = Path(state_path)
    timestamps: list[float] = []
    if path.exists():
        try:
            timestamps = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            timestamps = []

    timestamps, slept = _advance_window(timestamps, max_calls, window_seconds, sleep_fn, now_fn)
    path.write_text(json.dumps(timestamps))
    return slept
