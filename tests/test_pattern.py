import json

import numpy as np
import pandas as pd
import pytest

from premarket_analog.pattern import (
    PatternConfig,
    compute_indicators,
    forward_returns,
    scan,
    summarize_horizon,
)


def _dates(n, start="2024-01-02"):
    return pd.bdate_range(start=start, periods=n)


def test_scan_requires_all_three_conditions():
    idx = _dates(5)
    df = pd.DataFrame(
        {
            "gap_pct": [2.5, 1.0, 3.0, 5.0, 2.1],
            "rsi_prior": [60, 60, 40, 65, 60],  # row 2 fails RSI band
            "volume_ratio": [2.0, 2.0, 2.0, 1.0, 1.6],  # row 1 & 3 fail volume
        },
        index=idx,
    )
    pattern = PatternConfig(gap_pct_min=2.0, rsi_range=(50, 70), volume_multiple=1.5)
    matches = scan(df, pattern)
    # Only row 0 and row 4 satisfy gap>=2, rsi in [50,70], volume_ratio>=1.5
    assert list(matches.index) == [idx[0], idx[4]]


def test_compute_indicators_gap_pct_and_prior_shift():
    idx = _dates(4)
    df = pd.DataFrame(
        {
            "open": [100.0, 102.0, 95.0, 110.0],
            "high": [101.0, 103.0, 96.0, 111.0],
            "low": [99.0, 101.0, 94.0, 109.0],
            "close": [100.0, 100.0, 100.0, 100.0],
            "volume": [1000, 1000, 1000, 1000],
        },
        index=idx,
    )
    pattern = PatternConfig()
    out = compute_indicators(df, pattern)
    # gap_pct for row i = (open_i - close_{i-1}) / close_{i-1} * 100
    assert out["gap_pct"].iloc[0] != out["gap_pct"].iloc[0]  # NaN, no prior close
    assert out["gap_pct"].iloc[1] == pytest.approx(2.0)  # (102-100)/100*100
    assert out["gap_pct"].iloc[2] == pytest.approx(-5.0)  # (95-100)/100*100
    # rsi_prior at row i must equal rsi at row i-1 (shifted by one); both are
    # NaN this early (RSI needs `rsi_period` bars of warmup), so compare with
    # equals_nan rather than `==` (NaN != NaN).
    assert np.array_equal(out["rsi_prior"].iloc[1], out["rsi"].iloc[0], equal_nan=True)


def test_forward_returns_computes_correct_pct_and_excludes_unresolvable():
    idx = _dates(6)
    df = pd.DataFrame({"close": [100.0, 110.0, 121.0, 90.0, 95.0, 100.0]}, index=idx)
    # Match on day 0 (index position 0) and day 4 (position 4, too close to end for +5)
    matches = df.loc[[idx[0], idx[4]]]

    returns, excluded = forward_returns(df, matches, horizons=(1, 5))

    # Day 0 +1 -> close[1]=110 vs close[0]=100 -> +10%
    day0_plus1 = next(r for r in returns[1] if r["date"] == idx[0].strftime("%Y-%m-%d"))
    assert day0_plus1["return_pct"] == pytest.approx(10.0)

    # Day 0 +5 -> close[5]=100 vs close[0]=100 -> 0%
    day0_plus5 = next(r for r in returns[5] if r["date"] == idx[0].strftime("%Y-%m-%d"))
    assert day0_plus5["return_pct"] == pytest.approx(0.0)

    # Day 4 +5 goes past the end of history (position 9 doesn't exist) -> excluded
    assert excluded[5] == 1
    assert not any(r["date"] == idx[4].strftime("%Y-%m-%d") for r in returns[5])
    # Day 4 +1 -> position 5 exists -> resolved, close[5]=100 vs close[4]=95 -> ~+5.26%
    day4_plus1 = next(r for r in returns[1] if r["date"] == idx[4].strftime("%Y-%m-%d"))
    assert day4_plus1["return_pct"] == pytest.approx(5.263157894736842)


def test_summarize_horizon_stats():
    returns = [{"date": "d", "return_pct": v} for v in [-2.0, -1.0, 0.0, 1.0, 3.0]]
    stats = summarize_horizon(returns)
    assert stats["count"] == 5
    assert stats["win_rate_pct"] == pytest.approx(40.0)  # 2 of 5 are > 0
    assert stats["avg_return_pct"] == pytest.approx(0.2)
    assert stats["median_return_pct"] == pytest.approx(0.0)
    assert stats["distribution"]["min_pct"] == pytest.approx(-2.0)
    assert stats["distribution"]["max_pct"] == pytest.approx(3.0)


def test_summarize_horizon_empty():
    stats = summarize_horizon([])
    assert stats["count"] == 0
    assert stats["win_rate_pct"] is None
    assert stats["distribution"] is None


def test_pattern_config_layering(tmp_path):
    config_file = tmp_path / "pattern.json"
    config_file.write_text(json.dumps({"gap_pct_min": 3.0, "rsi_range": [40, 60]}))

    # File overrides defaults, CLI overrides file.
    pattern = PatternConfig.from_overrides(
        config_path=str(config_file),
        gap_pct_min=None,
        rsi_min=45,  # CLI wins over the file's 40
        rsi_max=None,  # file's 60 stands
        volume_multiple=None,
        volume_window=None,
    )
    assert pattern.gap_pct_min == 3.0  # from file
    assert pattern.rsi_range == (45, 60)  # min from CLI, max from file
    assert pattern.volume_multiple == PatternConfig.default().volume_multiple
