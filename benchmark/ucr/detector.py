"""Ask each method for its single answer on a UCR series: the row where it thinks the anomaly is.

UCR tells every method there is exactly one anomaly, after the training part, and scores one
location per series. The methods:

- product: the production pipeline (generic provider), with the router choosing the analyzers,
  exactly as a CSV upload runs. The answer is the top-ranked localized finding after the training
  part, ranked by importance score, the order a user sees findings in.
- anomaly_zscore, pyod_outlier, seasonal_anomaly: one analyzer with its production configuration,
  run on every series whatever the router would decide. The answer is its most confident localized
  signal after the training part. This measures each detector without routing.
- discord (reference, not an Ops Signals analyzer): the textbook matrix-profile discord. Every
  test subsequence is compared with every training subsequence (the training part is guaranteed
  normal), and the answer is the centre of the test subsequence farthest from its nearest training
  neighbour. The window is one period, estimated from the training part's autocorrelation.
- max_jump (trivial baseline): the largest point-to-point jump in the test part. Wu & Keogh
  argue a good benchmark should defeat one-liners like this, so it shows how much of the archive
  is that easy.

A signal's location is its change point when it reports one, otherwise its first row. Signals
spanning half the series or more (a trend, a forecast fit, a motif summary) don't point at a
location and are skipped. `stumpy`, the product's matrix-profile analyzer, reports repeated
patterns (motifs), not unusual ones, so it gives no location and has no direct method here.

UCR series have no timestamps. Each gets a synthetic one-minute timestamp, one row per resampled
bucket, and analyzer locations are mapped back to rows.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from benchmark import harness
from benchmark.router_benchmark import _instantiate_analyzer
from benchmark.ucr.data import UcrSeries, load_series
from intelligence.normalize.normalizer import normalize_timeseries

METRIC_NAME = "ucr_series"
INTERVAL_MINUTES = 1
DIRECT_ANALYZERS = ("anomaly_zscore", "pyod_outlier", "seasonal_anomaly")
PRODUCT, DISCORD, MAX_JUMP = "product", "discord", "max_jump"
METHODS = (PRODUCT, *DIRECT_ANALYZERS, DISCORD, MAX_JUMP)
WHOLE_SERIES_FRACTION = 0.5
TOP_CANDIDATES = 5

# Discord window bounds, in points. The period search looks at up to this many training points.
MIN_WINDOW, MAX_WINDOW, DEFAULT_WINDOW = 16, 1000, 100
PERIOD_SEARCH_POINTS = 20_000


def series_frame(series: UcrSeries) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2000-01-01", periods=len(series.values), freq=f"{INTERVAL_MINUTES}min", tz="UTC"),
            "value": series.values,
            "metric_name": METRIC_NAME,
        }
    )


def run_method(path: str, method: str) -> dict[str, Any]:
    """One method on one series. Never raises: a failure is recorded and scores as no answer."""
    logging.disable(logging.WARNING)
    series = load_series(Path(path))
    started = time.perf_counter()
    result: dict[str, Any] = {"method": method, "row": None, "error": None}
    try:
        if method == PRODUCT:
            result.update(_product(series))
        elif method in DIRECT_ANALYZERS:
            result.update(_direct(series, method))
        elif method == DISCORD:
            result.update(_discord(series))
        elif method == MAX_JUMP:
            result.update(_max_jump(series))
        else:
            raise ValueError(f"unknown method {method}")
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["seconds"] = round(time.perf_counter() - started, 3)
    return result


def _product(series: UcrSeries) -> dict[str, Any]:
    frame = series_frame(series)
    pipeline = harness.build_pipeline(INTERVAL_MINUTES, METRIC_NAME)
    result = pipeline.run_dataframe(frame)
    candidates = _candidates(result.signals, frame, series.train_end)
    candidates.sort(key=lambda c: (-c["importance"], -c["confidence"], c["row"]))
    return {
        **_answer(candidates),
        "executed_analyzers": list(result.executed_analyzers),
        "routing": [
            {
                "analyzer": d.get("analyzer_id"),
                "recommendation": d.get("recommendation"),
                "score": d.get("final_score"),
                "reason": (d.get("reasons") or [d.get("reason")])[0],
            }
            for d in result.analyzer_routing
        ],
        "signal_count": len(result.signals),
    }


def _direct(series: UcrSeries, analyzer_id: str) -> dict[str, Any]:
    analyzer = _instantiate_analyzer(analyzer_id)
    if analyzer is None:
        raise RuntimeError(f"{analyzer_id} is not registered or can't be built")
    frame = series_frame(series)
    config = harness.build_pipeline(INTERVAL_MINUTES, METRIC_NAME).config
    signals = analyzer.analyze(normalize_timeseries(frame, config.input))
    candidates = _candidates(signals, frame, series.train_end)
    candidates.sort(key=lambda c: (-c["confidence"], c["row"]))
    return {**_answer(candidates), "signal_count": len(signals)}


def _discord(series: UcrSeries) -> dict[str, Any]:
    import stumpy

    values, train_end = series.values, series.train_end
    window = estimate_period(values[:train_end])
    profile = stumpy.stump(values[train_end:], window, values[:train_end], ignore_trivial=False)
    distances = profile[:, 0].astype(float)
    distances[~np.isfinite(distances)] = -np.inf
    start = int(np.argmax(distances))
    return {"row": train_end + start + window // 2, "window": window, "discord_distance": round(float(distances[start]), 6)}


def _max_jump(series: UcrSeries) -> dict[str, Any]:
    tail = series.values[series.train_end - 1 :]
    return {"row": series.train_end + int(np.argmax(np.abs(np.diff(tail))))}


def estimate_period(train: np.ndarray) -> int:
    """The first autocorrelation peak after the autocorrelation first turns negative, clipped to
    [MIN_WINDOW, MAX_WINDOW]; DEFAULT_WINDOW when the series shows no period."""
    x = np.asarray(train[-PERIOD_SEARCH_POINTS:], dtype=float)
    x = x - x.mean()
    if len(x) < 2 * MIN_WINDOW or not np.any(x):
        return DEFAULT_WINDOW
    spectrum = np.fft.rfft(x, n=2 * len(x))
    acf = np.fft.irfft(spectrum * np.conj(spectrum))[: len(x)]
    acf /= acf[0]
    limit = min(len(acf) - 1, MAX_WINDOW * 2)
    negative = np.flatnonzero(acf[1:limit] < 0)
    if not len(negative):
        return DEFAULT_WINDOW
    first = int(negative[0]) + 1
    peak = first + int(np.argmax(acf[first:limit]))
    if acf[peak] <= 0.1:
        return DEFAULT_WINDOW
    return int(np.clip(peak, MIN_WINDOW, MAX_WINDOW))


def _candidates(signals, frame: pd.DataFrame, train_end: int) -> list[dict[str, Any]]:
    """Every localized signal whose location is in the test part (0-based row >= train_end)."""
    times = frame["timestamp"].dt.tz_convert(None).to_numpy()
    candidates = []
    for signal in signals:
        start, end = _row(times, signal.start_time), _row(times, signal.end_time)
        moment = (signal.evidence or {}).get("change_point_time")
        if moment:
            row = _row(times, moment)
        elif end - start >= WHOLE_SERIES_FRACTION * len(times):
            continue
        else:
            row = start
        if row >= train_end:
            candidates.append(
                {
                    "row": row,
                    "analyzer": str(signal.analyzer_id),
                    "signal_type": str(signal.signal_type),
                    "importance": round(float(signal.importance_score or 0.0), 6),
                    "confidence": round(float(signal.confidence or 0.0), 6),
                }
            )
    return candidates


def _answer(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "row": candidates[0]["row"] if candidates else None,
        "top_candidates": candidates[:TOP_CANDIDATES],
        "candidate_rows": [c["row"] for c in candidates],
    }


def _row(times: np.ndarray, moment) -> int:
    stamp = pd.Timestamp(moment)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("UTC").tz_localize(None)
    return min(int(np.searchsorted(times, stamp.to_datetime64(), side="left")), len(times) - 1)
