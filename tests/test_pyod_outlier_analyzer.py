from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
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
    assert signal.evidence["implementation"]["library"] == "pyod"
    assert signal.evidence["implementation"]["detector"] == "KNN"
    assert signal.evidence["implementation"]["detector_type"] == "knn"
    assert signal.evidence["contamination"] == 0.05
    assert signal.evidence["max_anomaly_score"] > 0
    assert signal.evidence["point_count"] >= 1
    assert signal.evidence["outlier_indices"]
    assert signal.evidence["outlier_timestamps"]
    assert signal.evidence["min_samples"] == 50
    assert signal.evidence["finding_rule"]["min_range_excess"] == 0.56
    assert signal.evidence["finding_rule_matched"] is True


def test_a_single_clear_spike_is_a_finding() -> None:
    # One point far outside the normal range: the case the old 8-points-per-group rule could never pass.
    values = [50.0 + (index % 5) for index in range(120)]
    values[20] = 180.0

    signals = PyODOutlierAnalyzer(contamination=0.01, min_samples=50, grouping_gap="5m").analyze(_frame(values))

    spike = next(signal for signal in signals if 20 in signal.evidence["outlier_indices"])
    assert spike.evidence["finding_rule_matched"] is True
    assert spike.evidence["range_excess"] > 20
    assert spike.confidence == 1.0


def test_the_top_one_percent_of_healthy_noise_is_not_a_finding() -> None:
    # KNN always marks its contamination share of points; on smooth noise those sit at the edge of
    # the normal range, not beyond it.
    rng = np.random.default_rng(7)
    values = list(50.0 + rng.normal(0, 1, 300))

    signals = PyODOutlierAnalyzer(contamination=0.01, min_samples=50, grouping_gap="5m").analyze(_frame(values))

    assert signals, "KNN marks outliers even on healthy data"
    assert all(signal.evidence["finding_rule_matched"] is False for signal in signals)
    assert all(signal.confidence < 0.5 for signal in signals)


def test_confidence_is_absolute_and_crosses_one_half_at_the_rule() -> None:
    analyzer = PyODOutlierAnalyzer()

    assert analyzer._confidence(0.0) == 0.0
    assert analyzer._confidence(0.28) == 0.25
    assert analyzer._confidence(0.56) == 0.5
    assert analyzer._confidence(0.78) == 0.75
    assert analyzer._confidence(1.0) == 1.0
    assert analyzer._confidence(29.0) == 1.0


def test_pyod_outlier_analyzer_skips_short_dataset() -> None:
    signals = PyODOutlierAnalyzer(min_samples=50).analyze(_frame([1.0, 2.0, 100.0]))

    assert signals == []
