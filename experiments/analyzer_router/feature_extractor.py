from __future__ import annotations

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
    shift_index = _shift_index(y)
    slope = float(np.polyfit(x, y, 1)[0]) if len(values) >= 2 else 0.0
    trend_strength, trend_fit_r2, trend_abruptness_ratio = _trend_strength(y, shift_index)
    seasonality_strength, seasonality_dominant_lag, seasonality_peak_strength = _seasonality_strength(y)
    # _spikiness looks at point-to-point jumps. On a strongly seasonal series (e.g. taxi demand,
    # which jumps by thousands of rides every single day just from rush hour), that everyday jump
    # is bigger than a real anomaly's jump, so the anomaly reads as *quieter* than normal and never
    # crosses the threshold. When seasonality is strong enough to trust (same 0.42 bar used above
    # and at _detect_profiles), compare each point to the same point one cycle back instead - the
    # everyday rush-hour swing mostly cancels out, and a real anomaly (this Thanksgiving vs. a
    # normal Thursday) stands out on its own terms rather than against the day's own noise.
    spikiness_input = y
    if seasonality_strength >= 0.42 and seasonality_dominant_lag:
        residual = _seasonal_residual(y, seasonality_dominant_lag)
        if residual is not None:
            spikiness_input = residual
    spikiness, transient_spike_count, persistent_jump_count = _spikiness(spikiness_input)
    if seasonality_strength >= 0.42 and trend_strength < 0.28:
        trend_strength = 0.0
    autocorrelation = _autocorrelation(y)
    calendar_strength, calendar_lag = (
        calendar_seasonality(y, sampling_interval_seconds) if regular_sampling else (0.0, None)
    )
    detected_profiles = _detect_profiles(
        shift_index=shift_index,
        seasonality_strength=seasonality_strength,
        trend_strength=trend_strength,
        spikiness=spikiness,
        trend_abruptness_ratio=trend_abruptness_ratio,
        persistent_jump_count=persistent_jump_count,
    )

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
        trend_fit_r2=trend_fit_r2,
        trend_abruptness_ratio=trend_abruptness_ratio,
        seasonality_dominant_lag=seasonality_dominant_lag,
        seasonality_peak_strength=seasonality_peak_strength,
        transient_spike_count=transient_spike_count,
        persistent_jump_count=persistent_jump_count,
        calendar_seasonality_strength=calendar_strength,
        calendar_seasonality_lag=calendar_lag,
        detected_profiles=detected_profiles,
        notes=[],
    )


CALENDAR_PERIODS_SECONDS = (86_400, 604_800)
MIN_CALENDAR_CYCLES = 3


def calendar_seasonality(values: np.ndarray, interval_seconds: int | None) -> tuple[float, int | None]:
    """How strongly the series repeats on a daily or weekly cycle, as (strength 0-1, period in
    points). Classical decomposition: a centred moving average one period wide removes the level
    (and any trend or level shift), then the strength is the autocorrelation of what's left at
    exactly one period - how closely each day (or week) matches the next. Noise, random walks,
    level shifts and isolated spikes score near 0; a clear daily cycle scores near 1.

    _seasonality_strength works on point-to-point differences, which suits sharp repeating shapes
    but flattens a smooth daily cycle into noise; this measures the cycle on the values
    themselves. A period needs MIN_CALENDAR_CYCLES full cycles of data. When both fit, the daily
    cycle wins unless the weekly one is clearly stronger.
    """
    if not interval_seconds or interval_seconds <= 0:
        return 0.0, None
    best_strength, best_lag = 0.0, None
    for period_seconds in CALENDAR_PERIODS_SECONDS:
        if period_seconds % interval_seconds:
            continue
        lag = period_seconds // interval_seconds
        if lag < 4 or len(values) < MIN_CALENDAR_CYCLES * lag:
            continue
        level = pd.Series(values).rolling(lag, center=True).mean().to_numpy()
        cycle = values - level
        left, right = cycle[:-lag], cycle[lag:]
        usable = ~np.isnan(left) & ~np.isnan(right)
        if usable.sum() < lag or np.std(left[usable]) <= 1e-12 or np.std(right[usable]) <= 1e-12:
            continue
        strength = max(0.0, float(np.corrcoef(left[usable], right[usable])[0, 1]))
        if best_lag is None or strength > best_strength + 0.1:
            best_strength, best_lag = strength, int(lag)
    return float(min(1.0, best_strength)), best_lag


def _detect_profiles(
    *,
    shift_index: float,
    seasonality_strength: float,
    trend_strength: float,
    spikiness: float,
    trend_abruptness_ratio: float,
    persistent_jump_count: int,
) -> list[str]:
    profiles: set[str] = set()
    active_groups: set[str] = set()
    sustained_jump = persistent_jump_count > 0 or trend_abruptness_ratio >= 0.45

    if shift_index >= 0.12 and sustained_jump:
        profiles.add("baseline_shift")
        active_groups.add("baseline")
    if shift_index >= 0.22 and sustained_jump:
        profiles.add("regime_change")
        active_groups.add("baseline")
    if seasonality_strength >= 0.42:
        profiles.update({"seasonal", "repeating_pattern"})
        active_groups.add("seasonal")
    if trend_strength >= 0.18:
        profiles.add("trend")
        active_groups.add("trend")
    if spikiness >= 0.22:
        profiles.update({"anomaly", "outlier", "spike"})
        active_groups.add("spike")

    if len(active_groups) >= 2:
        profiles.add("mixed")

    return sorted(profiles)


def _trend_strength(values: np.ndarray, shift_index: float) -> tuple[float, float, float]:
    if len(values) < 16:
        return 0.0, 0.0, 0.0

    window_count = min(12, max(8, len(values) // 24))
    windows = [window for window in np.array_split(values, window_count) if len(window)]
    if len(windows) < 4:
        return 0.0, 0.0, 0.0

    means = np.array([float(np.mean(window)) for window in windows], dtype=float)
    x = np.arange(len(means), dtype=float)
    slope, intercept = np.polyfit(x, means, 1)
    fitted = slope * x + intercept
    total_variance = float(np.sum((means - float(np.mean(means))) ** 2))
    residual_variance = float(np.sum((means - fitted) ** 2))
    r2 = 0.0 if total_variance <= 1e-12 else max(0.0, min(1.0, 1.0 - (residual_variance / total_variance)))

    changes = np.diff(means)
    abs_changes = np.abs(changes)
    total_change = float(np.sum(abs_changes))
    if total_change <= 1e-12:
        return 0.0, r2, 0.0

    positive = float(np.sum(changes[changes > 0]))
    negative = float(abs(np.sum(changes[changes < 0])))
    directional_consistency = max(positive, negative) / total_change
    abruptness_ratio = float(np.max(abs_changes) / total_change)
    endpoint_delta = abs(float(means[-1] - means[0]))
    magnitude = min(1.0, endpoint_delta / (abs(float(np.mean(means))) + 1e-9))
    continuity = max(0.0, 1.0 - abruptness_ratio)
    strength = r2 * directional_consistency * continuity * magnitude
    continuous_strength = 0.0

    if len(changes) >= 4:
        dominant_change_index = int(np.argmax(abs_changes))
        continuous_changes = np.delete(changes, dominant_change_index)
        continuous_abs_changes = np.abs(continuous_changes)
        continuous_total = float(np.sum(continuous_abs_changes))
        if continuous_total > 1e-12:
            continuous_positive = float(np.sum(continuous_changes[continuous_changes > 0]))
            continuous_negative = float(abs(np.sum(continuous_changes[continuous_changes < 0])))
            continuous_direction = max(continuous_positive, continuous_negative) / continuous_total
            continuous_magnitude = min(1.0, continuous_total / (abs(float(np.mean(means))) + 1e-9))
            continuous_strength = continuous_direction * continuous_magnitude

    if shift_index >= 0.12 and abruptness_ratio >= 0.55:
        strength *= 0.2
    strength = max(strength, continuous_strength)

    return float(max(0.0, min(1.0, strength))), float(r2), abruptness_ratio


def _seasonality_strength(values: np.ndarray) -> tuple[float, int | None, float]:
    if len(values) < 24:
        return 0.0, None, 0.0

    detrended = _remove_linear_trend(values)
    differenced = np.diff(detrended)
    if len(differenced) < 12 or float(np.std(differenced, ddof=0)) <= 1e-12:
        return 0.0, None, 0.0

    centered = differenced - float(np.mean(differenced))
    max_lag = min(len(centered) // 3, 400)
    if max_lag < 4:
        return 0.0, None, 0.0

    correlations: dict[int, float] = {}
    for lag in range(2, max_lag + 1):
        left = centered[:-lag]
        right = centered[lag:]
        if len(left) < 4 or float(np.std(left, ddof=0)) <= 1e-12 or float(np.std(right, ddof=0)) <= 1e-12:
            continue
        corr = float(np.corrcoef(left, right)[0, 1])
        if np.isfinite(corr):
            correlations[lag] = max(0.0, corr)

    if not correlations:
        return 0.0, None, 0.0

    best_lag, best_corr = max(correlations.items(), key=lambda item: item[1])
    if best_corr < 0.35:
        return 0.0, best_lag, best_corr

    # Prefer the fundamental period if best_lag is an integer multiple of a smaller lag
    # with comparable correlation (prevents harmonic doubling from cross-platform float variations).
    for divisor in range(min(best_lag // 2, 6), 1, -1):
        if best_lag % divisor == 0:
            sub_lag = best_lag // divisor
            if sub_lag in correlations and correlations[sub_lag] >= best_corr - 0.05:
                best_lag = sub_lag
                best_corr = correlations[best_lag]
                break

    neighbor_values = [
        corr
        for lag, corr in correlations.items()
        if lag != best_lag and abs(lag - best_lag) <= 3
    ]
    neighbor_mean = float(np.mean(neighbor_values)) if neighbor_values else 0.0
    prominence = max(0.0, best_corr - neighbor_mean)

    harmonic_scores = []
    for multiple in (2, 3):
        harmonic = best_lag * multiple
        if harmonic <= max_lag:
            harmonic_scores.append(correlations.get(harmonic, 0.0))
    harmonic_support = max(harmonic_scores) if harmonic_scores else best_corr
    cycles = len(values) / max(best_lag, 1)
    cycle_factor = min(1.0, cycles / 3.0)

    broad_high_ratio = float(np.mean(np.array(list(correlations.values())) > best_corr * 0.8))
    if broad_high_ratio > 0.25 and prominence < 0.08:
        return 0.0, best_lag, best_corr

    strength = best_corr * max(prominence / 0.1, 0.0) * max(harmonic_support, 0.5) * cycle_factor
    return float(max(0.0, min(1.0, strength))), best_lag, best_corr


def _seasonal_residual(values: np.ndarray, lag: int) -> np.ndarray | None:
    # values[t] - values[t - lag] for every point that has a prior cycle to compare against. The
    # first `lag` points have no prior cycle yet and are simply left out, rather than compared
    # against something that doesn't exist - the series just needs to be long enough to have at
    # least one full cycle of residual left over after dropping them.
    if lag <= 0 or len(values) <= lag:
        return None
    residual = values[lag:] - values[:-lag]
    return residual


def _spikiness(values: np.ndarray) -> tuple[float, int, int]:
    if len(values) < 8:
        return 0.0, 0, 0

    diffs = np.diff(values)
    abs_diffs = np.abs(diffs)
    median_diff = float(np.median(abs_diffs))
    mad = float(np.median(np.abs(abs_diffs - median_diff)))
    # Deliberately no std(diffs)-based term here anymore: it used to be part of this max(), but
    # np.std is not robust to the very outliers this threshold exists to catch - with enough
    # injected spikes to noticeably move the raw variance (empirically, as few as ~8 out of 288
    # points), std(diffs) inflates almost linearly with the injected magnitude itself, so the
    # threshold chased the outliers upward and they could never cross it no matter how extreme
    # (confirmed: identical 0.0 spikiness from magnitude 6 through 60 on the PyOD Outlier Lab's
    # default shape - see issue #21). median_diff + 10*mad is already a high-breakdown robust
    # estimator and does the job; std(values)*0.08 stays as a small noise floor since it isn't the
    # term that was breaking down.
    threshold = max(
        median_diff + (10.0 * mad),
        float(np.std(values, ddof=0)) * 0.08,
        1e-9,
    )
    if mad <= 1e-12 and float(np.std(abs_diffs, ddof=0)) <= 1e-12:
        return 0.0, 0, 0
    candidate_indexes = np.where(abs_diffs > threshold)[0]
    if not len(candidate_indexes):
        return 0.0, 0, 0

    transient_count = 0
    persistent_count = 0
    baseline_window = max(5, min(24, len(values) // 40))
    return_tolerance = max(mad * 6.0, median_diff * 3.0, float(np.std(values, ddof=0)) * 0.05, 1e-9)
    edge_spike_counted = False

    for index in candidate_indexes:
        before_start = max(0, index - baseline_window + 1)
        before = values[before_start : index + 1]
        after_end = min(len(values), index + 1 + baseline_window)
        after = values[index + 1 : after_end]
        if len(before) < 3:
            continue
        if len(after) < 3:
            # A jump in the newest points can't be confirmed as transient yet - there's nothing
            # after it to come back down to. Skipping it meant a fresh spike, exactly what a live
            # or alert window ending "now" is about, never got a spike detector (QA-31). Count it
            # as a spike when the newest reading sits well clear of the recent level (twice the
            # jump threshold, since no return can be checked), at most once per series.
            if not edge_spike_counted and abs(float(values[index + 1]) - float(np.median(before))) >= 2.0 * threshold:
                transient_count += 1
                edge_spike_counted = True
            continue
        before_level = float(np.median(before))
        after_level = float(np.median(after))
        jump = float(values[index + 1] - values[index])
        reversed_quickly = False
        for next_index in range(index + 1, min(len(diffs), index + 1 + baseline_window)):
            if abs(float(diffs[next_index])) >= threshold and np.sign(diffs[next_index]) == -np.sign(jump):
                post_reversal = values[next_index + 1 : min(len(values), next_index + 1 + baseline_window)]
                if len(post_reversal) and abs(float(np.median(post_reversal)) - before_level) <= return_tolerance:
                    reversed_quickly = True
                    break
        if reversed_quickly or abs(after_level - before_level) <= return_tolerance:
            transient_count += 1
        else:
            persistent_count += 1

    score = min(1.0, transient_count / 3.0)
    return float(score), int(transient_count), int(persistent_count)


def _remove_linear_trend(values: np.ndarray) -> np.ndarray:
    if len(values) < 2:
        return values.astype(float)
    x = np.arange(len(values), dtype=float)
    slope, intercept = np.polyfit(x, values.astype(float), 1)
    return values.astype(float) - ((slope * x) + intercept)


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
        trend_fit_r2=0.0,
        trend_abruptness_ratio=0.0,
        seasonality_dominant_lag=None,
        seasonality_peak_strength=0.0,
        transient_spike_count=0,
        persistent_jump_count=0,
        detected_profiles=[],
    )
