from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from backend.app.analyzers.custom.data_health import DataHealthAnalyzer
from backend.app.services.timeseries_routing_service import TimeSeriesRoutingService, build_csv_routing_config
from intelligence.config import load_config
from intelligence.finding_aggregator import FindingAggregator
from intelligence.importance_score import score_signals
from intelligence.normalize.normalizer import normalize_timeseries
from intelligence.pipeline import SignalPipeline
from intelligence.signals.schema import OperationalSignal

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TIMESTAMPS = pd.date_range("2026-09-01", periods=288, freq="5min", tz="UTC")
INDEX = np.arange(len(TIMESTAMPS))


class NullStore:
    engine = None


def _noisy_cpu(seed: int = 7) -> np.ndarray:
    return 50 + np.random.default_rng(seed).normal(0, 3, len(TIMESTAMPS))


def _normalized(values: np.ndarray, *, drop: range | list[int] = (), metric: str = "cpu_usage", **columns) -> pd.DataFrame:
    frame = pd.DataFrame({"timestamp": TIMESTAMPS, "metric_name": metric, "value": values, "service": "svc", "env": "prod", **columns})
    frame = frame.drop(index=list(drop))
    config = build_csv_routing_config(provider="generic", service="svc", metric_name=metric, interval="5m", analyzer_id="all", preview=True)
    return normalize_timeseries(frame, config.input)


def _signals(normalized: pd.DataFrame) -> list[OperationalSignal]:
    return DataHealthAnalyzer().analyze(normalized)


def test_gap_in_a_normally_dense_series_is_reported() -> None:
    [signal] = _signals(_normalized(_noisy_cpu(), drop=range(150, 157)))

    assert signal.signal_type == "data_gap"
    assert signal.evidence["missing_points"] == 7
    assert signal.evidence["gap_minutes"] == 35.0
    assert signal.start_time == TIMESTAMPS[149].to_pydatetime()
    assert signal.end_time == TIMESTAMPS[157].to_pydatetime()
    assert "stopped reporting for 35 minutes" in signal.summary


def test_short_gap_is_not_reported() -> None:
    assert _signals(_normalized(_noisy_cpu(), drop=range(150, 152))) == []


def test_series_that_is_sparse_by_design_is_not_reported_for_gaps() -> None:
    # Reports every other interval throughout - its "gaps" are its normal cadence.
    assert _signals(_normalized(_noisy_cpu(), drop=range(1, 288, 2))) == []


def test_flatline_in_a_normally_changing_series_is_reported() -> None:
    values = np.where((INDEX >= 100) & (INDEX < 120), 61.5, _noisy_cpu())

    [signal] = _signals(_normalized(values))

    assert signal.signal_type == "flatline"
    assert signal.severity == "medium"
    assert signal.evidence["stuck_value"] == 61.5
    assert signal.evidence["identical_points"] == 20
    assert signal.evidence["still_flat_at_end"] is False


def test_flatline_still_stuck_at_the_end_is_high_severity() -> None:
    values = np.where(INDEX >= 250, 61.5, _noisy_cpu())

    [signal] = _signals(_normalized(values))

    assert signal.severity == "high"
    assert signal.evidence["still_flat_at_end"] is True
    assert "still stuck at the end of the window" in signal.summary


def test_short_flat_stretch_is_not_reported() -> None:
    values = np.where((INDEX >= 100) & (INDEX < 104), 61.5, _noisy_cpu())

    assert _signals(_normalized(values)) == []


def test_metrics_that_are_constant_or_mostly_constant_by_design_are_not_reported() -> None:
    rng = np.random.default_rng(3)
    replica_count = np.full(len(TIMESTAMPS), 3.0)
    error_counter = np.where(rng.random(len(TIMESTAMPS)) < 0.05, rng.integers(1, 4, len(TIMESTAMPS)), 0).astype(float)

    assert _signals(_normalized(replica_count, metric="replicas")) == []
    assert _signals(_normalized(error_counter, metric="errors")) == []


def test_healthy_noisy_series_is_not_reported() -> None:
    assert _signals(_normalized(_noisy_cpu())) == []


def test_each_host_is_checked_as_its_own_series() -> None:
    healthy = pd.DataFrame({"timestamp": TIMESTAMPS, "value": _noisy_cpu(1), "host": "host-a"})
    stuck = pd.DataFrame({"timestamp": TIMESTAMPS, "value": np.where(INDEX >= 200, 70.0, _noisy_cpu(2)), "host": "host-b"})
    frame = pd.concat([healthy, stuck], ignore_index=True).assign(metric_name="cpu_usage", service="svc", env="prod")
    config = build_csv_routing_config(provider="generic", service="svc", metric_name="cpu_usage", interval="5m", analyzer_id="all", preview=True)

    [signal] = DataHealthAnalyzer().analyze(normalize_timeseries(frame, config.input))

    assert signal.evidence["host"] == "host-b"
    assert "cpu_usage on host-b" in signal.summary


def test_data_health_signals_become_their_own_data_quality_finding() -> None:
    normalized = _normalized(np.where(INDEX >= 250, 61.5, _noisy_cpu()))
    flatline = score_signals(_signals(normalized), normalized["timestamp"].max().to_pydatetime())
    trend = OperationalSignal(
        signal_type="trend",
        analyzer_id="trend",
        metric_name="cpu_usage",
        service="svc",
        env="prod",
        severity="medium",
        confidence=0.8,
        start_time=TIMESTAMPS[0].to_pydatetime(),
        end_time=TIMESTAMPS[-1].to_pydatetime(),
        summary="cpu_usage increased steadily.",
        evidence={"slope_percent": 20.0},
    )

    findings = FindingAggregator().aggregate([*flatline, trend], normalized).findings

    by_category = {finding.category: finding for finding in findings}
    assert set(by_category) == {"data_quality", "behavior_change"}
    data_quality = by_category["data_quality"]
    assert data_quality.title == "cpu_usage got stuck at a constant value during the selected time window."
    assert data_quality.signal_ids == [flatline[0].signal_id]
    assert data_quality.health_status == "significant"
    assert by_category["behavior_change"].signal_ids == [trend.signal_id]


def test_registered_data_health_is_eligible_on_a_flat_series_and_always_runs() -> None:
    config = load_config(PROJECT_ROOT / "config.yaml")
    config.analysis.selection_mode = "recommended_threshold"
    normalized = _normalized(np.full(len(TIMESTAMPS), 3.0), metric="replicas")

    routing = TimeSeriesRoutingService().route_normalized(normalized).analyzer_routing
    decisions = {decision["analyzer_id"]: decision for decision in routing}
    pipeline = SignalPipeline(config=config, store=NullStore())

    assert decisions["data_health"]["eligible"] is True
    assert decisions["ruptures"]["recommendation"] == "REJECTED"
    assert "data_health" in {analyzer.analyzer_id for analyzer in pipeline._build_analyzers(routing)}
