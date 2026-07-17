from __future__ import annotations

import pandas as pd

from intelligence.config import InputConfig


CORE_COLUMNS = ["metric_name", "timestamp", "value", "service", "env", "host", "namespace", "pod", "source", "unit", "metric_type"]


def normalize_timeseries(dataframe: pd.DataFrame, config: InputConfig) -> pd.DataFrame:
    working = dataframe.copy()
    working = _apply_provider_mappings(working, config)
    working = _apply_core_renames(working, config)

    _validate_required_columns(working)
    _apply_datadog_tags(working, config)

    working["timestamp"] = _parse_timestamps(working["timestamp"], config.provider)
    working["value"] = _parse_values(working["value"])
    _validate_rules(working, config)

    for column in config.optional_columns:
        if column not in working.columns:
            working[column] = None

    if "service" in working.columns and config.service:
        working["service"] = working["service"].where(working["service"].notna(), config.service)
    if "metric_name" in working.columns and config.metric_name:
        working["metric_name"] = working["metric_name"].where(working["metric_name"].notna(), config.metric_name)
    if "source" in working.columns:
        provider = (config.provider or "generic").lower()
        working["source"] = working["source"].where(working["source"].notna(), provider)

    for column in ["metric_name", "service", "env", "host", "namespace", "pod", "source", "unit", "metric_type"]:
        if column in working.columns:
            working[column] = working[column].where(working[column].notna(), None)

    metadata_columns = [column for column in CORE_COLUMNS if column not in {"timestamp", "value"}]
    group_columns = [column for column in metadata_columns if column in working.columns]

    normalized_frames: list[pd.DataFrame] = []
    for keys, group in working.groupby(group_columns, dropna=False):
        group = group.sort_values("timestamp")
        freq_str = config.interval.replace('m', 'min') if config.interval.endswith('m') else config.interval
        resampled = (
            group.set_index("timestamp")
            .resample(freq_str)
            .mean(numeric_only=True)
            .reset_index()
        )

        if not isinstance(keys, tuple):
            keys = (keys,)

        for column, value in zip(group_columns, keys):
            resampled[column] = value

        normalized_frames.append(resampled)

    normalized = pd.concat(normalized_frames, ignore_index=True)
    normalized = normalized[CORE_COLUMNS].copy()

    tag_columns = [column for column in working.columns if column not in CORE_COLUMNS]
    tag_lookup = (
        working[[*CORE_COLUMNS, *tag_columns]]
        .drop_duplicates(subset=["metric_name", "timestamp", "service", "env", "host", "namespace", "pod", "source", "unit", "metric_type"])
        .set_index(["metric_name", "timestamp", "service", "env", "host", "namespace", "pod", "source", "unit", "metric_type"])
        if tag_columns
        else None
    )

    def build_tags(row: pd.Series) -> dict[str, object]:
        if tag_lookup is None:
            return {}
        key = tuple(row[column] for column in ["metric_name", "timestamp", "service", "env", "host", "namespace", "pod", "source", "unit", "metric_type"])
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
    return normalized


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


def _validate_required_columns(dataframe: pd.DataFrame) -> None:
    required = ["timestamp", "metric_name", "value"]
    missing = [column for column in required if column not in dataframe.columns]
    if missing:
        raise ValueError(f"CSV missing canonical required columns after mapping: {missing}")


def _parse_timestamps(series: pd.Series, provider: str) -> pd.Series:
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


def _validate_rules(dataframe: pd.DataFrame, config: InputConfig) -> None:
    rules = config.validation or {}

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

    group_columns = [column for column in ["metric_name", "service", "host", "pod"] if column in dataframe.columns]

    if bool(rules.get("enforce_monotonic_timestamp", False)):
        for keys, group in dataframe.groupby(group_columns, dropna=False):
            if not group["timestamp"].is_monotonic_increasing:
                raise ValueError(f"Timestamps are not monotonic within series group {keys}")

    max_gap_minutes = rules.get("max_gap_minutes")
    if max_gap_minutes is not None:
        limit = float(max_gap_minutes)
        for keys, group in dataframe.groupby(group_columns, dropna=False):
            timestamps = group.sort_values("timestamp")["timestamp"]
            if len(timestamps) < 2:
                continue
            max_gap = timestamps.diff().dt.total_seconds().dropna().max() / 60.0
            if max_gap > limit:
                raise ValueError(f"Max timestamp gap {max_gap:.1f}m exceeds {limit:.1f}m for series group {keys}")
