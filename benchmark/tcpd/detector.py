"""Run a TCPD series through Ops Signals and read off the change points it reports.

Two modes:

- product: the production pipeline (generic provider). The router decides which analyzers run;
  change points are read from the change analyzers' signals (`ruptures`, `baseline_shift`). When
  the router doesn't select one, Ops Signals reports no change point - exactly what a user sees.
- all_analyzers: the same pipeline with every enabled analyzer, whatever the router decides - the
  "run everything" baseline. Change points are read the same way as for the product.
- direct: the `ruptures` analyzer with its production configuration, run on every series whatever
  the router would decide. This measures the change-point detector itself.

Z-score only and static threshold don't report change points, so they have no method here; TCPD's
own "zero" method (no change points) is the trivial baseline in the leaderboard.

Both change analyzers report at most one change point per series - the primary shift - by design.
TCPD series often have several, so recall is capped on those series.

TCPD scores change points by row index, not time, and many series are yearly or monthly with
irregular calendar spacing. Each series is given a synthetic daily timestamp (one row per day from
2000-01-01) so every row maps to one resampled bucket; the location reported by an analyzer is
mapped back to its row.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from benchmark import harness
from benchmark.methods import ALL_ANALYZERS
from benchmark.router_benchmark import _instantiate_analyzer
from benchmark.tcpd.data import TcpdSeries
from intelligence.normalize.normalizer import normalize_timeseries

METRIC_NAME = "tcpd_series"
INTERVAL_MINUTES = 1440
CHANGE_SIGNAL_TYPES = {"ruptures", "baseline_shift"}
DIRECT_ANALYZER = "ruptures"


@dataclass(slots=True)
class TcpdRun:
    series: str
    n_obs: int
    product_cps: list[int] = field(default_factory=list)
    direct_cps: list[int] = field(default_factory=list)
    executed_analyzers: list[str] = field(default_factory=list)
    change_analyzers_run: list[str] = field(default_factory=list)
    routing: list[dict[str, Any]] = field(default_factory=list)
    product_error: str | None = None
    direct_error: str | None = None
    all_cps: list[int] = field(default_factory=list)
    all_executed_analyzers: list[str] = field(default_factory=list)
    all_error: str | None = None
    seconds: dict[str, float] = field(default_factory=dict)


def series_frame(series: TcpdSeries) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2000-01-01", periods=len(series.values), freq="D", tz="UTC"),
            "value": series.values,
            "metric_name": METRIC_NAME,
        }
    )


def run_series(series: TcpdSeries) -> TcpdRun:
    logging.disable(logging.WARNING)
    harness.warm_up()
    frame = series_frame(series)
    timestamps = frame["timestamp"].dt.tz_convert(None).to_numpy()
    run = TcpdRun(series=series.name, n_obs=len(frame))
    pipeline = harness.build_pipeline(INTERVAL_MINUTES, METRIC_NAME)

    started = time.perf_counter()
    try:
        result = pipeline.run_dataframe(frame)
        run.executed_analyzers = list(result.executed_analyzers)
        run.routing = [
            {
                "analyzer": d.get("analyzer_id"),
                "recommendation": d.get("recommendation"),
                "score": d.get("final_score"),
                "reason": (d.get("reasons") or [d.get("reason")])[0],
            }
            for d in result.analyzer_routing
        ]
        change_signals = [s for s in result.signals if s.signal_type in CHANGE_SIGNAL_TYPES]
        run.change_analyzers_run = sorted({str(s.analyzer_id) for s in change_signals} | ({*run.executed_analyzers} & {"ruptures", "baseline_shift"}))
        run.product_cps = _change_points(change_signals, timestamps)
    except Exception as exc:  # a failure scores 0, as TCPD's paper scores method failures
        run.product_error = f"{type(exc).__name__}: {exc}"
    run.seconds["product"] = round(time.perf_counter() - started, 3)

    started = time.perf_counter()
    try:
        result = harness.build_pipeline(INTERVAL_MINUTES, METRIC_NAME, ALL_ANALYZERS).run_dataframe(frame)
        run.all_executed_analyzers = list(result.executed_analyzers)
        run.all_cps = _change_points([s for s in result.signals if s.signal_type in CHANGE_SIGNAL_TYPES], timestamps)
    except Exception as exc:
        run.all_error = f"{type(exc).__name__}: {exc}"
    run.seconds[ALL_ANALYZERS] = round(time.perf_counter() - started, 3)

    started = time.perf_counter()
    try:
        analyzer = _instantiate_analyzer(DIRECT_ANALYZER)
        normalized = normalize_timeseries(frame, pipeline.config.input)
        run.direct_cps = _change_points(analyzer.analyze(normalized), timestamps)
    except Exception as exc:
        run.direct_error = f"{type(exc).__name__}: {exc}"
    run.seconds["direct"] = round(time.perf_counter() - started, 3)
    return run


def _change_points(signals, timestamps: np.ndarray) -> list[int]:
    rows = set()
    for signal in signals:
        evidence = signal.evidence or {}
        moment = evidence.get("change_point_time")
        if moment:
            stamp = pd.Timestamp(moment).tz_convert("UTC").tz_localize(None).to_datetime64()
            row = int(np.searchsorted(timestamps, stamp, side="left"))
        elif evidence.get("change_point_index") is not None:
            row = int(evidence["change_point_index"])
        else:
            continue
        if 0 < row < len(timestamps):
            rows.add(row)
    return sorted(rows)
