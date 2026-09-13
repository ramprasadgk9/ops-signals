from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from intelligence.config import InputConfig
from intelligence.normalize.normalizer import normalize_timeseries


def _config(**overrides: object) -> InputConfig:
    defaults = dict(
        source_type="csv",
        file_path="unused.csv",
        history="1d",
        interval="5m",
        timestamp_column="timestamp",
        value_column="value",
        metric_column="metric_name",
        required_columns=["timestamp", "metric_name", "value"],
        optional_columns=["service", "env", "host", "namespace", "pod", "source", "unit", "metric_type"],
        service="checkout-service",
        metric_name="errors_total",
        provider="generic",
    )
    defaults.update(overrides)
    return InputConfig(**defaults)


def _minute_series(values: list[float], *, metric_type: str | None = None) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [
        {"timestamp": start + timedelta(minutes=index), "metric_name": "errors_total", "value": value}
        for index, value in enumerate(values)
    ]
    if metric_type is not None:
        for row in rows:
            row["metric_type"] = metric_type
    return pd.DataFrame(rows)


def test_a_declared_counter_keeps_the_spike_after_resampling_instead_of_averaging_it_away() -> None:
    # A running total (e.g. cumulative errors) with a real spike at minute 3: 90 new errors in
    # one minute. Averaged across a 5-minute bucket, that spike would be blurred into a single
    # meaningless middle value (144) that looks like nothing happened.
    raw_values = [100, 105, 110, 200, 205]
    dataframe = _minute_series(raw_values, metric_type="counter")

    normalized = normalize_timeseries(dataframe, _config(interval="5m"))

    assert len(normalized) == 1
    resampled_value = normalized.iloc[0]["value"]
    assert resampled_value == 205  # last reading in the bucket, not the average (144)
    assert resampled_value != sum(raw_values) / len(raw_values)


def test_an_undeclared_counter_is_still_detected_by_its_monotonically_increasing_shape() -> None:
    # metric_type is optional and most uploads won't set it - the same spike must still survive
    # via the monotonic-values fallback, not just when a user remembers to label it "counter".
    raw_values = [100, 105, 110, 200, 205]
    dataframe = _minute_series(raw_values, metric_type=None)

    normalized = normalize_timeseries(dataframe, _config(interval="5m"))

    assert len(normalized) == 1
    assert normalized.iloc[0]["value"] == 205


def test_a_gauge_still_gets_averaged_exactly_as_before() -> None:
    # Regression check: a normal point-in-time metric (e.g. CPU%) must keep averaging - this
    # fix must not change behavior for anything that isn't a running total.
    raw_values = [40.0, 42.0, 38.0, 90.0, 41.0]
    dataframe = _minute_series(raw_values, metric_type="gauge")

    normalized = normalize_timeseries(dataframe, _config(interval="5m"))

    assert len(normalized) == 1
    assert normalized.iloc[0]["value"] == sum(raw_values) / len(raw_values)


def test_an_undeclared_non_monotonic_series_still_gets_averaged() -> None:
    # The auto-detect fallback must only catch genuinely monotonic series - a gauge that happens
    # to go up and down (not strictly increasing) must not be misclassified as a counter.
    raw_values = [40.0, 42.0, 38.0, 90.0, 41.0]
    dataframe = _minute_series(raw_values, metric_type=None)

    normalized = normalize_timeseries(dataframe, _config(interval="5m"))

    assert len(normalized) == 1
    assert normalized.iloc[0]["value"] == sum(raw_values) / len(raw_values)


def test_an_explicit_gauge_label_wins_even_over_a_monotonic_shape() -> None:
    # A short window of a genuinely-gauge metric can coincidentally look monotonic (e.g. a
    # battery that hasn't started draining yet within the sampled window). An explicit label
    # must take priority over the heuristic, not the other way around.
    raw_values = [10.0, 20.0, 30.0, 40.0, 50.0]
    dataframe = _minute_series(raw_values, metric_type="gauge")

    normalized = normalize_timeseries(dataframe, _config(interval="5m"))

    assert len(normalized) == 1
    assert normalized.iloc[0]["value"] == sum(raw_values) / len(raw_values)
