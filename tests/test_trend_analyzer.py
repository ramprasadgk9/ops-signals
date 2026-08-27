from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from intelligence.analyzers.trend import TrendAnalyzer


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


def test_trend_analyzer_emits_finding_rule_metadata() -> None:
    values = [100.0 + index for index in range(30)]

    signals = TrendAnalyzer(
        min_slope_percent=10,
        finding_rules={"min_slope_percent": 20},
        implementation={"library": "statsmodels", "model": "OLS"},
    ).analyze(_frame(values))

    assert signals
    signal = signals[0]
    assert signal.signal_type == "trend"
    assert signal.evidence["slope_percent"] >= 20
    assert signal.evidence["finding_rules"]["min_slope_percent"] == 20
    assert signal.evidence["finding_rule_matched"] is True
    assert signal.evidence["implementation"] == {"library": "statsmodels", "model": "OLS"}


def test_trend_analyzer_suppresses_signals_below_finding_rule() -> None:
    values = [100.0 + index * 0.1 for index in range(30)]

    signals = TrendAnalyzer(
        min_slope_percent=1,
        finding_rules={"min_slope_percent": 10},
    ).analyze(_frame(values))

    assert signals == []
