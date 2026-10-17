"""QA-09: an infinite value was accepted, stored as Infinity and served back as null, and -inf was
reported as a "negative value"."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from intelligence.config import InputConfig
from intelligence.normalize.normalizer import VALIDATION_WARNINGS_ATTR, normalize_timeseries


def _config(source_type: str) -> InputConfig:
    return InputConfig(
        source_type=source_type,
        file_path="unused.csv",
        history="1d",
        interval="5m",
        timestamp_column="timestamp",
        value_column="value",
        metric_column="metric_name",
        required_columns=["timestamp", "metric_name", "value"],
        optional_columns=["service", "env", "host", "namespace", "pod", "source", "unit", "metric_type"],
        service="checkout",
        metric_name="cpu_usage",
        provider="generic",
        validation={"allow_negative_values": False},
    )


def _series(values: list) -> pd.DataFrame:
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    return pd.DataFrame(
        {"timestamp": [start + timedelta(minutes=5 * i) for i in range(len(values))], "metric_name": "cpu_usage", "value": values}
    )


@pytest.mark.parametrize("bad", ["inf", "-inf", "Infinity"])
def test_a_csv_with_an_infinite_value_is_rejected_with_its_row(bad: str) -> None:
    with pytest.raises(ValueError, match=r"Infinite values \(inf or -inf\) at CSV rows: \[4\]"):
        normalize_timeseries(_series(["1.0", "2.0", bad, "3.0"]), _config("csv"))


def test_a_live_source_drops_infinite_points_and_keeps_the_series() -> None:
    normalized = normalize_timeseries(_series([1.0, 2.0, float("inf"), 3.0]), _config("prometheus"))

    assert normalized["value"].dropna().tolist() == [1.0, 2.0, 3.0]
    assert "Dropped 1 infinite value(s)" in normalized.attrs[VALIDATION_WARNINGS_ATTR][-1]


def test_finite_values_are_untouched() -> None:
    normalized = normalize_timeseries(_series([1.0, 2.0, 3.0]), _config("csv"))

    assert normalized["value"].tolist() == [1.0, 2.0, 3.0]
    assert normalized.attrs[VALIDATION_WARNINGS_ATTR] == []
