from __future__ import annotations

import numpy as np

from benchmark.nab import metrics


def test_probation_follows_nabs_rule_of_15_percent_capped_at_750_rows() -> None:
    assert metrics.probation_rows(4032) == 604
    assert metrics.probation_rows(22695) == 750


def test_first_alarm_in_a_window_detects_it_and_later_ones_are_neither_rewarded_nor_penalized() -> None:
    scores = np.zeros(2000)
    scores[[1000, 1010, 1020]] = 0.9

    counts = metrics.score_series(list(scores), [(990, 1100)], threshold=0.5)

    assert counts.detected_windows == 1
    assert counts.alarms == 3
    assert counts.alarms_in_windows == 3
    assert counts.false_alarms == 0
    assert counts.detection_positions == ((1000 - 990) / 110,)


def test_alarms_outside_windows_are_false_and_probationary_alarms_are_ignored() -> None:
    scores = np.zeros(2000)
    scores[10] = 1.0  # probationary period (first 300 rows): ignored
    scores[500] = 1.0  # outside every window: false alarm
    scores[1500] = 0.3  # below threshold: not an alarm

    counts = metrics.score_series(list(scores), [(1400, 1600)], threshold=0.5)

    assert counts.alarms == 1
    assert counts.false_alarms == 1
    assert counts.detected_windows == 0
    summary = counts.summary()
    assert summary["window_recall"] == 0.0
    assert summary["alarm_precision"] == 0.0


def test_series_with_no_windows_and_no_alarms_has_undefined_rather_than_perfect_scores() -> None:
    summary = metrics.score_series([0.0] * 1000, [], threshold=0.5).summary()

    assert summary["window_recall"] is None
    assert summary["alarm_precision"] is None
    assert summary["f1"] is None


def test_window_timestamps_map_to_inclusive_row_ranges() -> None:
    timestamps = np.array(["2014-04-10T00:04", "2014-04-10T00:09", "2014-04-10T00:14", "2014-04-10T00:19"], dtype="datetime64[ns]")

    rows = metrics.window_rows(timestamps, [["2014-04-10 00:05:00.000000", "2014-04-10 00:14:00.000000"]])

    assert rows == [(1, 2)]
