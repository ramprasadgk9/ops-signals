from __future__ import annotations

from pathlib import Path

import numpy as np

from benchmark.smd import data, metrics
from benchmark.smd.data import Incident


def _write_machine(root: Path, name: str, train: np.ndarray, test: np.ndarray, labels: list[int], interpretation: str) -> None:
    for part, values in (("train", train), ("test", test)):
        (root / part).mkdir(parents=True, exist_ok=True)
        np.savetxt(root / part / f"{name}.txt", values, delimiter=",", fmt="%.6f")
    (root / "test_label").mkdir(exist_ok=True)
    (root / "test_label" / f"{name}.txt").write_text("\n".join(str(v) for v in labels) + "\n", encoding="utf-8")
    (root / "interpretation_label").mkdir(exist_ok=True)
    (root / "interpretation_label" / f"{name}.txt").write_text(interpretation, encoding="utf-8")


def test_label_runs_are_zero_based_and_inclusive() -> None:
    assert data.label_runs(np.array([0, 1, 1, 0, 0, 1, 0, 1])) == [(1, 2), (5, 5), (7, 7)]


def test_incidents_take_the_metrics_of_every_overlapping_interpretation_range(tmp_path: Path) -> None:
    zeros = np.zeros((20, data.METRIC_COUNT))
    labels = [0] * 5 + [1] * 5 + [0] * 10
    # The published files often end one row past the labeled run; a second, overlapping range adds metrics.
    _write_machine(tmp_path, "machine-9-9", zeros, zeros, labels, "5-10:1,9\n7-8:12\n")

    machine = data.load_machine(tmp_path, "machine-9-9")

    assert [(i.start, i.end, i.metrics) for i in machine.incidents] == [(5, 9, [1, 9, 12])]
    assert machine.label_discrepancy  # two ranges for one labeled incident


def test_alarms_across_metrics_within_fifteen_minutes_are_one_alert() -> None:
    alarms = [[100, 3, 0.9, "a"], [110, 7, 0.6, "b"], [124, 3, 0.7, "a"], [140, 1, 0.8, "c"], [141, 2, 0.2, "c"]]

    alerts = metrics.group_alerts(alarms, threshold=0.5)

    assert [(a.start, a.end, a.metrics) for a in alerts] == [(100, 124, [3, 7]), (140, 140, [1])]


def test_an_incident_is_caught_by_an_alert_starting_inside_it_and_others_are_false() -> None:
    incidents = [Incident(100, 150, [3, 7]), Incident(500, 520, [1])]
    alarms = [[110, 3, 0.9, "a"], [112, 7, 0.8, "b"], [113, 9, 0.6, "b"], [300, 4, 0.9, "a"]]

    counts = metrics.score_machine(alarms, incidents, test_rows=1440, threshold=0.5)
    summary = counts.summary()

    assert (summary["caught"], summary["alerts"], summary["false_alerts"]) == (1, 2, 1)
    assert summary["median_delay_minutes"] == 10
    # Listed metrics 3 and 7 are the top two of the three that alarmed inside the incident.
    assert summary["hit_rate"]["100"] == 1.0
    assert abs(summary["localization_precision"] - 2 / 3) < 1e-9
    assert summary["false_alerts_per_machine_day"] == 1.0


def test_metrics_are_ranked_by_confidence_inside_the_incident() -> None:
    incident = Incident(10, 20, [])
    alarms = [[12, 5, 0.6, "a"], [15, 2, 0.9, "a"], [11, 8, 0.9, "b"], [30, 1, 1.0, "a"]]

    assert metrics.rank_metrics(alarms, incident, threshold=0.5) == [8, 2, 5]
