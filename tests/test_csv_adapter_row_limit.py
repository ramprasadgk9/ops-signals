from __future__ import annotations

from pathlib import Path

import pytest

from intelligence.adapters import csv_adapter as csv_adapter_module
from intelligence.adapters.csv_adapter import CSVAdapter
from intelligence.config import InputConfig


def _config(file_path: str) -> InputConfig:
    return InputConfig(
        source_type="csv",
        file_path=file_path,
        history="1d",
        interval="5m",
        timestamp_column="timestamp",
        value_column="value",
        metric_column="metric_name",
        required_columns=["timestamp", "metric_name", "value"],
        optional_columns=[],
        provider="generic",
    )


def _write_csv(path: Path, row_count: int) -> None:
    lines = ["timestamp,metric_name,value"]
    lines.extend(f"2026-01-01T00:{row:02d}:00Z,cpu_usage,{row}" for row in range(row_count))
    path.write_text("\n".join(lines))


@pytest.fixture
def small_row_limit(monkeypatch: pytest.MonkeyPatch) -> int:
    limit = 5
    monkeypatch.setattr(csv_adapter_module, "MAX_CSV_ROWS", limit)
    return limit


def test_load_rejects_a_csv_with_more_rows_than_the_configured_limit(tmp_path: Path, small_row_limit: int) -> None:
    csv_path = tmp_path / "too_big.csv"
    _write_csv(csv_path, row_count=small_row_limit + 1)
    adapter = CSVAdapter(_config("too_big.csv"), base_path=tmp_path)

    with pytest.raises(ValueError, match=str(small_row_limit)):
        adapter.load()


def test_load_accepts_a_csv_at_or_under_the_configured_limit(tmp_path: Path, small_row_limit: int) -> None:
    csv_path = tmp_path / "fits.csv"
    _write_csv(csv_path, row_count=small_row_limit)
    adapter = CSVAdapter(_config("fits.csv"), base_path=tmp_path)

    dataframe = adapter.load()

    assert len(dataframe) == small_row_limit


def test_default_row_limit_is_generous_enough_for_typical_metric_history() -> None:
    # A year of 5-minute samples for a single series is ~105k rows - should comfortably fit
    # under the default without anyone needing to touch OPS_SIGNALS_MAX_CSV_ROWS.
    one_year_of_five_minute_samples = 365 * 24 * 12
    assert one_year_of_five_minute_samples < csv_adapter_module.MAX_CSV_ROWS
