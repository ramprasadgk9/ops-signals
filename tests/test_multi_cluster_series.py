"""Series from several clusters behind one Prometheus-compatible endpoint (Mimir, Thanos) share
service/env and differ only by an external `cluster` label. They must be analysed as separate
series, and findings must say which cluster they belong to."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from backend.app.services.timeseries_routing_service import build_csv_routing_config
from intelligence.normalize.normalizer import normalize_timeseries
from intelligence.pipeline import SignalPipeline
from intelligence.series_identity import run_analyzer_by_cluster
from intelligence.analyzers.anomaly_zscore import ZScoreAnomalyAnalyzer

POINTS = 288


class InMemoryStore:
    def __init__(self) -> None:
        self.normalized_points = None
        self.saved_signals = []
        self.saved_findings = []

    def init_db(self) -> None:
        return None

    def init_db_from_sql(self, sql_path: Path) -> None:
        return None

    def save_normalized_points(self, dataframe, analysis_run_id=None, series_key=None) -> None:
        self.normalized_points = dataframe.copy()

    def save_signals(self, signals, embeddings=None) -> None:
        self.saved_signals = list(signals)

    def save_findings(self, findings) -> None:
        self.saved_findings = list(findings)

    def save_level_events(self, analysis_run_id, normalized) -> list:
        return []

    def create_analysis_run(self, payload) -> None:
        return None

    def update_analysis_run_learning_snapshot(self, analysis_run_id, snapshot) -> None:
        return None

    def save_capabilities(self, capabilities) -> None:
        return None

    def save_questions(self, questions) -> None:
        return None

    def save_question_answers(self, answers) -> None:
        return None


class NullEmbedder:
    def embed(self, text: str):
        return None


def _cluster_frame(cluster: str | None, *, spike: bool, seed: int) -> pd.DataFrame:
    values = 100 + np.random.default_rng(seed).uniform(-2, 2, POINTS)
    if spike:
        values[200:204] = 1000.0
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-09-01", periods=POINTS, freq="5min", tz="UTC"),
            "metric_name": "http_requests",
            "value": values,
            "service": "checkout",
            "env": "prod",
        }
    )
    if cluster is not None:
        frame["cluster"] = cluster
    return frame


def _config(analyzer_id: str = "anomaly_zscore"):
    return build_csv_routing_config(
        provider="generic", service="checkout", metric_name="http_requests", interval="5m", analyzer_id=analyzer_id, preview=False
    )


def _two_clusters_spike_in_us() -> pd.DataFrame:
    return pd.concat([_cluster_frame("eu", spike=False, seed=1), _cluster_frame("us", spike=True, seed=2)], ignore_index=True)


def test_normalizer_keeps_clusters_as_separate_series() -> None:
    normalized = normalize_timeseries(_two_clusters_spike_in_us(), _config().input)

    assert "cluster" in normalized.columns
    assert sorted(normalized["cluster"].unique()) == ["eu", "us"]
    # Not averaged together: each cluster keeps its own 288 points.
    assert normalized.groupby("cluster").size().to_dict() == {"eu": POINTS, "us": POINTS}
    assert normalized.loc[normalized["cluster"] == "eu", "value"].max() < 200


def test_normalizer_without_cluster_label_leaves_cluster_empty() -> None:
    normalized = normalize_timeseries(_cluster_frame(None, spike=False, seed=1), _config().input)

    assert normalized["cluster"].isna().all()


def test_analyzer_runs_once_per_cluster_and_stamps_the_cluster() -> None:
    normalized = normalize_timeseries(_two_clusters_spike_in_us(), _config().input)

    signals = run_analyzer_by_cluster(ZScoreAnomalyAnalyzer(), normalized)

    flagged = [signal for signal in signals if signal.evidence.get("finding_rule_matched")]
    assert flagged
    assert {signal.cluster for signal in flagged} == {"us"}


def test_analyzer_on_data_without_clusters_is_unchanged() -> None:
    normalized = normalize_timeseries(_cluster_frame(None, spike=True, seed=2), _config().input)

    direct = ZScoreAnomalyAnalyzer().analyze(normalized)
    by_cluster = run_analyzer_by_cluster(ZScoreAnomalyAnalyzer(), normalized)

    assert [signal.summary for signal in by_cluster] == [signal.summary for signal in direct]
    assert all(signal.cluster is None for signal in by_cluster)


def test_pipeline_reports_the_anomaly_only_for_the_cluster_that_had_it() -> None:
    store = InMemoryStore()

    result = SignalPipeline(_config(), store=store, embedder=NullEmbedder()).run_dataframe(_two_clusters_spike_in_us())

    assert result.findings
    assert {finding.cluster for finding in result.findings} == {"us"}
    assert {signal.cluster for signal in store.saved_signals} <= {"us", "eu"}
    assert all(finding.service == "checkout" for finding in result.findings)


def test_pipeline_finding_records_carry_cluster() -> None:
    result = SignalPipeline(_config(), store=InMemoryStore(), embedder=NullEmbedder()).run_dataframe(_two_clusters_spike_in_us())

    assert all(finding.to_record()["cluster"] == "us" for finding in result.findings)
    assert all(signal.to_dict()["cluster"] in {"eu", "us"} for signal in result.signals)
