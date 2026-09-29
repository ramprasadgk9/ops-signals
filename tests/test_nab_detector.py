from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import pandas as pd

from benchmark.nab import detector


def _write_series(path: Path, spike_row: int, rows: int = 900) -> None:
    rng = np.random.default_rng(7)
    values = 50 + rng.normal(0, 1, rows)
    values[spike_row : spike_row + 3] += 40
    timestamps = pd.date_range("2014-04-10", periods=rows, freq="5min")
    pd.DataFrame({"timestamp": timestamps.strftime("%Y-%m-%d %H:%M:%S"), "value": values}).to_csv(path, index=False)


def test_replay_never_alarms_before_the_event_and_catches_a_clear_spike(tmp_path: Path) -> None:
    spike_row = 700
    path = tmp_path / "spike.csv"
    _write_series(path, spike_row)

    run = detector.run_series(path, "synthetic/spike.csv")

    assert run.batch_error is None
    assert run.replay_errors == 0
    assert run.interval_minutes == 5
    replay = np.asarray(run.replay_scores)
    alarms = np.nonzero(replay >= 0.5)[0]
    assert alarms.size, "a +40 spike on unit noise should raise a confident alarm"
    # Causal: every confident alarm lands at or after the spike, and within one replay step of it.
    first = int(alarms[alarms >= spike_row - 1][0])
    assert spike_row <= first <= spike_row + detector.REPLAY_STEP + 2
    assert not (alarms < spike_row - detector.REPLAY_STEP).any()


def test_batch_alarm_lands_on_the_detected_events_own_row(tmp_path: Path) -> None:
    spike_row = 700
    path = tmp_path / "spike.csv"
    _write_series(path, spike_row)

    run = detector.run_series(path, "synthetic/spike.csv")

    batch = np.asarray(run.batch_scores)
    assert batch[spike_row : spike_row + 3].max() >= 0.5


def test_static_threshold_alarms_once_per_excursion_after_the_probationary_period() -> None:
    values = np.full(1000, 50.0)
    values[10] = 90.0  # inside the probationary period: sets the learned range, never alarms
    values[500:505] = 95.0  # one excursion above the learned max
    values[800] = 10.0  # one excursion below the learned min

    scores = detector.static_threshold_scores(values)

    assert np.flatnonzero(scores).tolist() == [500, 800]


def test_every_series_run_reports_each_baseline_with_its_cost(tmp_path: Path) -> None:
    path = tmp_path / "spike.csv"
    _write_series(path, 700)

    run = detector.run_series(path, "synthetic/spike.csv")

    assert set(run.baselines) == set(detector.BASELINES)
    for method, method_run in run.baselines.items():
        assert len(method_run.scores) == run.rows
        assert method_run.errors == 0, method
    assert run.baselines["zscore_only"].analyzer_runs == run.baselines["zscore_only"].runs
    assert run.baselines["all_analyzers"].analyzer_runs > run.replay_analyzer_runs
    assert run.baselines["static_threshold"].analyzer_runs == 0
