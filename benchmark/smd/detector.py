"""Run each method on one SMD machine's 38 metrics and turn what it finds into alarms in the test half.

Each metric is its own series, the way Ops Signals monitors a server: train and test halves joined,
with a synthetic one-minute timestamp per row, through the production pipeline (generic provider).
Analyzers see the whole series at once - batch mode, like a published method scored offline on the
test half. Replaying it causally, as the NAB suite does, would mean hundreds of thousands of pipeline
runs; this is stated in the report.

Only signals a user would see count: those that became part of a finding (harness.user_facing_signals).
A signal becomes an alarm on the first row at or after its start, scored with its confidence, and
only when that row is in the test half. Signals spanning half the series or more (a trend, a
forecast fit) don't point at a moment and are skipped.

The methods (benchmark/methods.py):

- router_picks, all_analyzers, zscore_only: the pipeline with the router's picks, every analyzer, or
  only anomaly_zscore.
- static_threshold: each metric's alert line is its lowest and highest value in the train half. An
  alarm (score 1.0) is raised on the first test row of each excursion outside that range.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from benchmark import harness
from benchmark.methods import ALL_ANALYZERS, ROUTER_PICKS, STATIC_THRESHOLD, ZSCORE_ANALYZERS, ZSCORE_ONLY
from benchmark.smd.data import METRIC_COUNT, SmdMachine, load_machine, metric_name

INTERVAL_MINUTES = 1
WHOLE_SERIES_FRACTION = 0.5
PIPELINE_METHODS = {ROUTER_PICKS: ROUTER_PICKS, ALL_ANALYZERS: ALL_ANALYZERS, ZSCORE_ONLY: ZSCORE_ANALYZERS}
METHODS = (*PIPELINE_METHODS, STATIC_THRESHOLD)


def run_machine(dataset_dir: str, name: str, method: str) -> dict[str, Any]:
    """Every alarm one method raises on one machine, and what it cost. Never raises: a metric that
    fails is counted and skipped."""
    logging.disable(logging.WARNING)
    harness.warm_up()
    machine = load_machine(Path(dataset_dir), name)
    started = time.perf_counter()
    if method == STATIC_THRESHOLD:
        alarms = static_threshold_alarms(machine)
        result = {"alarms": alarms, "analyzer_runs": 0, "errors": 0, "first_error": None, "analyzers_by_metric": {}}
    else:
        result = _pipeline_alarms(machine, PIPELINE_METHODS[method])
    result.update(machine=name, method=method, seconds=round(time.perf_counter() - started, 3))
    return result


def static_threshold_alarms(machine: SmdMachine) -> list[list[Any]]:
    alarms = []
    for index in range(METRIC_COUNT):
        train, test = machine.train[:, index], machine.test[:, index]
        low, high = float(np.nanmin(train)), float(np.nanmax(train))
        outside = (test < low) | (test > high)
        starts = np.flatnonzero(outside & ~np.concatenate([[False], outside[:-1]]))
        alarms.extend([int(row), index + 1, 1.0, STATIC_THRESHOLD] for row in starts)
    return alarms


def _pipeline_alarms(machine: SmdMachine, analyzers: str | tuple[str, ...]) -> dict[str, Any]:
    history = len(machine.train)
    values = np.vstack([machine.train, machine.test])
    timestamps = pd.date_range("2000-01-01", periods=len(values), freq=f"{INTERVAL_MINUTES}min", tz="UTC")
    times = timestamps.tz_convert(None).to_numpy()
    alarms: list[list[Any]] = []
    analyzer_runs = errors = 0
    first_error = None
    analyzers_by_metric: dict[str, list[str]] = {}
    for index in range(METRIC_COUNT):
        name = metric_name(index + 1)
        frame = pd.DataFrame({"timestamp": timestamps, "value": values[:, index], "metric_name": name})
        try:
            result = harness.build_pipeline(INTERVAL_MINUTES, name, analyzers).run_dataframe(frame)
        except Exception as exc:  # one metric failing doesn't sink the machine
            errors += 1
            first_error = first_error or f"{name}: {type(exc).__name__}: {exc}"
            continue
        analyzer_runs += len(result.executed_analyzers)
        analyzers_by_metric[name] = list(result.executed_analyzers)
        for signal in harness.user_facing_signals(result):
            start, end = _row(times, signal.start_time), _row(times, signal.end_time)
            if end - start >= WHOLE_SERIES_FRACTION * len(times) or start < history:
                continue
            alarms.append([start - history, index + 1, round(float(signal.confidence or 0.0), 6), str(signal.analyzer_id)])
    return {"alarms": alarms, "analyzer_runs": analyzer_runs, "errors": errors, "first_error": first_error, "analyzers_by_metric": analyzers_by_metric}


def _row(times: np.ndarray, moment) -> int:
    stamp = pd.Timestamp(moment)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("UTC").tz_localize(None)
    return min(int(np.searchsorted(times, stamp.to_datetime64(), side="left")), len(times) - 1)
