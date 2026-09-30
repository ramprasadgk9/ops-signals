"""Run NAB series through the production analysis path and turn its signals into NAB-format
per-row anomaly scores.

What runs is the same path a CSV upload takes with the `generic` provider: normalization with the
provider's validation rules, the analyzer router, the analyzers it selects
(`recommended_threshold`, top 3 above 0.80, plus data_health), and importance scoring. Two input
settings are chosen per series, the way a user would set them on upload: the resampling interval
is the series' own median sampling interval (the generic default of 5m would leave 11 of every 12
buckets empty on hourly data), and negative values are allowed (one artificial NAB series has them).

Only signals a user would see count: those that became part of a finding, after each analyzer's own
finding rules (harness.user_facing_signals). A signal becomes an alarm, scored with the signal's
confidence, at one row:

- batch mode analyzes the whole series at once, and the alarm goes on the first row at or after the
  signal's start. Detectors see the full series, including data after the alarm. That breaks NAB's
  rule that a detector may only use past data, so batch results are not comparable with NAB's
  published scoreboard.
- replay mode is causal. It analyzes a trailing window every REPLAY_STEP new rows, the way a
  scheduled production run would, and an alarm goes on the row where that run happens - the first
  moment the event could actually have been known. An event raises one alarm: a later run that
  re-detects it (same analyzer and signal type, start within REPLAY_STEP rows, confidence no higher
  than an alarm already raised there) stays quiet.

Signals spanning the whole analysis window (a trend or a forecast fit) start at the window's first
row, so in batch mode they land in NAB's probationary period, which is never scored, and in replay
mode they are older than the new-event horizon and never alarm.

Baselines (benchmark/methods.py) run in replay mode only, the mode behind the headline:

- Ops Signals, all analyzers, and Z-score only: the same replay with a different analyzer set.
- Static threshold: the alert line is the lowest and highest value seen in NAB's probationary
  period, which NAB treats as the detector's learning time. An alarm (score 1.0) is raised when the
  value first crosses outside that range, and again only after it has come back inside - the way a
  threshold alert fires and resolves. It is causal by construction.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from benchmark import harness
from benchmark.methods import ALL_ANALYZERS, ROUTER_PICKS, STATIC_THRESHOLD, ZSCORE_ANALYZERS, ZSCORE_ONLY
from benchmark.nab.metrics import probation_rows
from intelligence.normalize.normalizer import VALIDATION_WARNINGS_ATTR
from intelligence.pipeline import SignalPipeline

PROVIDER = harness.PROVIDER
METRIC_NAME = "nab_series"

# Replay cadence and memory, in rows. 12 rows is an hour of 5-minute data; 2016 rows is a week.
REPLAY_STEP = 12
REPLAY_WINDOW = 2016
# The oldest a signal's start may be, in rows before the current run, to still count as a new event.
REPLAY_NEW_EVENT_HORIZON = 4 * REPLAY_STEP
REPLAY_MIN_HISTORY = 288

# Replay-mode baselines compared with the product (ROUTER_PICKS, whose replay is the headline).
PIPELINE_BASELINES = {ALL_ANALYZERS: ALL_ANALYZERS, ZSCORE_ONLY: ZSCORE_ANALYZERS}
BASELINES = (*PIPELINE_BASELINES, STATIC_THRESHOLD)


@dataclass(slots=True)
class Replay:
    """One replay of a series: alarm scores per row, overall and per analyzer, and which analyzers
    ran at each scheduled run (keyed by the run's last row)."""

    scores: np.ndarray
    runs: int = 0
    errors: int = 0
    first_error: str | None = None
    analyzer_runs: int = 0
    scores_by_analyzer: dict[str, np.ndarray] = field(default_factory=dict)
    executed_by_run: dict[int, list[str]] = field(default_factory=dict)


@dataclass(slots=True)
class MethodRun:
    """One method's replay on one series, with what it cost."""

    scores: list[float]
    seconds: float
    runs: int
    analyzer_runs: int
    errors: int = 0
    first_error: str | None = None
    # Per analyzer, for the all-analyzers run: what each analyzer alone would have alarmed on.
    scores_by_analyzer: dict[str, list[float]] = field(default_factory=dict)


@dataclass(slots=True)
class SeriesRun:
    series: str
    rows: int
    interval_minutes: int
    batch_scores: list[float]
    replay_scores: list[float]
    executed_analyzers: list[str]
    routing: list[dict[str, Any]]
    batch_signal_count: int
    replay_runs: int
    batch_seconds: float
    replay_seconds: float
    validation_warnings: list[str] = field(default_factory=list)
    batch_error: str | None = None
    replay_errors: int = 0
    first_replay_error: str | None = None
    replay_analyzer_runs: int = 0
    baselines: dict[str, MethodRun] = field(default_factory=dict)
    # The analyzers the router ran at each scheduled replay run, keyed by the run's last row.
    replay_executed_by_run: dict[int, list[str]] = field(default_factory=dict)


def build_pipeline(interval_minutes: int, analyzers: str | tuple[str, ...] = ROUTER_PICKS) -> SignalPipeline:
    return harness.build_pipeline(interval_minutes, METRIC_NAME, analyzers)


def load_series(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["metric_name"] = METRIC_NAME
    return frame.sort_values("timestamp").reset_index(drop=True)


def median_interval_minutes(frame: pd.DataFrame) -> int:
    diffs = frame["timestamp"].diff().dt.total_seconds().dropna()
    return max(1, int(round(float(diffs.median()) / 60.0))) if len(diffs) else 5


def run_series(path: Path, series_name: str, skip: frozenset[str] = frozenset()) -> SeriesRun:
    logging.disable(logging.WARNING)
    harness.warm_up()
    frame = load_series(path)
    interval = median_interval_minutes(frame)
    pipeline = build_pipeline(interval)
    times = frame["timestamp"].dt.tz_convert(None).to_numpy()

    batch_scores = np.zeros(len(frame))
    executed: list[str] = []
    routing: list[dict[str, Any]] = []
    warnings: list[str] = []
    batch_error = None
    signal_count = 0
    started = time.perf_counter()
    try:
        result = pipeline.run_dataframe(frame[["timestamp", "value", "metric_name"]])
        executed = list(result.executed_analyzers)
        routing = [_routing_summary(decision) for decision in result.analyzer_routing]
        warnings = list(result.normalized_points.attrs.get(VALIDATION_WARNINGS_ATTR) or [])
        signal_count = len(result.signals)
        for signal in harness.user_facing_signals(result):
            row = _row_at_or_after(times, signal.start_time)
            if row is not None:
                batch_scores[row] = max(batch_scores[row], float(signal.confidence))
    except Exception as exc:  # recorded per series, never fatal to the whole benchmark
        batch_error = f"{type(exc).__name__}: {exc}"
    batch_seconds = time.perf_counter() - started

    started = time.perf_counter()
    replay = _replay(pipeline, frame, times)
    replay_seconds = time.perf_counter() - started

    baselines: dict[str, MethodRun] = {}
    for method, analyzers in PIPELINE_BASELINES.items():
        if method in skip:
            continue
        started = time.perf_counter()
        result = _replay(build_pipeline(interval, analyzers), frame, times)
        baselines[method] = MethodRun(
            scores=[round(float(score), 6) for score in result.scores],
            seconds=round(time.perf_counter() - started, 3),
            runs=result.runs,
            analyzer_runs=result.analyzer_runs,
            errors=result.errors,
            first_error=result.first_error,
            scores_by_analyzer=(
                {name: [round(float(v), 6) for v in values] for name, values in result.scores_by_analyzer.items()}
                if method == ALL_ANALYZERS
                else {}
            ),
        )
    if STATIC_THRESHOLD not in skip:
        started = time.perf_counter()
        static_scores = static_threshold_scores(frame["value"].to_numpy(dtype=float))
        baselines[STATIC_THRESHOLD] = MethodRun(
            scores=[float(score) for score in static_scores],
            seconds=round(time.perf_counter() - started, 3),
            runs=1,
            analyzer_runs=0,
        )

    return SeriesRun(
        series=series_name,
        rows=len(frame),
        interval_minutes=interval,
        batch_scores=[round(float(score), 6) for score in batch_scores],
        replay_scores=[round(float(score), 6) for score in replay.scores],
        executed_analyzers=executed,
        routing=routing,
        batch_signal_count=signal_count,
        replay_runs=replay.runs,
        batch_seconds=round(batch_seconds, 3),
        replay_seconds=round(replay_seconds, 3),
        validation_warnings=warnings,
        batch_error=batch_error,
        replay_errors=replay.errors,
        first_replay_error=replay.first_error,
        replay_analyzer_runs=replay.analyzer_runs,
        baselines=baselines,
        replay_executed_by_run=replay.executed_by_run,
    )


def static_threshold_scores(values: np.ndarray, margin: float = 0.0) -> np.ndarray:
    """1.0 on each row where the value leaves the probationary period's [min, max] range, counting
    only the first row of each excursion; 0 elsewhere. A margin widens both limits by that fraction
    of the range (0.3 moves each limit 30% of the range further out), as a team would move the line
    to get fewer alerts."""
    scores = np.zeros(len(values))
    learn = probation_rows(len(values))
    normal = values[:learn][np.isfinite(values[:learn])]
    if not len(normal):
        return scores
    span = float(normal.max() - normal.min())
    low, high = float(normal.min()) - margin * span, float(normal.max()) + margin * span
    outside = (values < low) | (values > high)
    for row in range(learn, len(values)):
        if outside[row] and not outside[row - 1]:
            scores[row] = 1.0
    return scores


def _replay(pipeline: SignalPipeline, frame: pd.DataFrame, times: np.ndarray) -> Replay:
    replay = Replay(scores=np.zeros(len(frame)))
    raised: dict[tuple[str, str], list[tuple[int, float]]] = {}
    columns = frame[["timestamp", "value", "metric_name"]]
    for end in range(min(REPLAY_MIN_HISTORY, len(frame) - 1), len(frame), REPLAY_STEP):
        window = columns.iloc[max(0, end - REPLAY_WINDOW + 1) : end + 1]
        replay.runs += 1
        try:
            result = pipeline.run_dataframe(window)
        except Exception as exc:
            replay.errors += 1
            replay.first_error = replay.first_error or f"{type(exc).__name__}: {exc}"
            continue
        replay.analyzer_runs += len(result.executed_analyzers)
        replay.executed_by_run[end] = list(result.executed_analyzers)
        for signal in harness.user_facing_signals(result):
            start_row = _row_at_or_after(times, signal.start_time)
            if start_row is None or start_row < end - REPLAY_NEW_EVENT_HORIZON:
                continue
            analyzer = str(signal.analyzer_id)
            key = (analyzer, str(signal.signal_type))
            confidence = float(signal.confidence)
            if any(
                abs(start_row - earlier_row) <= REPLAY_STEP and earlier_confidence >= confidence
                for earlier_row, earlier_confidence in raised.get(key, [])
            ):
                continue
            raised.setdefault(key, []).append((start_row, confidence))
            replay.scores[end] = max(replay.scores[end], confidence)
            per_analyzer = replay.scores_by_analyzer.setdefault(analyzer, np.zeros(len(frame)))
            per_analyzer[end] = max(per_analyzer[end], confidence)
    return replay


def _row_at_or_after(times: np.ndarray, moment) -> int | None:
    stamp = pd.Timestamp(moment)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("UTC").tz_localize(None)
    row = int(np.searchsorted(times, stamp.to_datetime64(), side="left"))
    return row if row < len(times) else None


def _routing_summary(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "analyzer": decision.get("analyzer_id") or decision.get("analyzer"),
        "recommendation": decision.get("recommendation") or decision.get("category"),
        "score": decision.get("final_score", decision.get("score")),
        "reason": (decision.get("reasons") or [decision.get("reason")])[0],
    }
