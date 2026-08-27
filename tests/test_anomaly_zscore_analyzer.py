from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from intelligence.analyzers.anomaly_zscore import ZScoreAnomalyAnalyzer


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


def test_zscore_analyzer_emits_implementation_and_finding_rule_metadata() -> None:
    values = [50.0] * 40 + [120.0]

    signals = ZScoreAnomalyAnalyzer(
        implementation={"library": "pandas", "method": "zscore", "zscore_threshold": 3.0, "grouping_gap": "15m"},
        finding_rules={"min_abs_zscore": 3.0, "min_points": 1},
    ).analyze(_frame(values))

    assert signals
    signal = signals[0]
    assert signal.analyzer_id == "anomaly_zscore"
    assert signal.evidence["implementation"]["library"] == "pandas"
    assert signal.evidence["implementation"]["method"] == "zscore"
    assert signal.evidence["finding_rules"] == {"min_abs_zscore": 3.0, "min_points": 1}
    assert signal.evidence["finding_rule_matched"] is True


def test_zscore_analyzer_marks_finding_rule_unmatched_when_group_too_small() -> None:
    values = [50.0] * 40 + [120.0]

    signals = ZScoreAnomalyAnalyzer(
        zscore_threshold=3.0,
        grouping_gap="15m",
        finding_rules={"min_abs_zscore": 3.0, "min_points": 2},
    ).analyze(_frame(values))

    assert signals
    assert signals[0].evidence["finding_rule_matched"] is False
