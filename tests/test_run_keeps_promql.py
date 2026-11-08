"""A Prometheus run keeps the query it ran and the connection it used, so a guided investigation
can query the same series again. A CSV run has neither."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from backend.app.api.ingestion import PreviewPipelineStore
from intelligence.config import load_config
from intelligence.pipeline import SignalPipeline

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run(run_metadata: dict | None) -> dict:
    config = load_config(PROJECT_ROOT / "config.yaml")
    config.embeddings.enabled = False
    store = PreviewPipelineStore()
    timestamps = pd.date_range("2026-11-05 20:30", periods=60, freq="5min", tz="UTC")
    values = np.r_[np.full(30, 0.2), np.full(30, 1.8)]
    frame = pd.DataFrame({"timestamp": timestamps, "metric_name": "http_request_duration_seconds", "value": values, "service": "checkout"})
    SignalPipeline(config, store=store).run_dataframe(frame, run_metadata=run_metadata)
    return store.analysis_run


def test_a_prometheus_run_keeps_its_query_and_connection() -> None:
    run = _run({"connection_id": "prod", "promql": 'histogram_quantile(0.95, sum by (le) (rate(x_bucket{service="checkout"}[5m])))'})

    assert run["connection_id"] == "prod"
    assert run["promql"].startswith("histogram_quantile(0.95")


def test_a_csv_run_has_no_query() -> None:
    run = _run({"file_name": "checkout.csv"})

    assert run["promql"] is None and run["connection_id"] is None
