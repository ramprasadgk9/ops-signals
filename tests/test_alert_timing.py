from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.app.alerts.timing import ALERT_TIME, SPIKE, STEP_CHANGE, TREND, choose_start_time

ALERT = datetime(2026, 9, 23, 14, 0, tzinfo=timezone.utc)
WINDOW_START = ALERT - timedelta(hours=6)


def step(analyzer: str, at: datetime) -> SimpleNamespace:
    return SimpleNamespace(analyzer_id=analyzer, signal_type=analyzer, start_time=WINDOW_START, evidence={"change_point_time": at.isoformat()})


def spike(at: datetime, analyzer: str = "anomaly_zscore") -> SimpleNamespace:
    return SimpleNamespace(analyzer_id=analyzer, signal_type="anomaly", start_time=at, evidence={})


def trend(slope: float = 0.4) -> SimpleNamespace:
    # A trend spans the whole window: its start_time is the window start, not when anything began.
    return SimpleNamespace(analyzer_id="trend", signal_type="trend", start_time=WINDOW_START, evidence={"slope": slope})


def choose(signals, step_lookback: timedelta | None = None, spike_lookback: timedelta = timedelta(hours=1)):
    return choose_start_time(signals, ALERT, step_lookback=step_lookback, spike_lookback=spike_lookback, after=timedelta(minutes=5))


def test_slow_rise_alone_has_no_start_time() -> None:
    start = choose([trend()])
    assert (start.basis, start.time, start.trend_direction) == (TREND, None, "upward")


def test_spike_on_a_slow_rise_is_timed_by_the_spike_and_keeps_the_trend_as_context() -> None:
    start = choose([trend(), spike(ALERT - timedelta(minutes=2))])
    assert (start.basis, start.time, start.analyzer_id, start.trend_direction) == (
        SPIKE, ALERT - timedelta(minutes=2), "anomaly_zscore", "upward",
    )


def test_step_change_wins_over_a_later_spike() -> None:
    start = choose([spike(ALERT - timedelta(minutes=2)), step("ruptures", ALERT - timedelta(minutes=20))])
    assert (start.basis, start.time) == (STEP_CHANGE, ALERT - timedelta(minutes=20))


def test_baseline_shift_is_preferred_over_ruptures() -> None:
    start = choose([step("ruptures", ALERT - timedelta(minutes=10)), step("baseline_shift", ALERT - timedelta(minutes=12))])
    assert (start.analyzer_id, start.time) == ("baseline_shift", ALERT - timedelta(minutes=12))


def test_step_change_anywhere_in_the_window_counts_by_default() -> None:
    start = choose([step("baseline_shift", ALERT - timedelta(hours=3))])
    assert (start.basis, start.time) == (STEP_CHANGE, ALERT - timedelta(hours=3))


def test_step_lookback_drops_older_step_changes() -> None:
    start = choose([step("baseline_shift", ALERT - timedelta(hours=3)), trend()], step_lookback=timedelta(hours=1))
    assert start.basis == TREND


def test_spike_older_than_the_spike_lookback_is_over() -> None:
    start = choose([spike(ALERT - timedelta(hours=5)), trend()])
    assert start.basis == TREND
    assert choose([spike(ALERT - timedelta(hours=5))], spike_lookback=timedelta(hours=6)).basis == SPIKE


def test_latest_spike_before_the_alert_is_chosen() -> None:
    start = choose([spike(ALERT - timedelta(minutes=40)), spike(ALERT - timedelta(minutes=3), "pyod_outlier")])
    assert (start.time, start.analyzer_id) == (ALERT - timedelta(minutes=3), "pyod_outlier")


def test_moments_well_after_the_alert_fired_are_ignored() -> None:
    assert choose([step("baseline_shift", ALERT + timedelta(minutes=30))]).basis == ALERT_TIME
    assert choose([spike(ALERT + timedelta(minutes=4))]).basis == SPIKE  # within the 5 min "after" window


def test_nothing_usable_falls_back_to_alert_time() -> None:
    assert choose([]).basis == ALERT_TIME
    no_change_point = SimpleNamespace(analyzer_id="baseline_shift", signal_type="baseline_shift", start_time=WINDOW_START, evidence={})
    assert choose([no_change_point]).basis == ALERT_TIME


def test_downward_trend_and_stored_signal_rows_are_understood() -> None:
    stored = SimpleNamespace(analyzer_id="trend", signal_type="trend", start_time=WINDOW_START, evidence=None, evidence_json={"slope": -2.0})
    assert choose([stored]).trend_direction == "downward"


def _series(level_at) -> list[tuple[datetime, float]]:
    return [(WINDOW_START + timedelta(minutes=m), level_at(m)) for m in range(0, 361)]


CHANGE_MIN = 300  # 13:00, an hour before the alert


def test_change_point_where_the_metric_stays_shifted_is_a_step() -> None:
    series = _series(lambda m: 100.0 if m < CHANGE_MIN else 300.0)
    start = choose_start_time([step("ruptures", WINDOW_START + timedelta(minutes=CHANGE_MIN))], ALERT, step_lookback=None,
                              spike_lookback=timedelta(hours=2), after=timedelta(minutes=5), series=series)
    assert start.basis == STEP_CHANGE


def test_change_point_on_a_spike_that_ended_is_a_spike() -> None:
    # Change-point analyzers also mark a short spike; the level after it is back to normal.
    series = _series(lambda m: 900.0 if CHANGE_MIN <= m < CHANGE_MIN + 2 else 100.0 + m * 0.1)
    at = WINDOW_START + timedelta(minutes=CHANGE_MIN)
    start = choose_start_time([step("ruptures", at), trend()], ALERT, step_lookback=None,
                              spike_lookback=timedelta(hours=2), after=timedelta(minutes=5), series=series)
    assert (start.basis, start.time, start.analyzer_id, start.trend_direction) == (SPIKE, at, "ruptures", "upward")


def test_ended_spike_older_than_the_spike_lookback_is_dropped() -> None:
    series = _series(lambda m: 900.0 if CHANGE_MIN <= m < CHANGE_MIN + 2 else 100.0)
    start = choose_start_time([step("ruptures", WINDOW_START + timedelta(minutes=CHANGE_MIN))], ALERT, step_lookback=None,
                              spike_lookback=timedelta(minutes=30), after=timedelta(minutes=5), series=series)
    assert start.basis == ALERT_TIME
