from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
import uuid
from pathlib import Path
from time import perf_counter

import pandas as pd

from .config import ExperimentConfig, as_dict
from .inspection import infer_columns, inspect_dataset, pretty_print_inspection
from .labels import compare_with_labels, load_labels
from .normalization import explain_normalization, normalize_signal
from .plotting import save_change_point_plot, save_comparison_plot, save_raw_plot
from .quality import validate_data
from .report import build_report, save_report
from .ruptures_runner import run_ruptures


def _load_dataframe(csv_path: str) -> pd.DataFrame:
    return pd.read_csv(csv_path)


def _dataset_name(csv_path: str) -> str:
    return Path(csv_path).stem


def _sampling_interval_seconds(inspection) -> int | None:
    try:
        value = pd.to_timedelta(inspection.sampling_interval)
        return int(value.total_seconds())
    except Exception:
        return None


def _build_plain_language_summary(dataset_name: str, event_count: int, events: list[dict[str, object]]) -> str:
    if not events:
        return f"The analyzer did not find a meaningful change in {dataset_name}."
    first = events[0]
    direction = "increased" if float(first.get("details", {}).get("percentage_change", 0) or 0) >= 0 else "decreased"
    return (
        f"The analyzer found {event_count} meaningful changes in {dataset_name}. "
        f"The most important change happened around {first.get('timestamp')}, when the metric {direction} to a new operating level. "
        "Some of the later changes may represent related stages of the same operational event."
    )


def _build_event_summary(event: dict[str, object]) -> str:
    details = event.get("details", {}) if isinstance(event.get("details"), dict) else {}
    pct = float(details.get("percentage_change", 0) or 0)
    before = details.get("mean_before")
    after = details.get("mean_after")
    if pct >= 0:
        return (
            f"{event.get('event_type', 'change point').replace('_', ' ').title()} detected. "
            f"The metric moved from about {before} to {after}, an increase of roughly {abs(pct):.1f}%."
        )
    return (
        f"{event.get('event_type', 'change point').replace('_', ' ').title()} detected. "
        f"The metric moved from about {before} to {after}, a decrease of roughly {abs(pct):.1f}%."
    )


def run_experiment(config: ExperimentConfig) -> dict[str, object]:
    created_at = datetime.now(timezone.utc)
    experiment_id = str(uuid.uuid4())
    dataframe = _load_dataframe(config.dataset.csv_path)
    timestamp_column, value_column = infer_columns(dataframe, config.dataset.timestamp_column, config.dataset.value_column)

    inspection = inspect_dataset(dataframe, timestamp_column, value_column)
    quality = validate_data(dataframe, timestamp_column, value_column)

    plots_dir = Path(config.output.plots_dir)
    reports_dir = Path(config.output.reports_dir)

    raw_plot = save_raw_plot(dataframe, timestamp_column, value_column, plots_dir / f"{_dataset_name(config.dataset.csv_path)}_raw.png", f"Raw signal: {_dataset_name(config.dataset.csv_path)}")

    normalized = normalize_signal(dataframe[value_column], config.normalization.method)
    working = dataframe.copy()
    working[value_column] = normalized

    start = perf_counter()
    result = run_ruptures(
        working[value_column],
        config.ruptures.algorithm,
        config.ruptures.model,
        config.ruptures.penalty,
        config.ruptures.min_size,
        config.ruptures.jump,
    )
    execution_seconds = perf_counter() - start

    change_plot = save_change_point_plot(
        dataframe,
        timestamp_column,
        value_column,
        result.change_points,
        plots_dir / f"{_dataset_name(config.dataset.csv_path)}_change_points.png",
        f"Change points: {_dataset_name(config.dataset.csv_path)}",
    )

    comparison_plots = []
    for penalty in config.experiments.penalties:
        tuned = run_ruptures(working[value_column], config.ruptures.algorithm, config.ruptures.model, penalty, config.ruptures.min_size, config.ruptures.jump)
        comparison_plots.append((f"penalty={penalty}", dataframe, tuned.change_points))
    comparison_plot = save_comparison_plot(
        comparison_plots,
        timestamp_column,
        value_column,
        plots_dir / f"{_dataset_name(config.dataset.csv_path)}_comparison.png",
        f"Penalty comparison: {_dataset_name(config.dataset.csv_path)}",
    )

    label_windows = load_labels(
        dataframe,
        timestamp_column,
        config.dataset.label_column,
        config.dataset.anomaly_start_column,
        config.dataset.anomaly_end_column,
    )
    comparison = compare_with_labels(dataframe, timestamp_column, result.change_points, label_windows) if label_windows else None

    raw_events: list[dict[str, object]] = []
    timestamps = pd.to_datetime(dataframe[timestamp_column], utc=True, errors="coerce").reset_index(drop=True)
    values = pd.to_numeric(dataframe[value_column], errors="coerce").reset_index(drop=True)
    for point in result.change_points[:-1]:
        if 0 <= point < len(timestamps):
            before = values.iloc[max(0, point - config.ruptures.min_size):point]
            after = values.iloc[point:min(len(values), point + config.ruptures.min_size)]
            mean_before = float(before.mean()) if not before.empty else None
            mean_after = float(after.mean()) if not after.empty else None
            pct_change = ((mean_after - mean_before) / abs(mean_before) * 100.0) if mean_before not in (None, 0) and mean_after is not None else None
            event = {
                "event_id": str(uuid.uuid4()),
                "event_type": "change_point",
                "index": int(point),
                "timestamp": timestamps.iloc[point].isoformat() if pd.notna(timestamps.iloc[point]) else None,
                "value": float(values.iloc[point]) if pd.notna(values.iloc[point]) else None,
                "severity": "major" if pct_change is not None and abs(pct_change) > 50 else "significant" if pct_change is not None and abs(pct_change) > 25 else "noticeable" if pct_change is not None and abs(pct_change) > 10 else "minor",
                "score": None,
                "window_start": timestamps.iloc[max(0, point - config.ruptures.min_size)].isoformat() if pd.notna(timestamps.iloc[max(0, point - config.ruptures.min_size)]) else None,
                "window_end": timestamps.iloc[min(len(timestamps) - 1, point + config.ruptures.min_size - 1)].isoformat() if pd.notna(timestamps.iloc[min(len(timestamps) - 1, point + config.ruptures.min_size - 1)]) else None,
                "details": {
                    "mean_before": round(mean_before, 4) if mean_before is not None else None,
                    "mean_after": round(mean_after, 4) if mean_after is not None else None,
                    "absolute_change": round((mean_after - mean_before), 4) if mean_before is not None and mean_after is not None else None,
                    "percentage_change": round(pct_change, 4) if pct_change is not None else None,
                },
                "interpretation": None,
                "technical_summary": f"index={point}, model={config.ruptures.model}, algorithm={config.ruptures.algorithm}, penalty={config.ruptures.penalty}",
            }
            event["interpretation"] = _build_event_summary(event)
            raw_events.append(event)

    event_count = len(raw_events)
    plain_language_summary = _build_plain_language_summary(_dataset_name(config.dataset.csv_path), event_count, raw_events)

    observations = [
        f"Normalization strategy: {config.normalization.method}",
        f"Ruptures returned {len(result.change_points) - 1} internal change points.",
        "Penalty increases usually reduce the number of detected change points and favor broader, more stable shifts.",
        "Penalty decreases usually increase sensitivity, which can reveal smaller regime changes but also more false positives.",
        "Use l2 when baseline mean shifts matter most, rbf when shape/nonlinear distribution changes matter, and normal when variance changes matter too.",
        "Use PELT when you want a scalable penalized search, Binary Segmentation for quick iterative splits, and Bottom Up when you want merge-based segmentation over many small pieces.",
    ]
    if quality.issues:
        observations.insert(0, "Data quality issues were found and should be reviewed before treating the output as definitive.")

    recommended = (
        f"- Dataset: {_dataset_name(config.dataset.csv_path)}\n"
        f"- Algorithm: {config.ruptures.algorithm}\n"
        f"- Model: {config.ruptures.model}\n"
        f"- Penalty: {config.ruptures.penalty}\n"
        f"- Suitable for: operational metrics with repeatable regime changes such as CPU, latency, request rate, memory, and network throughput\n"
        f"- Not suitable for: highly irregular series, sparse event logs, or signals with severe missingness without preprocessing"
    )

    report_text = build_report(
        dataset_name=_dataset_name(config.dataset.csv_path),
        inspection=inspection,
        quality_report=quality,
        ruptures_config=config.ruptures,
        normalization_explanation=explain_normalization(config.normalization.method),
        execution_seconds=execution_seconds,
        change_points=result.change_points,
        plot_paths={"raw": str(raw_plot), "change_points": str(change_plot), "comparison": str(comparison_plot)},
        label_comparison=comparison,
        observations=observations,
        recommended_configuration=recommended,
    )

    report_path = save_report(report_text, reports_dir / f"{_dataset_name(config.dataset.csv_path)}_ruptures_report.md")

    results_dir = Path("experiments/ruptures/results")
    results_dir.mkdir(parents=True, exist_ok=True)
    result_payload = {
        "experiment_id": experiment_id,
        "dataset": {
            "name": _dataset_name(config.dataset.csv_path),
            "file_path": config.dataset.csv_path,
            "rows": inspection.rows,
            "columns": inspection.columns,
            "timestamp_column": inspection.timestamp_column,
            "value_column": inspection.value_column,
            "sampling_interval_seconds": _sampling_interval_seconds(inspection),
            "start_time": timestamps.min().isoformat() if pd.notna(timestamps.min()) else None,
            "end_time": timestamps.max().isoformat() if pd.notna(timestamps.max()) else None,
            "min_value": float(values.min()),
            "max_value": float(values.max()),
            "missing_values": inspection.missing_values,
            "duplicate_timestamps": inspection.duplicate_timestamps,
            "timestamps_sorted": inspection.timestamps_sorted,
        },
        "analyzer": {
            "name": "ruptures",
            "algorithm": config.ruptures.algorithm,
            "model": config.ruptures.model,
            "parameters": {
                "penalty": config.ruptures.penalty,
                "min_size": config.ruptures.min_size,
                "jump": config.ruptures.jump,
            },
        },
        "preprocessing": {"normalization": config.normalization.method},
        "execution": {
            "status": "completed",
            "started_at": created_at.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "execution_time_seconds": execution_seconds,
        },
        "results": {
            "event_type": "change_point",
            "event_count": event_count,
            "events": raw_events,
        },
        "metrics": {
            "precision": getattr(comparison, "precision", None),
            "recall": getattr(comparison, "recall", None),
            "f1_score": getattr(comparison, "f1", None),
        },
        "artifacts": {
            "raw_plot": str(raw_plot),
            "result_plot": str(change_plot),
            "comparison_plot": str(comparison_plot),
        },
        "observations": observations,
        "recommendation": {
            "title": "Baseline settings for CPU-style operational metrics",
            "summary": "Start with PELT + l2 + moderate penalty and compare lower/higher penalties for sensitivity.",
            "recommended_configuration": recommended,
            "suitable_for": ["CPU", "latency", "request rate", "memory", "network throughput"],
            "not_suitable_for": ["irregular event logs", "highly missing series", "unvalidated sparse samples"],
            "limitations": ["No root-cause confirmation", "Labels may be absent", "Short windows can overfit"],
        },
        "created_at": created_at.isoformat(),
        "plain_language_summary": plain_language_summary,
        "event_summaries": [e["interpretation"] for e in raw_events],
    }
    (results_dir / f"{experiment_id}.json").write_text(json.dumps(result_payload, indent=2))

    print(pretty_print_inspection(inspection))
    if quality.issues:
        print("\nData quality issues:")
        for issue in quality.issues:
            print(f"- {issue}")
    print("\nNormalization:")
    print(explain_normalization(config.normalization.method))
    print("\nDetected change points:", result.change_points)
    if comparison:
        print("\nLabel comparison:")
        print(f"Precision: {comparison.precision}")
        print(f"Recall: {comparison.recall}")
        print(f"F1: {comparison.f1}")
    print(f"\nExperiment ID: {experiment_id}")
    print(f"Structured JSON written to: {results_dir / f'{experiment_id}.json'}")
    print(f"Report written to: {report_path}")

    return {
        "experiment_id": experiment_id,
        "inspection": inspection,
        "quality": quality,
        "result": result,
        "comparison": comparison,
        "report_path": str(report_path),
        "plots": {"raw": str(raw_plot), "change_points": str(change_plot), "comparison": str(comparison_plot)},
        "execution_seconds": execution_seconds,
    }
