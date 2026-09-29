"""Score Ops Signals on the Server Machine Dataset: 28 real servers, 38 metrics each, 327 labeled
incidents with the metrics involved.

    .venv/bin/python -m benchmark.run_all --suites smd

Every machine runs with each method in benchmark/methods.py (see detector.py), in parallel worker
processes. Scoring (metrics.py) is per incident: caught or not, false alerts, and whether the alert
points at the metrics involved.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Any

from benchmark.methods import ALL_ANALYZERS, DESCRIPTIONS, LABELS, ROUTER_PICKS
from benchmark.router_benchmark import DEFAULT_ANALYZER_REGISTRY_DIR
from intelligence.analyzer_registry import load_registrations
from benchmark.smd import data, detector, metrics

PLOT_POINTS = 360


def run_smd_suite(raw_dir=None, *, workers: int | None = None, only: list[str] | None = None, skip: frozenset[str] = frozenset()) -> dict[str, Any]:
    dataset_dir = data.ensure_smd()
    names = [name for name in data.machine_names(dataset_dir) if not only or name in only]
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    methods = tuple(m for m in detector.METHODS if m not in skip)
    tasks = [(name, method) for method in methods for name in names]
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        outcomes = list(pool.map(detector.run_machine, [str(dataset_dir)] * len(tasks), *zip(*tasks)))
    wall_seconds = time.perf_counter() - started
    by_task = {(o["machine"], o["method"]): o for o in outcomes}

    overall = {method: {t: metrics.IncidentCounts() for t in metrics.THRESHOLDS} for method in methods}
    analyzer_ids = sorted(r.analyzer_id for r in load_registrations(DEFAULT_ANALYZER_REGISTRY_DIR) if r.enabled)
    analyzer_overall = {a: {t: metrics.IncidentCounts() for t in metrics.THRESHOLDS} for a in analyzer_ids}
    machines = []
    for name in names:
        machine = data.load_machine(dataset_dir, name)
        per_method = {}
        for method in methods:
            outcome = by_task[(name, method)]
            sweep = {}
            for threshold in metrics.THRESHOLDS:
                counts = metrics.score_machine(outcome["alarms"], machine.incidents, len(machine.test), threshold)
                overall[method][threshold].add(counts)
                sweep[str(threshold)] = counts.summary()
            headline = metrics.group_alerts(outcome["alarms"], metrics.HEADLINE_THRESHOLD)
            per_method[method] = {
                "headline": sweep[str(metrics.HEADLINE_THRESHOLD)],
                "sweep": sweep,
                "alerts": [[a.start, a.end, a.metrics, round(a.score, 3)] for a in headline],
                "seconds": outcome["seconds"],
                "analyzer_runs": outcome["analyzer_runs"],
                "errors": outcome["errors"],
                "first_error": outcome["first_error"],
                "analyzers_by_metric": outcome["analyzers_by_metric"],
            }
        everything = by_task.get((name, ALL_ANALYZERS))
        if everything:
            for analyzer in analyzer_ids:
                own = [alarm for alarm in everything["alarms"] if alarm[3] == analyzer]
                for threshold in metrics.THRESHOLDS:
                    analyzer_overall[analyzer][threshold].add(metrics.score_machine(own, machine.incidents, len(machine.test), threshold))
        router = by_task.get((name, ROUTER_PICKS))
        incident_choices = _router_choices(machine, everything, router)
        machines.append(
            {
                "machine": name,
                "router_choices": incident_choices,
                "train_rows": len(machine.train),
                "test_rows": len(machine.test),
                "incidents": [[i.start, i.end, i.metrics] for i in machine.incidents],
                "interpretation_ranges": machine.interpretation_ranges,
                "label_discrepancy": machine.label_discrepancy,
                "methods": per_method,
                "plot": _plot(machine),
            }
        )

    summaries = {method: {str(t): counts.summary() for t, counts in by_t.items()} for method, by_t in overall.items()}
    return {
        "smd": {"repository": data.SMD_REPOSITORY, "commit": data.SMD_COMMIT, "machines": len(names), "metrics_per_machine": data.METRIC_COUNT},
        "settings": {
            "methods": list(methods),
            "thresholds": list(metrics.THRESHOLDS),
            "headline_threshold": metrics.HEADLINE_THRESHOLD,
            "alert_gap_minutes": metrics.ALERT_GAP_ROWS,
            "hit_rates": [f"{int(p * 100)}" for p in metrics.HIT_RATES],
            "whole_series_fraction": detector.WHOLE_SERIES_FRACTION,
            "mode": "batch",
        },
        "workers": workers,
        "wall_seconds_total": round(wall_seconds, 1),
        "overall": summaries,
        "comparison": {
            method: {
                "label": LABELS[method],
                "description": DESCRIPTIONS[method],
                "overall": summaries[method],
                "cost": {
                    "seconds": round(sum(by_task[(n, method)]["seconds"] for n in names), 3),
                    "analyzer_runs": sum(by_task[(n, method)]["analyzer_runs"] for n in names),
                    "errors": sum(by_task[(n, method)]["errors"] for n in names),
                },
            }
            for method in methods
        },
        "analyzers": (
            {analyzer: {str(t): counts.summary() for t, counts in by_t.items()} for analyzer, by_t in analyzer_overall.items()}
            if ALL_ANALYZERS in methods else {}
        ),
        "label_discrepancies": [m["machine"] for m in machines if m["label_discrepancy"]],
        "machines": machines,
        "product": ROUTER_PICKS,
    }


def _router_choices(machine: data.SmdMachine, everything: dict[str, Any] | None, router: dict[str, Any] | None) -> list[dict[str, Any]]:
    """For each incident: the analyzers that, on their own, raised an alarm inside it (with the
    metrics they alarmed on), whether the router ran one of them on one of those metrics, and
    whether router picks caught the incident."""
    if not everything or not router:
        return []
    threshold = metrics.HEADLINE_THRESHOLD
    router_alerts = metrics.group_alerts(router["alarms"], threshold)
    choices = []
    for incident in machine.incidents:
        capable: dict[str, set[int]] = {}
        for row, metric, score, analyzer in everything["alarms"]:
            if score >= threshold and incident.start <= row <= incident.end:
                capable.setdefault(analyzer, set()).add(metric)
        hit = any(
            analyzer in (router["analyzers_by_metric"].get(data.metric_name(metric)) or [])
            for analyzer, metrics_hit in capable.items()
            for metric in metrics_hit
        )
        choices.append(
            {
                "rows": [incident.start, incident.end],
                "capable": sorted(capable),
                "router_ran_capable": hit if capable else None,
                "router_caught": any(incident.start <= alert.start <= incident.end for alert in router_alerts),
            }
        )
    return choices


def _plot(machine: data.SmdMachine) -> list[list[float]]:
    """The test half's mean across all 38 metrics, bucketed - enough to see where incidents sit."""
    values = machine.test.mean(axis=1)
    bucket = max(1, -(-len(values) // PLOT_POINTS))
    return [[start, round(float(values[start : start + bucket].mean()), 5)] for start in range(0, len(values), bucket)]
