from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from intelligence.analyzers.pyod_outlier import PyODOutlierAnalyzer


def _frame(values: list[float]) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=index) for index in range(len(values))],
            "value": values,
            "metric_name": ["cpu_usage"] * len(values),
            "service": ["checkout"] * len(values),
            "env": ["prod"] * len(values),
        }
    )


def test_pyod_outlier_analyzer_emits_anomaly_signal_for_outlier_series() -> None:
    values = [50.0 + (index % 5) for index in range(60)]
    values[20] = 180.0
    values[45] = 5.0

    signals = PyODOutlierAnalyzer(contamination=0.05, min_samples=50, grouping_gap="5m").analyze(_frame(values))

    assert signals
    signal = signals[0]
    assert signal.signal_type == "anomaly"
    assert signal.analyzer_id == "pyod_outlier"
    assert signal.evidence["library"] == "pyod"
    assert signal.evidence["detector"] == "KNN"
    assert signal.evidence["contamination"] == 0.05
    assert signal.evidence["max_anomaly_score"] > 0
    assert signal.evidence["point_count"] >= 1
    assert signal.evidence["min_samples"] == 50


def test_pyod_outlier_analyzer_skips_short_dataset() -> None:
    signals = PyODOutlierAnalyzer(min_samples=50).analyze(_frame([1.0, 2.0, 100.0]))

    assert signals == []
