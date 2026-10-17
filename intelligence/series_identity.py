"""Series identity beyond metric/service/env: the `cluster` column.

Analyzers group a frame by metric_name/service/env, which would merge the same service from two
clusters into one series. Rather than teach every analyzer (built-in, custom, HTTP) about
clusters, the pipeline hands each cluster to the analyzer separately and stamps the result.
"""

from __future__ import annotations

import threading
from contextlib import nullcontext

import pandas as pd

from intelligence.signals.schema import OperationalSignal

CLUSTER_COLUMN = "cluster"

# In-process analyzers run one at a time across all threads. Stumpy computes with Numba, whose
# default "workqueue" threading layer aborts the whole process when two threads use it at once
# ("Concurrent access has been detected"). Analyses run on several threads - the API's threadpool,
# the scheduler, alert enrichment - so without this two at once could kill the backend. Analyzers
# that compute in another process (HTTP analyzers, `runs_remotely`) don't take it.
IN_PROCESS_ANALYZER_LOCK = threading.RLock()


def frame_clusters(frame: pd.DataFrame) -> list[str]:
    """Distinct non-empty cluster values in the frame, sorted; [] for single-cluster data."""
    if CLUSTER_COLUMN not in frame.columns:
        return []
    return sorted({str(value) for value in frame[CLUSTER_COLUMN].dropna() if str(value)})


def run_analyzer_by_cluster(analyzer, frame: pd.DataFrame) -> list[OperationalSignal]:
    with analyzer_slot(analyzer):
        return _run_by_cluster(analyzer, frame)


def analyzer_slot(analyzer):
    """The lock an analyzer must hold while it computes: IN_PROCESS_ANALYZER_LOCK, or none for an
    analyzer that runs remotely."""
    return nullcontext() if getattr(analyzer, "runs_remotely", False) else IN_PROCESS_ANALYZER_LOCK


def _run_by_cluster(analyzer, frame: pd.DataFrame) -> list[OperationalSignal]:
    clusters = frame_clusters(frame)
    if not clusters:
        return list(analyzer.analyze(frame))
    signals: list[OperationalSignal] = []
    labelled = frame[CLUSTER_COLUMN].notna()
    for cluster in clusters:
        generated = analyzer.analyze(frame[frame[CLUSTER_COLUMN].astype(str) == cluster].reset_index(drop=True))
        for signal in generated:
            signal.cluster = cluster
        signals.extend(generated)
    # Rows without a cluster value next to rows with one (mixed sources) are still analysed.
    if not labelled.all():
        signals.extend(analyzer.analyze(frame[~labelled].reset_index(drop=True)))
    return signals


def cluster_points(points: pd.DataFrame, cluster: str | None) -> pd.DataFrame:
    """The rows of `points` that belong to `cluster` (None = rows without a cluster)."""
    if CLUSTER_COLUMN not in points.columns:
        return points
    if cluster is None:
        return points[points[CLUSTER_COLUMN].isna()]
    return points[points[CLUSTER_COLUMN].astype(str) == cluster]
