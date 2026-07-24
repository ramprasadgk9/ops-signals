from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class DataQualityReport:
    issues: list[str]

    @property
    def ok(self) -> bool:
        return not self.issues


def validate_data(dataframe: pd.DataFrame, timestamp_column: str, value_column: str) -> DataQualityReport:
    issues: list[str] = []
    timestamps = pd.to_datetime(dataframe[timestamp_column], utc=True, errors="coerce")
    values = pd.to_numeric(dataframe[value_column], errors="coerce")

    if timestamps.isna().any():
        issues.append(f"Missing or invalid timestamps: {int(timestamps.isna().sum())}")
    if values.isna().any():
        issues.append(f"NaN values in metric column: {int(values.isna().sum())}")
    if dataframe.duplicated().any():
        issues.append(f"Duplicated rows: {int(dataframe.duplicated().sum())}")
    if values.nunique(dropna=True) <= 1:
        issues.append("Constant or near-constant signal detected")
    if not timestamps.is_monotonic_increasing:
        issues.append("Out-of-order timestamps detected")

    return DataQualityReport(issues=issues)
