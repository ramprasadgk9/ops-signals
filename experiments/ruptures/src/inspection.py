from __future__ import annotations

from dataclasses import dataclass, asdict
from statistics import mean

import pandas as pd


@dataclass
class DatasetInspection:
    rows: int
    columns: int
    timestamp_column: str
    value_column: str
    missing_values: int
    duplicate_timestamps: int
    sampling_interval: str
    min_value: float
    max_value: float
    timestamps_sorted: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def infer_columns(dataframe: pd.DataFrame, timestamp_column: str | None = None, value_column: str | None = None) -> tuple[str, str]:
    if timestamp_column and value_column:
        return timestamp_column, value_column
    columns = list(dataframe.columns)
    inferred_timestamp = timestamp_column or next((c for c in columns if "time" in c.lower() or "date" in c.lower()), columns[0])
    inferred_value = value_column or next((c for c in columns if c != inferred_timestamp and pd.api.types.is_numeric_dtype(dataframe[c])), columns[-1])
    return inferred_timestamp, inferred_value


def inspect_dataset(dataframe: pd.DataFrame, timestamp_column: str, value_column: str) -> DatasetInspection:
    timestamps = pd.to_datetime(dataframe[timestamp_column], utc=True, errors="coerce")
    ordered = timestamps.sort_values()
    diffs = ordered.diff().dropna()
    interval = "unknown"
    if not diffs.empty:
        mode = diffs.mode()
        interval = str(mode.iloc[0]) if not mode.empty else str(diffs.iloc[0])

    return DatasetInspection(
        rows=int(len(dataframe)),
        columns=int(dataframe.shape[1]),
        timestamp_column=timestamp_column,
        value_column=value_column,
        missing_values=int(dataframe[[timestamp_column, value_column]].isna().sum().sum()),
        duplicate_timestamps=int(timestamps.duplicated().sum()),
        sampling_interval=interval,
        min_value=float(pd.to_numeric(dataframe[value_column], errors="coerce").min()),
        max_value=float(pd.to_numeric(dataframe[value_column], errors="coerce").max()),
        timestamps_sorted=bool(timestamps.is_monotonic_increasing),
    )


def pretty_print_inspection(inspection: DatasetInspection) -> str:
    lines = [
        "Dataset inspection",
        f"Rows: {inspection.rows}",
        f"Columns: {inspection.columns}",
        f"Timestamp column: {inspection.timestamp_column}",
        f"Value column: {inspection.value_column}",
        f"Missing values (timestamp/value): {inspection.missing_values}",
        f"Duplicate timestamps: {inspection.duplicate_timestamps}",
        f"Sampling interval: {inspection.sampling_interval}",
        f"Min value: {inspection.min_value:.6g}",
        f"Max value: {inspection.max_value:.6g}",
        f"Timestamps sorted: {inspection.timestamps_sorted}",
    ]
    return "\n".join(lines)
