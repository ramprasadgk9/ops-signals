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
