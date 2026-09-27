"""Score Ops Signals on the UCR Time Series Anomaly Archive: 250 series, one anomaly each.

    .venv/bin/python -m benchmark.run_all --suites ucr

Every method gives one location per series (see detector.py), scored with the archive's own rule
(metrics.py). Accuracy is the share of the 250 series answered correctly.

Each (series, method) pair runs in a worker process with a time limit. A run that doesn't finish
in time, or fails, is recorded as such and scores as no answer - what a user waiting on the
product would get. Workers are single-threaded for numba so parallel runs don't compete for cores.
"""

from __future__ import annotations

import multiprocessing
import os
import time
from multiprocessing.connection import wait
from pathlib import Path
from typing import Any

import numpy as np

from benchmark.ucr import data, metrics

TASK_TIMEOUT_SECONDS = 600
OVERVIEW_POINTS = 200
ZOOM_POINTS = 240


def run_ucr_suite(raw_dir: Path | None = None, *, workers: int | None = None, only: list[int] | None = None,
                  timeout: float = TASK_TIMEOUT_SECONDS) -> dict[str, Any]:
    from benchmark.ucr.detector import DIRECT_ANALYZERS, DISCORD, MAX_JUMP, METHODS, PRODUCT, WHOLE_SERIES_FRACTION

    series_dir = data.ensure_ucr()
    paths = [path for path in data.series_files(series_dir) if not only or int(path.name.split("_", 1)[0]) in only]
    workers = workers or max(1, (os.cpu_count() or 2) - 1)

    # Biggest series first, so a long run doesn't start last while the other workers sit idle.
    tasks = [(str(path), method) for path in sorted(paths, key=lambda p: -p.stat().st_size) for method in METHODS]
    started = time.perf_counter()
    outcomes = run_tasks(tasks, workers=workers, timeout=timeout)
    wall_seconds = time.perf_counter() - started

    rows = []
    for path in paths:
        series = data.load_series(path)
        methods = {}
        for method in METHODS:
            outcome = dict(outcomes[(str(path), method)])
            methods[method] = _score(outcome, series)
        rows.append(
            {
                "number": series.number,
                "file": series.file,
                "name": series.name,
                "source": series.source,
                "variant": series.variant,
                "domain": series.domain,
                "n_points": len(series.values),
                "train_end": series.train_end,
                "begin": series.begin,
                "end": series.end,
                "correct_region": list(metrics.correct_region(series.begin, series.end)),
                "default_rate": round(metrics.default_rate(len(series.values), series.train_end, series.begin, series.end), 6),
                "methods": methods,
                "plot": _overview(series),
                "zoom": _zoom(series),
            }
        )

    return {
        "archive": {"url": data.ARCHIVE_URL, "sha256": data.ARCHIVE_SHA256, "series": len(rows)},
        "settings": {
            "methods": list(METHODS),
            "product": PRODUCT,
            "direct_analyzers": list(DIRECT_ANALYZERS),
            "reference": DISCORD,
            "baseline": MAX_JUMP,
            "min_slack": metrics.MIN_SLACK,
            "whole_series_fraction": WHOLE_SERIES_FRACTION,
            "task_timeout_seconds": timeout,
        },
        "workers": workers,
        "wall_seconds_total": round(wall_seconds, 1),
        "summary": summarize(rows, METHODS),
        "series": rows,
    }


def summarize(rows: list[dict[str, Any]], methods) -> dict[str, Any]:
    def accuracy(group: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            method: {
                "correct": sum(1 for row in group if row["methods"][method]["correct"]),
                "answered": sum(1 for row in group if row["methods"][method]["row"] is not None),
                "timeouts": sum(1 for row in group if row["methods"][method]["status"] == "timeout"),
                "errors": sum(1 for row in group if row["methods"][method]["status"] == "error"),
                "found_anywhere": sum(1 for row in group if row["methods"][method].get("hit_rank")),
            }
            for method in methods
        } | {"series": len(group), "default_rate": round(float(np.mean([row["default_rate"] for row in group])), 6) if group else 0.0}

    def grouped(key: str) -> dict[str, Any]:
        return {value: accuracy([row for row in rows if row[key] == value]) for value in sorted({row[key] for row in rows})}

    return {"overall": accuracy(rows), "by_domain": grouped("domain"), "by_variant": grouped("variant")}


def _score(outcome: dict[str, Any], series: data.UcrSeries) -> dict[str, Any]:
    row = outcome.get("row")
    position = None if row is None else int(row) + 1
    candidate_rows = outcome.pop("candidate_rows", None)
    if outcome.get("status") is None:
        outcome["status"] = "error" if outcome.get("error") else ("answered" if row is not None else "no_answer")
    outcome["position"] = position
    outcome["correct"] = metrics.is_correct(position, series.begin, series.end)
    if candidate_rows is not None:
        outcome["candidates_after_train"] = len(candidate_rows)
        outcome["hit_rank"] = next(
            (rank for rank, candidate in enumerate(candidate_rows, 1) if metrics.is_correct(candidate + 1, series.begin, series.end)),
            None,
        )
    return outcome


# --- worker pool with per-task time limits ---------------------------------------------------


def run_tasks(tasks: list[tuple[str, str]], *, workers: int, timeout: float) -> dict[tuple[str, str], dict[str, Any]]:
    """Run (path, method) tasks in worker processes; a task over `timeout` seconds is killed and
    recorded as a timeout, and its worker replaced."""
    context = multiprocessing.get_context("spawn")
    os.environ["NUMBA_NUM_THREADS"] = "1"
    pending = list(reversed(tasks))
    results: dict[tuple[str, str], dict[str, Any]] = {}
    active: dict[Any, dict[str, Any]] = {}

    def start_worker():
        parent, child = context.Pipe()
        process = context.Process(target=_worker, args=(child,), daemon=True)
        process.start()
        child.close()
        active[parent] = {"process": process, "task": None, "deadline": None}
        return parent

    def assign(conn) -> None:
        slot = active[conn]
        if pending:
            task = pending.pop()
            slot["task"], slot["deadline"] = task, time.monotonic() + timeout
            conn.send(task)
        else:
            conn.send(None)
            slot["process"].join(timeout=5)
            del active[conn]

    for _ in range(min(workers, len(tasks))):
        assign(start_worker())

    while active:
        soonest = min(slot["deadline"] for slot in active.values())
        for conn in wait(list(active), timeout=max(0.0, soonest - time.monotonic())):
            slot = active[conn]
            try:
                results[slot["task"]] = conn.recv()
            except EOFError:
                results[slot["task"]] = {"method": slot["task"][1], "row": None, "status": "error", "error": "worker process died"}
                del active[conn]
                if pending:
                    assign(start_worker())
                continue
            assign(conn)
        now = time.monotonic()
        for conn, slot in list(active.items()):
            if slot["deadline"] is not None and now > slot["deadline"]:
                slot["process"].kill()
                slot["process"].join()
                results[slot["task"]] = {
                    "method": slot["task"][1],
                    "row": None,
                    "status": "timeout",
                    "error": f"did not finish within {timeout:.0f} s",
                    "seconds": timeout,
                }
                del active[conn]
                if pending:
                    assign(start_worker())
    return results


def _worker(conn) -> None:
    from benchmark.ucr.detector import run_method

    while True:
        task = conn.recv()
        if task is None:
            return
        conn.send(run_method(*task))


# --- plot data -------------------------------------------------------------------------------


def _overview(series: data.UcrSeries) -> list[list[Any]]:
    return _bucketed(series.values, 0, len(series.values), OVERVIEW_POINTS)


def _zoom(series: data.UcrSeries) -> dict[str, Any]:
    """The labeled anomaly with context on both sides, in 0-based rows."""
    low, high = metrics.correct_region(series.begin, series.end)
    length = series.end - series.begin + 1
    context = max(3 * length, 300)
    first = max(0, min(low, series.begin - context) - 1)
    last = min(len(series.values), max(high, series.end + context))
    return {"first_row": first, "last_row": last - 1, "points": _bucketed(series.values, first, last, ZOOM_POINTS)}


def _bucketed(values: np.ndarray, first: int, last: int, points: int) -> list[list[Any]]:
    """[row, mean, min, max] per bucket - min and max keep one-point spikes visible."""
    bucket = max(1, -(-(last - first) // points))
    out = []
    for start in range(first, last, bucket):
        chunk = values[start : min(start + bucket, last)]
        out.append([start, round(float(chunk.mean()), 6), round(float(chunk.min()), 6), round(float(chunk.max()), 6)])
    return out
