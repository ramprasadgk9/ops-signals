from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from intelligence.config import InputConfig
from intelligence.normalize.normalizer import VALIDATION_WARNINGS_ATTR, normalize_timeseries


def _config(**validation: object) -> InputConfig:
    return InputConfig(
        source_type="csv",
        file_path="unused.csv",
        history="1d",
        interval="5m",
        timestamp_column="timestamp",
        value_column="value",
        metric_column="metric_name",
        required_columns=["timestamp", "metric_name", "value"],
        optional_columns=["service", "env", "host", "namespace", "pod", "source", "unit", "metric_type"],
        service="traffic-sensor",
        metric_name="speed",
        provider="generic",
        validation={"max_gap_minutes": 60, **validation},
    )


def _series_with_outage(outage_hours: float) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    before = [start + timedelta(minutes=5 * index) for index in range(24)]
    resume = before[-1] + timedelta(hours=outage_hours)
    after = [resume + timedelta(minutes=5 * index) for index in range(24)]
    return pd.DataFrame(
        {"timestamp": before + after, "metric_name": "speed", "value": [60.0] * 48}
    )


def test_a_multi_hour_outage_keeps_the_series_and_records_a_warning_by_default() -> None:
    normalized = normalize_timeseries(_series_with_outage(7), _config())

    assert normalized["value"].notna().sum() == 48
    # The outage becomes empty resampled buckets, which is what data_health reports on.
    assert normalized["value"].isna().any()
    [warning] = normalized.attrs[VALIDATION_WARNINGS_ATTR]
    assert "exceeds 60.0m" in warning


def test_gap_policy_reject_keeps_the_old_strict_behavior() -> None:
    with pytest.raises(ValueError, match="exceeds 60.0m"):
        normalize_timeseries(_series_with_outage(7), _config(gap_policy="reject"))


def test_a_gap_within_the_limit_records_no_warning() -> None:
    normalized = normalize_timeseries(_series_with_outage(0.5), _config(gap_policy="reject"))

    assert normalized.attrs[VALIDATION_WARNINGS_ATTR] == []


def test_an_unknown_gap_policy_is_a_configuration_error() -> None:
    with pytest.raises(ValueError, match="Unknown gap_policy"):
        normalize_timeseries(_series_with_outage(7), _config(gap_policy="ignore"))
