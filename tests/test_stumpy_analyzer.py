from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from intelligence.analyzers.stumpy import STUMPYAnalyzer


def test_stumpy_analyzer_uses_real_stumpy_library_when_installed() -> None:
    values = [1.0, 2.0, 3.0, 1.0, 2.0, 3.0, 5.0, 6.0, 1.0, 2.0, 3.0, 7.0]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    dataframe = pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=index) for index in range(len(values))],
            "value": values,
            "metric_name": ["cpu_usage"] * len(values),
            "service": ["checkout"] * len(values),
            "env": ["prod"] * len(values),
        }
    )

    signals = STUMPYAnalyzer(window_size=3, profile_threshold=10.0).analyze(dataframe)

    assert len(signals) == 1
    assert signals[0].evidence["library"] == "stumpy"
    assert signals[0].evidence["algorithm"] == "stump"
    assert signals[0].evidence["implementation"]["library"] == "stumpy"
    assert signals[0].evidence["implementation"]["algorithm"] == "stump"
    assert signals[0].evidence["implementation"]["window_size"] == 4
    assert signals[0].confidence >= 0.75
    assert signals[0].evidence["finding_rules"]["max_motif_distance"] == 1.0
    assert signals[0].evidence["finding_rule_matched"] is True


def test_stumpy_analyzer_marks_finding_rule_as_unmatched_for_weak_motif() -> None:
    values = [1.0, 2.0, 3.0, 1.4, 2.4, 3.4, 5.0, 6.0, 1.8, 2.8, 3.8, 7.0]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    dataframe = pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=index) for index in range(len(values))],
            "value": values,
            "metric_name": ["cpu_usage"] * len(values),
            "service": ["checkout"] * len(values),
            "env": ["prod"] * len(values),
        }
    )

    signals = STUMPYAnalyzer(
        window_size=3,
        profile_threshold=10.0,
        finding_rules={"max_motif_distance": 0.01, "min_confidence": 0.99},
    ).analyze(dataframe)

    assert signals
    assert signals[0].evidence["finding_rule_matched"] is False
