from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from intelligence.config import InputConfig
from intelligence.normalize.normalizer import RESOLVED_INTERVALS_ATTR, VALIDATION_WARNINGS_ATTR, normalize_timeseries


def _config(interval: str) -> InputConfig:
    return InputConfig(
        source_type="csv",
        file_path="unused.csv",
        history="1d",
        interval=interval,
        timestamp_column="timestamp",
        value_column="value",
        metric_column="metric_name",
        required_columns=["timestamp", "metric_name", "value"],
        optional_columns=["service", "env", "host", "namespace", "pod", "source", "unit", "metric_type"],
        service="checkout",
        metric_name="cpu_usage",
        provider="generic",
    )


def _series(offsets_seconds: list[int], metric_name: str = "cpu_usage") -> pd.DataFrame:
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    return pd.DataFrame(
        {
            "timestamp": [start + timedelta(seconds=offset) for offset in offsets_seconds],
            "metric_name": metric_name,
            "value": [50.0 + (index % 3) for index in range(len(offsets_seconds))],
        }
    )


def test_auto_resamples_at_the_spacing_measured_from_the_data() -> None:
    normalized = normalize_timeseries(_series([index * 900 for index in range(100)]), _config("auto"))

    assert len(normalized) == 100
    assert normalized["value"].notna().all()
    assert normalized.attrs[RESOLVED_INTERVALS_ATTR] == ["15m"]


def test_a_blank_interval_is_treated_as_auto() -> None:
    normalized = normalize_timeseries(_series([index * 60 for index in range(30)]), _config(""))

    assert normalized.attrs[RESOLVED_INTERVALS_ATTR] == ["1m"]
    assert len(normalized) == 30


def test_one_long_outage_does_not_stretch_the_measured_interval() -> None:
    # 5-minute data with a 6-hour hole: span / count would say about 9 minutes; the typical gap
    # between points is still 5.
    before = [index * 300 for index in range(60)]
    after = [before[-1] + 6 * 3600 + index * 300 for index in range(60)]

    normalized = normalize_timeseries(_series(before + after), _config("auto"))

    assert normalized.attrs[RESOLVED_INTERVALS_ATTR] == ["5m"]


def test_small_export_jitter_rounds_to_the_intended_interval() -> None:
    offsets = [index * 900 + (index % 2) * 3 for index in range(50)]

    normalized = normalize_timeseries(_series(offsets), _config("auto"))

    assert normalized.attrs[RESOLVED_INTERVALS_ATTR] == ["15m"]


def test_each_series_in_one_file_gets_its_own_interval() -> None:
    fast = _series([index * 60 for index in range(40)], metric_name="cpu_usage")
    slow = _series([index * 900 for index in range(40)], metric_name="queue_depth")

    normalized = normalize_timeseries(pd.concat([fast, slow], ignore_index=True), _config("auto"))

    assert normalized.attrs[RESOLVED_INTERVALS_ATTR] == ["1m", "15m"]
    counts = normalized.groupby("metric_name").size().to_dict()
    assert counts == {"cpu_usage": 40, "queue_depth": 40}


def test_a_single_point_falls_back_to_five_minutes() -> None:
    normalized = normalize_timeseries(_series([0]), _config("auto"))

    assert normalized.attrs[RESOLVED_INTERVALS_ATTR] == ["5m"]


def test_an_explicit_interval_is_kept_and_warns_when_most_slots_are_empty() -> None:
    normalized = normalize_timeseries(_series([index * 900 for index in range(100)]), _config("5m"))

    assert normalized.attrs[RESOLVED_INTERVALS_ATTR] == ["5m"]
    warnings = normalized.attrs[VALIDATION_WARNINGS_ATTR]
    assert len(warnings) == 1
    assert "every 15m" in warnings[0]
    assert "checkout / cpu_usage" in warnings[0]


def test_an_explicit_interval_that_matches_the_data_does_not_warn() -> None:
    normalized = normalize_timeseries(_series([index * 300 for index in range(100)]), _config("5m"))

    assert normalized.attrs[VALIDATION_WARNINGS_ATTR] == []
    assert len(normalized) == 100
