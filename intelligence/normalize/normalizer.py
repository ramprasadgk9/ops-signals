from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from pandas.api.types import is_datetime64_any_dtype, is_object_dtype

from intelligence.config import InputConfig


logger = logging.getLogger(__name__)

# How an oversized timestamp gap is handled. "warn" keeps the series: resampling turns the gap into
# empty buckets, data_health reports it as a finding, and the message is kept on the normalized
# frame. "reject" refuses the whole series, which throws away every other point in it - real sensor
# and traffic feeds have multi-hour outages, and rejecting them hid those series from analysis.
GAP_POLICIES = {"warn", "reject"}
VALIDATION_WARNINGS_ATTR = "validation_warnings"
# The interval(s) each series was actually resampled at, in first-seen order. With "auto" this is
# what was measured from the data, so callers can show it instead of the word "auto".
RESOLVED_INTERVALS_ATTR = "resolved_intervals"

# "auto" (or blank) measures each series' own spacing instead of assuming one. A CSV sampled every
# 15 minutes and resampled at a fixed 5m gets two empty buckets per real point, and every analyzer
# then rejects the series for missing values.
AUTO_INTERVAL = "auto"
# Used when a series has too few distinct timestamps to measure a spacing.
FALLBACK_INTERVAL = "5m"
# An explicitly chosen interval that leaves more than this share of buckets empty is almost
# certainly finer than the data, so the caller is told what the data's spacing actually is.
EMPTY_BUCKET_WARNING_RATIO = 0.5

# `cluster` is the external label that tells apart otherwise identical series from different
# clusters behind one Mimir/Thanos endpoint; empty for single-cluster data.
CORE_COLUMNS = ["metric_name", "timestamp", "value", "service", "env", "host", "namespace", "pod", "source", "unit", "metric_type", "cluster"]


def normalize_timeseries(dataframe: pd.DataFrame, config: InputConfig) -> pd.DataFrame:
    if dataframe.empty:
        # Resampling would otherwise fail with pandas' "No objects to concatenate".
        raise ValueError("The data has no rows to analyze: only a header, or nothing at all.")
    working = dataframe.copy()
    working = _apply_provider_mappings(working, config)
    working = _apply_core_renames(working, config)
    if "metric_name" not in working.columns and config.metric_name:
        # A file of one metric may leave the metric column out and name it at upload instead.
        working["metric_name"] = config.metric_name

    _validate_required_columns(working, config)
    _apply_datadog_tags(working, config)

    working["timestamp"] = _parse_timestamps(working["timestamp"], config.provider)
    working["value"] = _parse_values(working["value"])
    working, infinite_warning = _drop_infinite_values(working, config)
    validation_warnings = _validate_rules(working, config)
    if infinite_warning:
        validation_warnings.append(infinite_warning)

    for column in config.optional_columns:
        if column not in working.columns:
            working[column] = None
    if "cluster" not in working.columns:
        working["cluster"] = None

    if "service" in working.columns and config.service:
        working["service"] = working["service"].where(working["service"].notna(), config.service)
    if "metric_name" in working.columns and config.metric_name:
        working["metric_name"] = working["metric_name"].where(working["metric_name"].notna(), config.metric_name)
    if "source" in working.columns:
        provider = (config.provider or "generic").lower()
        working["source"] = working["source"].where(working["source"].notna(), provider)

    for column in ["metric_name", "service", "env", "host", "namespace", "pod", "source", "unit", "metric_type", "cluster"]:
        if column in working.columns:
            working[column] = working[column].where(working[column].notna(), None)

    metadata_columns = [column for column in CORE_COLUMNS if column not in {"timestamp", "value"}]
    group_columns = [column for column in metadata_columns if column in working.columns]

    requested_interval = (config.interval or "").strip()
    auto_interval = requested_interval.lower() in {"", AUTO_INTERVAL}
    resolved_intervals: list[str] = []

    normalized_frames: list[pd.DataFrame] = []
    for keys, group in working.groupby(group_columns, dropna=False):
        group = group.sort_values("timestamp")
        measured_interval = _measure_interval(group["timestamp"])
        interval = (measured_interval or FALLBACK_INTERVAL) if auto_interval else requested_interval
        if interval not in resolved_intervals:
            resolved_intervals.append(interval)
        aggregation = "last" if _is_running_total(group) else "mean"
        resampled = (
            group.set_index("timestamp")
            .resample(_pandas_frequency(interval))["value"]
            .agg(aggregation)
            .reset_index()
        )

        if not isinstance(keys, tuple):
            keys = (keys,)

        if not auto_interval and measured_interval and measured_interval != interval and not resampled.empty:
            empty_ratio = float(resampled["value"].isna().mean())
            if empty_ratio > EMPTY_BUCKET_WARNING_RATIO:
                series_label = _series_label(dict(zip(group_columns, keys)))
                validation_warnings.append(
                    f"Interval {interval} leaves {empty_ratio:.0%} of time slots empty for {series_label}: "
                    f"the data has a point about every {measured_interval}. "
                    f"Set Interval to auto or {measured_interval}."
                )

        for column, value in zip(group_columns, keys):
            resampled[column] = value

        normalized_frames.append(resampled)

    normalized = pd.concat(normalized_frames, ignore_index=True)
    normalized = normalized[CORE_COLUMNS].copy()

    tag_columns = [column for column in working.columns if column not in CORE_COLUMNS]
    tag_lookup = (
        working[[*CORE_COLUMNS, *tag_columns]]
        .drop_duplicates(subset=["metric_name", "timestamp", "service", "env", "host", "namespace", "pod", "source", "unit", "metric_type", "cluster"])
        .set_index(["metric_name", "timestamp", "service", "env", "host", "namespace", "pod", "source", "unit", "metric_type", "cluster"])
        if tag_columns
        else None
    )

    def build_tags(row: pd.Series) -> dict[str, object]:
        if tag_lookup is None:
            return {}
        key = tuple(row[column] for column in ["metric_name", "timestamp", "service", "env", "host", "namespace", "pod", "source", "unit", "metric_type", "cluster"])
        if key not in tag_lookup.index:
            return {}
        tag_row = tag_lookup.loc[key]
        if isinstance(tag_row, pd.DataFrame):
            tag_row = tag_row.iloc[0]
        tag_dict = tag_row.to_dict()
        provider_tags = tag_dict.pop("__provider_tags_json", None)
        merged = {column: value for column, value in tag_dict.items() if pd.notna(value)}
        if isinstance(provider_tags, dict):
            merged.update(provider_tags)
        return merged

    normalized["tags_json"] = normalized.apply(build_tags, axis=1)
    normalized = normalized.sort_values(["metric_name", "timestamp"]).reset_index(drop=True)
    normalized.attrs[VALIDATION_WARNINGS_ATTR] = validation_warnings
    normalized.attrs[RESOLVED_INTERVALS_ATTR] = resolved_intervals
    return normalized


def _measure_interval(timestamps: pd.Series) -> str | None:
    """The series' typical spacing: the median gap between distinct timestamps. The median, not
    span / count, so one long outage in a 5-minute series doesn't stretch the answer to an hour.
    Rounded to whole minutes from a minute up, whole seconds below, so small export jitter
    (14:59 instead of 15:00) doesn't produce odd buckets. None when it can't be measured."""
    distinct = pd.Series(timestamps.dropna().unique()).sort_values()
    if len(distinct) < 2:
        return None
    median_seconds = float(distinct.diff().dt.total_seconds().dropna().median())
    if median_seconds <= 0:
        return None
    if median_seconds >= 60:
        return f"{max(round(median_seconds / 60), 1)}m"
    return f"{max(round(median_seconds), 1)}s"


def _pandas_frequency(interval: str) -> str:
    return interval.replace("m", "min") if interval.endswith("m") else interval


def _series_label(labels: dict[str, object]) -> str:
    parts = [
        str(labels[column])
        for column in ("service", "metric_name")
        if labels.get(column) is not None and not pd.isna(labels[column]) and labels[column] != ""
    ]
    return " / ".join(parts) or "the series"


def _is_running_total(group: pd.DataFrame) -> bool:
    """Averaging a cumulative running total (e.g. a request/error counter) within a resample
    bucket blurs a real spike into a meaningless middle value instead of preserving it - taking
    the last reading in the bucket is the correct way to downsample a running total. Prefers an
    explicit metric_type label (every row in `group` shares one value for it, since it's already
    a groupby key); falls back to detecting a monotonically non-decreasing series when the label
    is absent, since metric_type is optional and most uploads leave it blank. Doesn't attempt to
    detect a counter that has reset (dropped back to zero) mid-series - that shows up as a
    negative jump instead, which is itself a legitimate signal worth surfacing, not hiding."""
    if "metric_type" in group.columns:
        declared = group["metric_type"].dropna()
        if not declared.empty:
            return str(declared.iloc[0]).strip().lower() == "counter"
    values = group["value"].dropna()
    if len(values) < 2:
        return False
    return bool((values.diff().dropna() >= 0).all())


def _apply_provider_mappings(dataframe: pd.DataFrame, config: InputConfig) -> pd.DataFrame:
    working = dataframe.copy()
    provider = (config.provider or "generic").lower()

    if provider == "prometheus":
        if "__name__" in working.columns and "metric_name" not in working.columns:
            working = working.rename(columns={"__name__": "metric_name"})
        elif "metric" in working.columns and "metric_name" not in working.columns:
            working = working.rename(columns={"metric": "metric_name"})
    elif provider == "datadog":
        if "ts_epoch_ms" in working.columns and "timestamp" not in working.columns:
            working = working.rename(columns={"ts_epoch_ms": "timestamp"})
        elif "ts_epoch" in working.columns and "timestamp" not in working.columns:
            working = working.rename(columns={"ts_epoch": "timestamp"})

    mapping = config.provider_mappings or {}
    rename_map: dict[str, str] = {}
    for canonical_name, source_name in mapping.items():
        if source_name in working.columns and canonical_name not in working.columns:
            rename_map[source_name] = canonical_name
    if rename_map:
        working = working.rename(columns=rename_map)
    return working


def _apply_core_renames(dataframe: pd.DataFrame, config: InputConfig) -> pd.DataFrame:
    rename_map: dict[str, str] = {}
    if config.metric_column in dataframe.columns and config.metric_column != "metric_name":
        rename_map[config.metric_column] = "metric_name"
    if config.timestamp_column in dataframe.columns and config.timestamp_column != "timestamp":
        rename_map[config.timestamp_column] = "timestamp"
    if config.value_column in dataframe.columns and config.value_column != "value":
        rename_map[config.value_column] = "value"
    if rename_map:
        return dataframe.rename(columns=rename_map)
    return dataframe


def _validate_required_columns(dataframe: pd.DataFrame, config: InputConfig) -> None:
    required = ["timestamp", "metric_name", "value"]
    missing = [column for column in required if column not in dataframe.columns]
    if not missing:
        return

    # A configured provider_mappings entry that never matched a real column is the most likely
    # cause of a missing required column, but was previously silently skipped (see
    # _apply_provider_mappings) with no trace of it in the resulting error - naming the specific
    # mapping and what it expected turns "guess what's wrong" into "here's exactly what to fix".
    mapping = config.provider_mappings or {}
    mapping_hints = [
        f"'{canonical_name}' was expected to come from a column named '{mapping[canonical_name]}' "
        "(per the configured provider mapping), but no such column was found in the uploaded file."
        for canonical_name in missing
        if canonical_name in mapping
    ]
    hint_text = " " + " ".join(mapping_hints) if mapping_hints else ""
    raise ValueError(
        f"CSV missing canonical required columns after mapping: {missing}. "
        f"Columns found in the file: {list(dataframe.columns)}.{hint_text}"
    )


def _parse_timestamps(series: pd.Series, provider: str) -> pd.Series:
    if is_datetime64_any_dtype(series):
        parsed = pd.to_datetime(series, utc=True, errors="coerce")
    elif is_object_dtype(series) and series.map(lambda value: hasattr(value, "isoformat")).all():
        parsed = pd.to_datetime(series, utc=True, errors="coerce")
    else:
        numeric = pd.to_numeric(series, errors="coerce")
        if numeric.notna().all():
        # Datadog exports are commonly epoch ms; fall back to seconds for smaller values.
            unit = "ms" if float(numeric.abs().max()) > 1e11 else "s"
            parsed = pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
        else:
            parsed = pd.to_datetime(series, utc=True, errors="coerce")

    invalid = parsed.isna()
    if invalid.any():
        bad_rows = [int(i) + 2 for i in parsed[invalid].index[:5].tolist()]
        raise ValueError(f"Invalid timestamp values at CSV rows: {bad_rows}")
    return parsed


def _drop_infinite_values(dataframe: pd.DataFrame, config: InputConfig) -> tuple[pd.DataFrame, str | None]:
    """An infinite value was stored as Infinity and served back as null, with no finding or note;
    -inf was even reported as "negative". A CSV upload is the user's own file, so it's rejected with
    the rows to fix. Live sources (Prometheus, OTLP) can return +Inf legitimately - a histogram's
    top bucket, a division by zero - so those points are dropped with a warning instead of losing
    the whole series."""
    infinite = np.isinf(dataframe["value"].to_numpy(dtype=float))
    if not infinite.any():
        return dataframe, None
    if (config.source_type or "csv").lower() == "csv":
        bad_rows = [int(i) + 2 for i in dataframe.index[infinite][:5].tolist()]
        raise ValueError(f"Infinite values (inf or -inf) at CSV rows: {bad_rows}. Use a finite number, or leave the row out.")
    return dataframe[~infinite], f"Dropped {int(infinite.sum())} infinite value(s); they can't be analyzed."


def _parse_values(series: pd.Series) -> pd.Series:
    parsed = pd.to_numeric(series, errors="coerce")
    invalid = parsed.isna()
    if invalid.any():
        bad_rows = [int(i) + 2 for i in parsed[invalid].index[:5].tolist()]
        raise ValueError(f"Invalid numeric values at CSV rows: {bad_rows}")
    return parsed


def _parse_datadog_tag_string(value: object) -> dict[str, str]:
    if not isinstance(value, str) or not value.strip():
        return {}
    tags: dict[str, str] = {}
    for item in value.split(","):
        part = item.strip()
        if not part or ":" not in part:
            continue
        key, val = part.split(":", 1)
        key = key.strip()
        val = val.strip()
        if key and val:
            tags[key] = val
    return tags


def _apply_datadog_tags(dataframe: pd.DataFrame, config: InputConfig) -> None:
    provider = (config.provider or "generic").lower()
    if provider != "datadog" or "tags" not in dataframe.columns:
        return

    parsed = dataframe["tags"].apply(_parse_datadog_tag_string)
    dataframe["__provider_tags_json"] = parsed

    aliases = {
        "service": "service",
        "env": "env",
        "host": "host",
        "namespace": "namespace",
        "pod": "pod",
        "kube_namespace": "namespace",
        "pod_name": "pod",
    }

    for source_key, target_column in aliases.items():
        if target_column not in dataframe.columns:
            dataframe[target_column] = None
        inferred = parsed.apply(lambda item: item.get(source_key))
        dataframe[target_column] = dataframe[target_column].where(dataframe[target_column].notna(), inferred)


def _validate_rules(dataframe: pd.DataFrame, config: InputConfig) -> list[str]:
    rules = config.validation or {}
    warnings: list[str] = []

    if not bool(rules.get("allow_negative_values", True)):
        negatives = dataframe["value"] < 0
        if negatives.any():
            raise ValueError(f"Negative metric values are not allowed; found {int(negatives.sum())} rows")

    max_null_ratio = rules.get("max_null_ratio")
    if max_null_ratio is not None:
        ratio = float(max_null_ratio)
        for column in ["metric_name", "timestamp", "value"]:
            null_ratio = float(dataframe[column].isna().mean())
            if null_ratio > ratio:
                raise ValueError(
                    f"Column '{column}' null ratio {null_ratio:.3f} exceeds configured max_null_ratio {ratio:.3f}"
                )

    group_columns = [column for column in ["metric_name", "service", "host", "pod", "cluster"] if column in dataframe.columns]

    if bool(rules.get("enforce_monotonic_timestamp", False)):
        for keys, group in dataframe.groupby(group_columns, dropna=False):
            if not group["timestamp"].is_monotonic_increasing:
                raise ValueError(f"Timestamps are not monotonic within series group {keys}")

    max_gap_minutes = rules.get("max_gap_minutes")
    if max_gap_minutes is not None:
        limit = float(max_gap_minutes)
        gap_policy = str(rules.get("gap_policy") or "warn").lower()
        if gap_policy not in GAP_POLICIES:
            raise ValueError(f"Unknown gap_policy '{gap_policy}'; expected one of {sorted(GAP_POLICIES)}")
        for keys, group in dataframe.groupby(group_columns, dropna=False):
            timestamps = group.sort_values("timestamp")["timestamp"]
            if len(timestamps) < 2:
                continue
            max_gap = timestamps.diff().dt.total_seconds().dropna().max() / 60.0
            if max_gap > limit:
                message = f"Max timestamp gap {max_gap:.1f}m exceeds {limit:.1f}m for series group {keys}"
                if gap_policy == "reject":
                    raise ValueError(message)
                logger.warning("%s; keeping the series (gap_policy=warn)", message)
                warnings.append(message)

    return warnings
