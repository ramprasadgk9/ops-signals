"""Run NAB series through the production analysis path and turn its signals into NAB-format
per-row anomaly scores.

What runs is the same path a CSV upload takes with the `generic` provider: normalization with the
provider's validation rules, the analyzer router, the analyzers it selects
(`recommended_threshold`, top 3 above 0.80, plus data_health), and importance scoring. Two input
settings are chosen per series, the way a user would set them on upload: the resampling interval
is the series' own median sampling interval (the generic default of 5m would leave 11 of every 12
buckets empty on hourly data), and negative values are allowed (one artificial NAB series has them).

A signal becomes an alarm, scored with the signal's confidence, at one row:

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


def build_pipeline(interval_minutes: int) -> SignalPipeline:
    return harness.build_pipeline(interval_minutes, METRIC_NAME)


def load_series(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["metric_name"] = METRIC_NAME
    return frame.sort_values("timestamp").reset_index(drop=True)


def median_interval_minutes(frame: pd.DataFrame) -> int:
    diffs = frame["timestamp"].diff().dt.total_seconds().dropna()
    return max(1, int(round(float(diffs.median()) / 60.0))) if len(diffs) else 5


def run_series(path: Path, series_name: str) -> SeriesRun:
    logging.disable(logging.WARNING)
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
        for signal in result.signals:
            row = _row_at_or_after(times, signal.start_time)
            if row is not None:
                batch_scores[row] = max(batch_scores[row], float(signal.confidence))
    except Exception as exc:  # recorded per series, never fatal to the whole benchmark
        batch_error = f"{type(exc).__name__}: {exc}"
    batch_seconds = time.perf_counter() - started

    started = time.perf_counter()
    replay_scores, runs, errors, first_error = _replay(pipeline, frame, times)
    replay_seconds = time.perf_counter() - started

    return SeriesRun(
        series=series_name,
        rows=len(frame),
        interval_minutes=interval,
        batch_scores=[round(float(score), 6) for score in batch_scores],
        replay_scores=[round(float(score), 6) for score in replay_scores],
        executed_analyzers=executed,
        routing=routing,
        batch_signal_count=signal_count,
        replay_runs=runs,
        batch_seconds=round(batch_seconds, 3),
        replay_seconds=round(replay_seconds, 3),
        validation_warnings=warnings,
        batch_error=batch_error,
        replay_errors=errors,
        first_replay_error=first_error,
    )


def _replay(pipeline: SignalPipeline, frame: pd.DataFrame, times: np.ndarray) -> tuple[np.ndarray, int, int, str | None]:
    scores = np.zeros(len(frame))
    raised: dict[tuple[str, str], list[tuple[int, float]]] = {}
    runs = errors = 0
    first_error = None
    columns = frame[["timestamp", "value", "metric_name"]]
    for end in range(min(REPLAY_MIN_HISTORY, len(frame) - 1), len(frame), REPLAY_STEP):
        window = columns.iloc[max(0, end - REPLAY_WINDOW + 1) : end + 1]
        runs += 1
        try:
            result = pipeline.run_dataframe(window)
        except Exception as exc:
            errors += 1
            first_error = first_error or f"{type(exc).__name__}: {exc}"
            continue
        for signal in result.signals:
            start_row = _row_at_or_after(times, signal.start_time)
            if start_row is None or start_row < end - REPLAY_NEW_EVENT_HORIZON:
                continue
            key = (str(signal.analyzer_id), str(signal.signal_type))
            confidence = float(signal.confidence)
            if any(
                abs(start_row - earlier_row) <= REPLAY_STEP and earlier_confidence >= confidence
                for earlier_row, earlier_confidence in raised.get(key, [])
            ):
                continue
            raised.setdefault(key, []).append((start_row, confidence))
            scores[end] = max(scores[end], confidence)
    return scores, runs, errors, first_error


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
