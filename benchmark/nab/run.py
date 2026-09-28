"""Run the whole NAB corpus through the production analysis path and score it.

    .venv/bin/python -m benchmark.run_all --suites nab

Writes NAB-format result files - one CSV per series with timestamp, value, anomaly_score and
label - under <snapshot>/raw/nab_results/<detector>/<category>/<detector>_<file>.csv, the layout
NAB's own scorer reads from its results/ directory. The metrics reported here are this harness's
window metrics (benchmark/nab/metrics.py); the official NAB score comes from running NAB's scorer
on those files.
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from benchmark.methods import ALL_ANALYZERS, DESCRIPTIONS, LABELS, ROUTER_PICKS, STATIC_THRESHOLD, ZSCORE_ONLY
from benchmark.router_benchmark import DEFAULT_ANALYZER_REGISTRY_DIR
from intelligence.analyzer_registry import load_registrations
from benchmark.nab import detector, metrics
from benchmark.nab.fetch import NAB_COMMIT, NAB_REPOSITORY, ensure_nab

DETECTOR_NAMES = {"replay": "opsSignalsReplay", "batch": "opsSignalsBatch"}
# NAB-format detector names for the replay-mode baselines, so NAB's scorer can grade them too.
BASELINE_DETECTOR_NAMES = {
    ALL_ANALYZERS: "opsSignalsAllAnalyzers",
    ZSCORE_ONLY: "zscoreOnly",
    STATIC_THRESHOLD: "staticThreshold",
}
MODES = ("replay", "batch")
SERIES_POINTS = 360


def run_nab_suite(raw_dir: Path, *, workers: int | None = None, only: list[str] | None = None, skip: frozenset[str] = frozenset()) -> dict[str, Any]:
    nab_dir = ensure_nab()
    windows = json.loads((nab_dir / "labels" / "combined_windows.json").read_text(encoding="utf-8"))
    series_names = sorted(name for name in windows if not only or name in only)
    workers = workers or max(1, (os.cpu_count() or 2) - 1)

    # Longest series first: replay cost grows with row count, and a big series picked up last
    # would run alone while every other worker sits idle.
    by_size = sorted(series_names, key=lambda name: -(nab_dir / "data" / name).stat().st_size)
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        finished = dict(zip(by_size, pool.map(detector.run_series, [nab_dir / "data" / name for name in by_size], by_size, [frozenset(skip)] * len(by_size))))
    runs = [finished[name] for name in series_names]
    wall_seconds = time.perf_counter() - started

    results_dir = raw_dir / "nab_results"
    overall = {mode: {threshold: metrics.WindowCounts() for threshold in metrics.THRESHOLDS} for mode in MODES}
    baseline_overall = {method: {threshold: metrics.WindowCounts() for threshold in metrics.THRESHOLDS} for method in detector.BASELINES if method not in skip}
    analyzer_ids = sorted(r.analyzer_id for r in load_registrations(DEFAULT_ANALYZER_REGISTRY_DIR) if r.enabled)
    analyzer_overall = {a: {threshold: metrics.WindowCounts() for threshold in metrics.THRESHOLDS} for a in analyzer_ids}
    categories: dict[str, dict[str, metrics.WindowCounts]] = {}
    series_payload = []
    for run in runs:
        frame = detector.load_series(nab_dir / "data" / run.series)
        timestamps = frame["timestamp"].dt.tz_convert(None).to_numpy()
        rows = metrics.window_rows(timestamps, windows[run.series])
        labels = np.zeros(len(frame), dtype=int)
        for start, end in rows:
            labels[start : end + 1] = 1
        category = run.series.split("/")[0]

        per_mode: dict[str, Any] = {}
        for mode in MODES:
            scores = run.replay_scores if mode == "replay" else run.batch_scores
            _write_nab_file(results_dir, DETECTOR_NAMES[mode], run.series, frame, scores, labels)
            sweep = {}
            for threshold in metrics.THRESHOLDS:
                counts = metrics.score_series(scores, rows, threshold)
                overall[mode][threshold].add(counts)
                sweep[str(threshold)] = counts.summary()
            headline = metrics.score_series(scores, rows, metrics.HEADLINE_THRESHOLD)
            categories.setdefault(category, {m: metrics.WindowCounts() for m in MODES})[mode].add(headline)
            per_mode[mode] = {
                "headline": headline.summary(),
                "sweep": sweep,
                "alarm_times": _alarm_times(frame, scores),
            }

        per_baseline: dict[str, Any] = {}
        for method, method_run in run.baselines.items():
            _write_nab_file(results_dir, BASELINE_DETECTOR_NAMES[method], run.series, frame, method_run.scores, labels)
            for threshold in metrics.THRESHOLDS:
                baseline_overall[method][threshold].add(metrics.score_series(method_run.scores, rows, threshold))
            per_baseline[method] = {
                "headline": metrics.score_series(method_run.scores, rows, metrics.HEADLINE_THRESHOLD).summary(),
                "seconds": method_run.seconds,
                "runs": method_run.runs,
                "analyzer_runs": method_run.analyzer_runs,
                "errors": method_run.errors,
                "first_error": method_run.first_error,
            }

        by_analyzer = run.baselines[ALL_ANALYZERS].scores_by_analyzer if ALL_ANALYZERS in run.baselines else {}
        for analyzer in analyzer_ids:
            analyzer_scores = by_analyzer.get(analyzer) or [0.0] * len(frame)
            for threshold in metrics.THRESHOLDS:
                analyzer_overall[analyzer][threshold].add(metrics.score_series(analyzer_scores, rows, threshold))
        windows_detail = _router_choices(run, rows, len(frame), by_analyzer)

        record = asdict(run)
        record.pop("batch_scores")
        record.pop("replay_scores")
        record.pop("baselines")
        record.pop("replay_executed_by_run")
        series_payload.append(
            {
                **record,
                "category": category,
                "windows": windows[run.series],
                "probation_rows": metrics.probation_rows(len(frame)),
                "probation_end": _iso(frame["timestamp"].iloc[min(metrics.probation_rows(len(frame)), len(frame) - 1)]),
                "modes": per_mode,
                "baselines": per_baseline,
                "windows_detail": windows_detail,
                "plot": _plot_points(frame),
            }
        )

    return {
        "nab": {"repository": NAB_REPOSITORY, "commit": NAB_COMMIT},
        "settings": {
            "provider": detector.PROVIDER,
            "replay_step_rows": detector.REPLAY_STEP,
            "replay_window_rows": detector.REPLAY_WINDOW,
            "replay_new_event_horizon_rows": detector.REPLAY_NEW_EVENT_HORIZON,
            "replay_min_history_rows": detector.REPLAY_MIN_HISTORY,
            "thresholds": list(metrics.THRESHOLDS),
            "headline_threshold": metrics.HEADLINE_THRESHOLD,
            "probationary_percent": metrics.PROBATIONARY_PERCENT,
            "workers": workers,
        },
        "detector_names": DETECTOR_NAMES,
        "baseline_detector_names": BASELINE_DETECTOR_NAMES,
        "comparison": _comparison(runs, overall["replay"], baseline_overall),
        "analyzers": {
            analyzer: {str(threshold): counts.summary() for threshold, counts in by_threshold.items()}
            for analyzer, by_threshold in analyzer_overall.items()
        } if ALL_ANALYZERS not in skip else {},
        "nab_format_dir": str(results_dir),
        "wall_seconds_total": round(wall_seconds, 1),
        "overall": {
            mode: {str(threshold): counts.summary() for threshold, counts in by_threshold.items()}
            for mode, by_threshold in overall.items()
        },
        "categories": {
            category: {mode: counts.summary() for mode, counts in by_mode.items()}
            for category, by_mode in sorted(categories.items())
        },
        "series": series_payload,
        "series_with_errors": [
            item["series"] for item in series_payload if item["batch_error"] or item["replay_errors"]
        ],
    }


def _router_choices(run, rows: list[tuple[int, int]], length: int, by_analyzer: dict[str, list[float]]) -> list[dict[str, Any]]:
    """For each labeled window: which analyzers, each on its own, alarmed inside it at the headline
    threshold ("capable"), which analyzers the router ran on the scheduled runs whose last row falls
    inside it, and whether the router caught it."""
    threshold = metrics.HEADLINE_THRESHOLD
    probation = metrics.probation_rows(length)
    router_scores = np.asarray(run.replay_scores, dtype=float)
    detail = []
    for start, end in rows:
        first = max(start, probation)
        capable = sorted(
            analyzer for analyzer, scores in by_analyzer.items()
            if first <= end and np.any(np.asarray(scores[first : end + 1], dtype=float) >= threshold)
        )
        ran = sorted({a for row, analyzers in run.replay_executed_by_run.items() if start <= row <= end for a in analyzers})
        caught = bool(first <= end and np.any(router_scores[first : end + 1] >= threshold))
        detail.append({"rows": [start, end], "capable": capable, "router_ran": ran, "router_caught": caught})
    return detail


def _comparison(runs, router_overall, baseline_overall) -> dict[str, Any]:
    """Every method in replay mode, side by side: accuracy at every threshold, and what it cost -
    replay seconds and analyzer executions summed over every series and scheduled run."""
    router_cost = {
        "seconds": round(sum(run.replay_seconds for run in runs), 3),
        "runs": sum(run.replay_runs for run in runs),
        "analyzer_runs": sum(run.replay_analyzer_runs for run in runs),
        "errors": sum(run.replay_errors for run in runs),
    }
    methods = {ROUTER_PICKS: (router_overall, router_cost, DETECTOR_NAMES["replay"])}
    for method, by_threshold in baseline_overall.items():
        cost = {
            "seconds": round(sum(run.baselines[method].seconds for run in runs), 3),
            "runs": sum(run.baselines[method].runs for run in runs),
            "analyzer_runs": sum(run.baselines[method].analyzer_runs for run in runs),
            "errors": sum(run.baselines[method].errors for run in runs),
        }
        methods[method] = (by_threshold, cost, BASELINE_DETECTOR_NAMES[method])
    return {
        method: {
            "label": LABELS[method],
            "description": DESCRIPTIONS[method],
            "detector_name": detector_name,
            "overall": {str(threshold): (counts.summary() if isinstance(counts, metrics.WindowCounts) else counts) for threshold, counts in by_threshold.items()},
            "cost": cost,
        }
        for method, (by_threshold, cost, detector_name) in methods.items()
    }


def _write_nab_file(results_dir: Path, detector_name: str, series: str, frame: pd.DataFrame, scores: list[float], labels: np.ndarray) -> None:
    category, filename = series.split("/")
    path = results_dir / detector_name / category / f"{detector_name}_{filename}"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "timestamp": frame["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S"),
            "value": frame["value"],
            "anomaly_score": scores,
            "label": labels,
        }
    ).to_csv(path, index=False)


def _alarm_times(frame: pd.DataFrame, scores: list[float]) -> list[list[Any]]:
    values = np.asarray(scores)
    rows = np.nonzero(values >= metrics.THRESHOLDS[0])[0]
    return [[_iso(frame["timestamp"].iloc[row]), round(float(values[row]), 3)] for row in rows]


def _plot_points(frame: pd.DataFrame) -> list[list[Any]]:
    bucket = max(1, -(-len(frame) // SERIES_POINTS))
    grouped = frame.groupby(frame.index // bucket).agg(timestamp=("timestamp", "first"), value=("value", "mean"))
    return [[_iso(row.timestamp), round(float(row.value), 4)] for row in grouped.itertuples()]


def _iso(value) -> str:
    return pd.Timestamp(value).isoformat()
