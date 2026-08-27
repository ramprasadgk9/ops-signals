from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from intelligence.analyzers.prophet import ProphetAnalyzer


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


def test_prophet_analyzer_emits_finding_rule_metadata() -> None:
    values = [50.0 + index * 0.2 for index in range(30)]
    values[-1] = 90.0

    signals = ProphetAnalyzer(
        horizon_points=3,
        uncertainty_threshold=0.15,
        finding_rules={"min_relative_error": 0.1},
    ).analyze(_frame(values))

    assert signals
    signal = signals[0]
    assert signal.analyzer_id == "prophet"
    assert signal.evidence["relative_error"] > 0.1
    assert signal.evidence["implementation"]["library"] in {"prophet", "fallback"}
    assert signal.evidence["implementation"]["horizon_points"] == 3
    assert signal.evidence["implementation"]["uncertainty_threshold"] == 0.15
    assert signal.evidence["finding_rules"]["min_relative_error"] == 0.1
    assert signal.evidence["finding_rule_matched"] is True


def test_prophet_analyzer_marks_finding_rule_unmatched_for_small_error() -> None:
    values = [50.0 + index * 0.2 for index in range(30)]

    signals = ProphetAnalyzer(
        horizon_points=3,
        uncertainty_threshold=0.15,
        finding_rules={"min_relative_error": 0.5},
    ).analyze(_frame(values))

    assert signals
    assert signals[0].evidence["finding_rule_matched"] is False
