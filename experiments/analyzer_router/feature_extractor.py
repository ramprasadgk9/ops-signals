from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from statistics import mean, pstdev, pvariance

import numpy as np
import pandas as pd

from .models import SeriesProfile, ValidationDecision


def extract_series_profile(
    dataframe: pd.DataFrame,
    timestamp_column: str | None,
    value_column: str | None,
    interpolation_enabled: bool = True,
    maximum_gap_points: int = 5,
    maximum_interpolated_percentage: float = 20.0,
) -> tuple[ValidationDecision, SeriesProfile, pd.DataFrame]:
    df = dataframe.copy()
    validation = _validate(df, timestamp_column, value_column)
    if not validation.valid:
        return validation, _empty_profile(), df

    working = _clean(df, timestamp_column, value_column, interpolation_enabled, maximum_gap_points, maximum_interpolated_percentage, validation)
    profile = _profile(working, timestamp_column, value_column, validation)
    return validation, profile, working


def _validate(df: pd.DataFrame, timestamp_column: str | None, value_column: str | None) -> ValidationDecision:
    if value_column is None or value_column not in df.columns:
        return ValidationDecision(False, "rejected", ["No value column exists."], [])
    if timestamp_column is not None and timestamp_column not in df.columns:
        return ValidationDecision(False, "rejected", ["Timestamp column was selected but is not present."], [])

    return ValidationDecision(True, "accepted", [], [])


def _clean(
    df: pd.DataFrame,
    timestamp_column: str | None,
    value_column: str,
    interpolation_enabled: bool,
    maximum_gap_points: int,
    maximum_interpolated_percentage: float,
    validation: ValidationDecision,
) -> pd.DataFrame:
    working = df.copy()
    if timestamp_column and timestamp_column in working.columns:
        working[timestamp_column] = pd.to_datetime(working[timestamp_column], utc=True, errors="coerce")
        working = working.sort_values(timestamp_column)
    working[value_column] = pd.to_numeric(working[value_column], errors="coerce").replace([np.inf, -np.inf], np.nan)
    original_count = len(working)
    valid_values = int(working[value_column].notna().sum())
    invalid_values = original_count - valid_values
    if interpolation_enabled and invalid_values:
        working[value_column] = _interpolate_series(working[value_column], maximum_gap_points, maximum_interpolated_percentage, validation)
    if timestamp_column and timestamp_column in working.columns:
        working = working.dropna(subset=[timestamp_column])
    working = working.reset_index(drop=True)
    return working


def _interpolate_series(series: pd.Series, maximum_gap_points: int, maximum_interpolated_percentage: float, validation: ValidationDecision) -> pd.Series:
    interpolated = series.copy()
    missing = interpolated.isna()
    if not missing.any():
        return interpolated
    total_missing = int(missing.sum())
    allowed = int(len(series) * (maximum_interpolated_percentage / 100.0))
    if total_missing > allowed:
        validation.warnings.append("Interpolation skipped because missing percentage is above the configured ceiling.")
        return interpolated
    interpolated = interpolated.interpolate(method="linear", limit=maximum_gap_points, limit_direction="both")
    interpolated = interpolated.ffill(limit=1).bfill(limit=1)
    validation.warnings.append(f"Interpolated up to {maximum_gap_points} consecutive gaps and limited edge filling to 1 point.")
    return interpolated


def _profile(df: pd.DataFrame, timestamp_column: str | None, value_column: str, validation: ValidationDecision) -> SeriesProfile:
    values = pd.to_numeric(df[value_column], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().astype(float)
    timestamps = None
    if timestamp_column and timestamp_column in df.columns:
        timestamps = pd.to_datetime(df[timestamp_column], utc=True, errors="coerce").dropna()
    sample_count = len(values)
    if sample_count == 0:
        validation.valid = False
        validation.status = "rejected"
        validation.reasons.append("No valid numeric observations remain.")
        return _empty_profile()

    duration_seconds = None
    sampling_interval_seconds = None
    regular_sampling = False
    irregular_sampling_percentage = 0.0
    duplicate_timestamp_count = 0
    if timestamps is not None and len(timestamps) >= 2:
        duplicate_timestamp_count = int(timestamps.duplicated().sum())
        diffs = timestamps.sort_values().diff().dropna().dt.total_seconds().to_numpy()
        if len(diffs):
            sampling_interval_seconds = int(np.median(diffs))
            duration_seconds = int((timestamps.max() - timestamps.min()).total_seconds())
            irregular_sampling_percentage = float(np.mean(np.abs(diffs - sampling_interval_seconds) > max(1.0, sampling_interval_seconds * 0.10)) * 100.0)
            regular_sampling = irregular_sampling_percentage <= 10.0

    missing_percentage = float(df[value_column].isna().mean() * 100.0) if len(df) else 0.0
    constant_value_percentage = float(np.mean(values == values.iloc[0]) * 100.0) if len(values) else 0.0
    x = np.arange(len(values), dtype=float)
    y = values.to_numpy(dtype=float)
    slope = float(np.polyfit(x, y, 1)[0]) if len(values) >= 2 else 0.0
    fitted_delta = abs(slope * max(len(values) - 1, 1))
    trend_strength = min(1.0, fitted_delta / (abs(float(np.mean(y))) + 1e-9)) if len(values) else 0.0
    seasonality_strength = _seasonality_strength(y)
    spikiness = _spikiness(y)
    shift_index = _shift_index(y)
    autocorrelation = _autocorrelation(y)

    return SeriesProfile(
        original_sample_count=len(df),
        valid_sample_count=sample_count,
        invalid_timestamp_count=int(df[timestamp_column].isna().sum()) if timestamp_column and timestamp_column in df.columns else 0,
        invalid_value_count=int(df[value_column].isna().sum()),
        missing_percentage=missing_percentage,
        duplicate_timestamp_count=duplicate_timestamp_count,
        sampling_interval_seconds=sampling_interval_seconds,
        duration_seconds=duration_seconds,
        irregular_sampling_percentage=irregular_sampling_percentage,
        interpolated_sample_count=int(df[value_column].isna().sum()),
        interpolated_percentage=float(df[value_column].isna().mean() * 100.0),
        constant_value_percentage=constant_value_percentage,
        sample_count=sample_count,
        regular_sampling=regular_sampling,
        mean=float(np.mean(y)),
        stddev=float(np.std(y, ddof=0)) if len(y) > 1 else 0.0,
        minimum=float(np.min(y)),
        maximum=float(np.max(y)),
        variance=float(np.var(y, ddof=0)) if len(y) > 1 else 0.0,
        trend_slope=slope,
        trend_strength=trend_strength,
        seasonality_strength=seasonality_strength,
        spikiness=spikiness,
        shift_index=shift_index,
        autocorrelation=autocorrelation,
        notes=[],
    )


def _seasonality_strength(values: np.ndarray) -> float:
    if len(values) < 8:
        return 0.0
    lag = max(2, min(24, len(values) // 4))
    if len(values) <= lag:
        return 0.0
    corr = np.corrcoef(values[:-lag], values[lag:])[0, 1]
    if np.isnan(corr):
        return 0.0
    return float(max(0.0, min(1.0, abs(corr))))


def _spikiness(values: np.ndarray) -> float:
    if len(values) < 3:
        return 0.0
    diffs = np.abs(np.diff(values))
    if not len(diffs):
        return 0.0
    median = float(np.median(diffs))
    if median == 0:
        return 0.0
    return float(min(1.0, np.max(diffs) / (median * 5.0)))


def _shift_index(values: np.ndarray) -> float:
    if len(values) < 6:
        return 0.0
    best = 0.0
    start = max(3, int(len(values) * 0.2))
    end = min(len(values) - 3, int(len(values) * 0.8))
    for split in range(start, end + 1):
        left = values[:split]
        right = values[split:]
        denom = abs(float(np.mean(left))) + abs(float(np.mean(right))) + 1e-9
        best = max(best, abs(float(np.mean(right)) - float(np.mean(left))) / denom)
    return float(min(1.0, best))


def _autocorrelation(values: np.ndarray) -> float | None:
    if len(values) < 4:
        return None
    corr = np.corrcoef(values[:-1], values[1:])[0, 1]
    if np.isnan(corr):
        return None
    return float(corr)


def _empty_profile() -> SeriesProfile:
    return SeriesProfile(
        original_sample_count=0,
        valid_sample_count=0,
        invalid_timestamp_count=0,
        invalid_value_count=0,
        missing_percentage=0.0,
        duplicate_timestamp_count=0,
        sampling_interval_seconds=None,
        duration_seconds=None,
        irregular_sampling_percentage=0.0,
        interpolated_sample_count=0,
        interpolated_percentage=0.0,
        constant_value_percentage=100.0,
        sample_count=0,
        regular_sampling=False,
        mean=0.0,
        stddev=0.0,
        minimum=0.0,
        maximum=0.0,
        variance=0.0,
        trend_slope=0.0,
        trend_strength=0.0,
        seasonality_strength=0.0,
        spikiness=0.0,
        shift_index=0.0,
        autocorrelation=None,
    )
