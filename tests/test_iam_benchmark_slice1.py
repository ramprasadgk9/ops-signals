from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from benchmark.iam_vs_llm.evaluators.f1_evaluator import F1Evaluator
from benchmark.iam_vs_llm.evaluators.normalization import NormalizedRCA, normalize_structured_text
from benchmark.iam_vs_llm.evaluators.taxonomy import RootCauseClass
from benchmark.iam_vs_llm.runners.iam_slice_runner import IAMSliceRunner
from benchmark.iam_vs_llm.scenarios.scenario_01_resource_degradation.generator import generate_scenario_1


def test_scenario_1_telemetry_generator(tmp_path: Path) -> None:
    paths = generate_scenario_1(output_dir=tmp_path, seed=123)
    
    assert paths["metrics_csv"].exists()
    assert paths["k8s_events"].exists()
    assert paths["ground_truth"].exists()

    df = pd.read_csv(paths["metrics_csv"])
    assert "timestamp" in df.columns
    assert "service" in df.columns
    assert "metric_name" in df.columns
    assert "value" in df.columns
    assert set(df["service"].unique()) == {"payment-service", "auth-service"}

    with open(paths["ground_truth"], "r") as f:
        gt = yaml.safe_load(f)
    assert gt["entity"] == "payment-service"
    assert gt["root_cause"] == RootCauseClass.MEMORY_LEAK.value


def test_taxonomy_and_normalization() -> None:
    text = (
        "Investigation complete.\n"
        "ROOT_CAUSE: MEMORY_LEAK\n"
        "ENTITY: payment-service\n"
        "WINDOW: 2026-09-07T10:30:00Z to 2026-09-07T11:45:00Z\n"
        "EVIDENCE: memory_usage, cpu_throttled_seconds\n"
    )
    normalized = normalize_structured_text(text)
    assert normalized.entity == "payment-service"
    assert normalized.root_cause == RootCauseClass.MEMORY_LEAK
    assert normalized.fault_window is not None
    assert "memory_usage" in normalized.evidence_keys

    # Fallback to UNKNOWN on invalid text
    invalid = normalize_structured_text("Something is broken, not sure why.")
    assert invalid.root_cause == RootCauseClass.UNKNOWN
    assert invalid.entity is None


def test_f1_evaluator_mechanics() -> None:
    evaluator = F1Evaluator()
    ground_truth = {
        "entity": "payment-service",
        "root_cause": "MEMORY_LEAK",
        "fault_window": {
            "start": "2026-09-07T10:30:00Z",
            "end": "2026-09-07T11:45:00Z",
        },
        "key_evidence": ["memory_usage", "cpu_throttled_seconds"],
    }

    # Perfect prediction (matches entity, root cause, window, and evidence)
    from datetime import datetime
    perfect = NormalizedRCA(
        entity="payment-service",
        root_cause=RootCauseClass.MEMORY_LEAK,
        fault_window=(
            datetime.fromisoformat("2026-09-07T10:30:00+00:00"),
            datetime.fromisoformat("2026-09-07T11:45:00+00:00"),
        ),
        evidence_keys=["memory_usage", "cpu_throttled_seconds"],
        raw_summary="Memory leak on payment-service driving CPU throttling",
    )
    res_perfect = evaluator.evaluate(perfect, ground_truth)
    assert res_perfect.passed is True
    assert res_perfect.status == "SUCCESS"
    assert res_perfect.entity_match is True
    assert res_perfect.root_cause_match is True
    assert res_perfect.window_iou == 1.0
    assert res_perfect.composite_score >= 0.85

    # Offset-naive datetime handling (must not raise TypeError)
    naive_pred = NormalizedRCA(
        entity="payment-service",
        root_cause=RootCauseClass.MEMORY_LEAK,
        fault_window=(
            datetime(2026, 9, 7, 10, 30, 0),  # offset-naive
            datetime(2026, 9, 7, 11, 45, 0),  # offset-naive
        ),
        evidence_keys=["memory_usage", "cpu_throttled_seconds"],
        raw_summary="Memory leak on payment-service driving CPU throttling",
    )
    res_naive = evaluator.evaluate(naive_pred, ground_truth)
    assert res_naive.window_iou == 1.0
    assert res_naive.passed is True

    # Partial prediction (correct diagnosis, but missing temporal window)
    partial = NormalizedRCA(
        entity="payment-service",
        root_cause=RootCauseClass.MEMORY_LEAK,
        fault_window=None,
        evidence_keys=["memory_usage", "cpu_throttled_seconds"],
        raw_summary="Memory leak",
    )
    res_partial = evaluator.evaluate(partial, ground_truth)
    assert res_partial.passed is False
    assert res_partial.status == "PARTIAL"

    # Wrong entity
    wrong_entity = NormalizedRCA(
        entity="auth-service",
        root_cause=RootCauseClass.MEMORY_LEAK,
        evidence_keys=["memory_usage"],
    )
    res_wrong_entity = evaluator.evaluate(wrong_entity, ground_truth)
    assert res_wrong_entity.passed is False
    assert res_wrong_entity.entity_match is False

    # Wrong root cause
    wrong_rc = NormalizedRCA(
        entity="payment-service",
        root_cause=RootCauseClass.CPU_STARVATION,
        evidence_keys=["cpu_usage"],
    )
    res_wrong_rc = evaluator.evaluate(wrong_rc, ground_truth)
    assert res_wrong_rc.passed is False
    assert res_wrong_rc.root_cause_match is False


def test_iam_slice_runner_end_to_end() -> None:
    scenario_dir = Path(__file__).resolve().parents[1] / "benchmark" / "iam_vs_llm" / "scenarios" / "scenario_01_resource_degradation"
    assert scenario_dir.exists()

    runner = IAMSliceRunner()
    run_result = runner.run_batch_ingest(scenario_dir)

    assert run_result.runner_id == "iam_slice_runner"
    assert run_result.execution_time_seconds < 5.0
    assert run_result.token_usage == 0
    assert run_result.cost_usd == 0.0
    assert run_result.normalized_rca.entity == "payment-service"
    assert run_result.normalized_rca.root_cause == RootCauseClass.MEMORY_LEAK

    with open(scenario_dir / "ground_truth.yaml") as f:
        ground_truth = yaml.safe_load(f)

    evaluator = F1Evaluator()
    eval_result = evaluator.evaluate(run_result.normalized_rca, ground_truth)
    assert eval_result.passed is True
    assert eval_result.status == "SUCCESS"
    assert eval_result.entity_match is True
    assert eval_result.root_cause_match is True
    assert eval_result.composite_score > 0.8


def test_behavior_intelligence_causal_ablation() -> None:
    """Ablation study proving the Behavior Intelligence causal rule drives the diagnosis.
    
    - Without behavior intelligence: IAM only sees individual metric anomalies, where
      cpu_throttled_seconds is the top finding (importance 0.86 vs 0.81), misattributing
      the symptom to CPU_STARVATION.
    - With behavior intelligence: IAM correlates memory trend + cpu throttling, correctly
      attributing the root cause to MEMORY_LEAK.
    """
    from benchmark.iam_vs_llm.evaluators.normalization import normalize_iam_findings
    from benchmark.iam_vs_llm.runners.iam_slice_runner import IsolatedInMemoryStore, StubEmbedder
    from intelligence.config import load_config
    from intelligence.pipeline import SignalPipeline
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from backend.app.models.entities import BehaviorFindingEntity

    scenario_dir = Path(__file__).resolve().parents[1] / "benchmark" / "iam_vs_llm" / "scenarios" / "scenario_01_resource_degradation"
    df = pd.read_csv(scenario_dir / "metrics.csv")

    store = IsolatedInMemoryStore()
    pipeline = SignalPipeline(load_config(scenario_dir.parents[3] / "config.yaml"), store=store, embedder=StubEmbedder())
    res = pipeline.run_dataframe(df)

    # 1. Ablated: No behavior intelligence -> blames top single-metric finding (symptom misattribution)
    ablated_rca = normalize_iam_findings(res.findings, res.signals, behavior_findings=None)
    assert ablated_rca.entity == "payment-service"
    assert ablated_rca.root_cause == RootCauseClass.CPU_STARVATION

    # 2. Causal Engine active: correlates upward memory trend + throttling -> MEMORY_LEAK
    with Session(store.engine) as session:
        bfs = list(session.scalars(select(BehaviorFindingEntity)).all())
    assert len(bfs) == 1
    assert bfs[0].definition_id == "memory_leak"

    full_rca = normalize_iam_findings(res.findings, res.signals, behavior_findings=bfs)
    assert full_rca.entity == "payment-service"
    assert full_rca.root_cause == RootCauseClass.MEMORY_LEAK


def test_state_isolation_lifecycle() -> None:
    """Verifies that state_isolation() provides real filesystem and DB isolation."""
    from benchmark.iam_vs_llm.runners.base_runner import state_isolation

    cleanup_called = False
    temp_dir_path = None

    def my_cleanup():
        nonlocal cleanup_called
        cleanup_called = True

    with state_isolation() as ctx:
        temp_dir_path = ctx.temp_dir
        assert temp_dir_path.exists()
        ctx.register_cleanup(my_cleanup)

    assert cleanup_called is True
    assert not temp_dir_path.exists()

