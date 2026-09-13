from __future__ import annotations

import pandas as pd
import pytest

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
        optional_columns=["service"],
        provider="datadog",
        provider_mappings={"timestamp": "ts_epoch_ms"},
    )
    defaults.update(overrides)
    return InputConfig(**defaults)


def test_missing_required_column_names_the_mapping_that_never_matched() -> None:
    # The CSV has neither "timestamp" nor the "ts_epoch_ms" column the configured mapping
    # expected - previously this only produced the generic "missing columns" error with no
    # indication that a mapping was even involved.
    dataframe = pd.DataFrame({"metric_name": ["errors_total"], "value": [10]})

    with pytest.raises(ValueError) as excinfo:
        normalize_timeseries(dataframe, _config())

    message = str(excinfo.value)
    assert "'timestamp'" in message
    assert "'ts_epoch_ms'" in message
    assert "configured provider mapping" in message


def test_missing_required_column_without_a_mapping_still_lists_available_columns() -> None:
    # No mapping configured for the missing column - the error should still be useful (list what
    # columns the file actually has) without fabricating a mapping hint that doesn't exist.
    dataframe = pd.DataFrame({"metric_name": ["errors_total"], "value": [10]})

    with pytest.raises(ValueError) as excinfo:
        normalize_timeseries(dataframe, _config(provider_mappings={}, provider="generic"))

    message = str(excinfo.value)
    assert "Columns found in the file" in message
    assert "metric_name" in message
    assert "configured provider mapping" not in message
