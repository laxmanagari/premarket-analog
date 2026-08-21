import json

import pytest

from premarket_analog.ratelimit import (
    _advance_window,
    reset_window,
    wait_for_slot,
    wait_for_slot_persisted,
)


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start
        self.slept: list[float] = []

    def now_fn(self) -> float:
        return self.now

    def sleep_fn(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_advance_window_no_sleep_when_under_limit():
    clock = FakeClock(1000.0)
    timestamps = [1000.0, 1001.0, 1002.0, 1003.0]  # 4 calls, limit is 5
    new_timestamps, slept = _advance_window(
        timestamps, max_calls=5, window_seconds=60.0, sleep_fn=clock.sleep_fn, now_fn=clock.now_fn
    )
    assert slept == 0.0
    assert len(new_timestamps) == 5
    assert clock.slept == []


def test_advance_window_sleeps_until_oldest_ages_out_when_at_limit():
    clock = FakeClock(1000.0)
    timestamps = [1000.0, 1001.0, 1002.0, 1003.0, 1004.0]  # 5 calls, at the limit
    new_timestamps, slept = _advance_window(
        timestamps, max_calls=5, window_seconds=60.0, sleep_fn=clock.sleep_fn, now_fn=clock.now_fn
    )
    # oldest (1000.0) + 60s window = 1060.0; now was 1000.0, so it must sleep 60s
    assert slept == pytest.approx(60.0)
    assert clock.slept == [60.0]
    # after sleeping, the oldest timestamp (1000.0) ages out (not > cutoff of 1000.0)
    assert 1000.0 not in new_timestamps
    assert new_timestamps[-1] == pytest.approx(1060.0)


def test_advance_window_prunes_timestamps_outside_window():
    clock = FakeClock(1100.0)
    # first two timestamps are more than 60s old and should be pruned before counting
    timestamps = [1000.0, 1010.0, 1080.0, 1090.0]
    new_timestamps, slept = _advance_window(
        timestamps, max_calls=5, window_seconds=60.0, sleep_fn=clock.sleep_fn, now_fn=clock.now_fn
    )
    assert slept == 0.0
    assert 1000.0 not in new_timestamps
    assert 1010.0 not in new_timestamps
    assert 1080.0 in new_timestamps


def test_wait_for_slot_module_state_and_reset():
    reset_window()
    clock = FakeClock(2000.0)
    for _ in range(5):
        slept = wait_for_slot(max_calls=5, window_seconds=60.0, sleep_fn=clock.sleep_fn, now_fn=clock.now_fn)
        assert slept == 0.0
        clock.now += 0.5

    slept = wait_for_slot(max_calls=5, window_seconds=60.0, sleep_fn=clock.sleep_fn, now_fn=clock.now_fn)
    assert slept > 0.0

    reset_window()
    slept = wait_for_slot(max_calls=5, window_seconds=60.0, sleep_fn=clock.sleep_fn, now_fn=clock.now_fn)
    assert slept == 0.0
    reset_window()


def test_wait_for_slot_persisted_writes_and_reads_state_file(tmp_path):
    state_path = tmp_path / "calls.json"
    clock = FakeClock(5000.0)

    for i in range(5):
        slept = wait_for_slot_persisted(
            state_path, max_calls=5, window_seconds=60.0, sleep_fn=clock.sleep_fn, now_fn=clock.now_fn
        )
        assert slept == 0.0
        clock.now += 1.0

    stored = json.loads(state_path.read_text())
    assert len(stored) == 5

    # a 6th call now must block since the window is full
    slept = wait_for_slot_persisted(
        state_path, max_calls=5, window_seconds=60.0, sleep_fn=clock.sleep_fn, now_fn=clock.now_fn
    )
    assert slept > 0.0


def test_wait_for_slot_persisted_handles_missing_or_corrupt_file(tmp_path):
    state_path = tmp_path / "missing.json"
    clock = FakeClock(9000.0)
    slept = wait_for_slot_persisted(
        state_path, max_calls=5, window_seconds=60.0, sleep_fn=clock.sleep_fn, now_fn=clock.now_fn
    )
    assert slept == 0.0
    assert state_path.exists()

    state_path.write_text("not valid json")
    slept = wait_for_slot_persisted(
        state_path, max_calls=5, window_seconds=60.0, sleep_fn=clock.sleep_fn, now_fn=clock.now_fn
    )
    assert slept == 0.0
