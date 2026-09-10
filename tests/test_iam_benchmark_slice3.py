from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from backend.app.behavior_intelligence.fact_catalog import FACT_KEYS
from benchmark.iam_vs_llm.configs.manifest_loader import BenchmarkManifest, ModelRunConfig, PricingConfig
from benchmark.iam_vs_llm.evaluators.f1_evaluator import F1EvaluationResult, F1Evaluator
from benchmark.iam_vs_llm.evaluators.judge_agreement import calculate_fleiss_kappa, calculate_krippendorff_alpha
from benchmark.iam_vs_llm.evaluators.judge_evaluator import JudgeEvaluationResult, JudgeEvaluator, JudgeScore
from benchmark.iam_vs_llm.evaluators.normalization import NormalizedRCA
from benchmark.iam_vs_llm.evaluators.taxonomy import RootCauseClass
from benchmark.iam_vs_llm.run_comparison import generate_benchmark_reports, run_benchmark_comparison
from benchmark.iam_vs_llm.runners.base_runner import BenchmarkRunResult
from benchmark.iam_vs_llm.runners.baseline_b_runner import BaselineBRunner, MockSignalsAgent
from benchmark.iam_vs_llm.runners.mock_tool_environment import MockToolEnvironment
from benchmark.iam_vs_llm.runners.react_base import BaseReActRunner, ReActExecutionResult, USER_TRIAGE_PROMPT


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def scenario_1_dir(repo_root: Path) -> Path:
    return repo_root / "benchmark" / "iam_vs_llm" / "scenarios" / "scenario_01_resource_degradation"


@pytest.fixture
def scenario_2_dir(repo_root: Path) -> Path:
    return repo_root / "benchmark" / "iam_vs_llm" / "scenarios" / "scenario_02_cascading_failure"


@pytest.fixture
def scenario_3_dir(repo_root: Path) -> Path:
    return repo_root / "benchmark" / "iam_vs_llm" / "scenarios" / "scenario_03_benign_maintenance"


# ==============================================================================
# 1. Scenarios 2 & 3 Telemetry & Artifact Validation
# ==============================================================================

def test_scenario_2_telemetry_and_artifacts(scenario_2_dir: Path) -> None:
    """Verifies that Scenario 2 contains valid telemetry, ground truth, signals, and trajectories."""
    metrics_file = scenario_2_dir / "metrics.csv"
    k8s_file = scenario_2_dir / "k8s_events.json"
    gt_file = scenario_2_dir / "ground_truth.yaml"
    signals_file = scenario_2_dir / "signals.json"
    base_a_traj = scenario_2_dir / "mock_baseline_trajectory.yaml"
    base_b_traj = scenario_2_dir / "mock_baseline_b_trajectory.yaml"

    assert metrics_file.exists()
    assert k8s_file.exists()
    assert gt_file.exists()
    assert signals_file.exists()
    assert base_a_traj.exists()
    assert base_b_traj.exists()

    # Verify ground truth
    gt = yaml.safe_load(gt_file.read_text(encoding="utf-8"))
    assert gt["entity"] == "orders-service"
    assert gt["root_cause"] == "POOL_EXHAUSTION"
    assert "db_connections_active" in gt["key_evidence"]["metrics"]

    # Verify signals
    signals = json.loads(signals_file.read_text(encoding="utf-8"))
    assert len(signals) >= 3
    order_signals = [s for s in signals if s.get("service") == "orders-service"]
    assert len(order_signals) >= 2


def test_scenario_3_telemetry_and_artifacts(scenario_3_dir: Path) -> None:
    """Verifies that Scenario 3 contains valid telemetry, ground truth, signals, and trajectories."""
    metrics_file = scenario_3_dir / "metrics.csv"
    k8s_file = scenario_3_dir / "k8s_events.json"
    gt_file = scenario_3_dir / "ground_truth.yaml"
    signals_file = scenario_3_dir / "signals.json"
    base_a_traj = scenario_3_dir / "mock_baseline_trajectory.yaml"
    base_b_traj = scenario_3_dir / "mock_baseline_b_trajectory.yaml"

    assert metrics_file.exists()
    assert k8s_file.exists()
    assert gt_file.exists()
    assert signals_file.exists()
    assert base_a_traj.exists()
    assert base_b_traj.exists()

    gt = yaml.safe_load(gt_file.read_text(encoding="utf-8"))
    assert gt["entity"] == "report-service"
    assert gt["root_cause"] == "BENIGN_MAINTENANCE"
    assert "batch_jobs_active" in gt["key_evidence"]["metrics"]


# ==============================================================================
# 2. MockToolEnvironment Signals Integration
# ==============================================================================

def test_mock_tool_environment_signals(scenario_2_dir: Path) -> None:
    """Tests list_signals method, dispatcher registration, and tool schema with include_signals."""
    env = MockToolEnvironment(scenario_2_dir)

    # 1. Unfiltered signals
    all_signals = env.list_signals()
    assert len(all_signals) >= 3

    # 2. Filtered by service
    order_signals = env.list_signals(service="orders-service")
    assert all(s["service"] == "orders-service" for s in order_signals)

    # 3. Via dispatch
    dispatched = env.dispatch("list_signals", {"service": "orders-service"})
    assert len(dispatched) == len(order_signals)

    # 4. Tool definitions schema
    raw_tools = env.get_tool_definitions(include_signals=False)
    assert len(raw_tools) == 4
    assert not any(t["function"]["name"] == "list_signals" for t in raw_tools)

    signals_tools = env.get_tool_definitions(include_signals=True)
    assert len(signals_tools) == 5
    sig_tool = next(t for t in signals_tools if t["function"]["name"] == "list_signals")
    assert "service" in sig_tool["function"]["parameters"]["properties"]


# ==============================================================================
# 3. Baseline B Runner (Signals-Augmented ReAct Agent)
# ==============================================================================

def test_baseline_b_runner_mock_execution(scenario_2_dir: Path) -> None:
    """Tests BaselineBRunner offline scripted execution on Scenario 2."""
    runner = BaselineBRunner()
    result = runner.execute(scenario_2_dir)

    assert result.runner_id.startswith("baseline_b_")
    assert result.scenario_id == "scenario_02_cascading_failure"
    assert result.normalized_rca.root_cause == RootCauseClass.POOL_EXHAUSTION
    assert result.normalized_rca.entity == "orders-service"
    assert result.token_usage > 0
    assert result.cost_usd > 0.0

    traj = result.metadata["trajectory"]
    assert len(traj) > 0
    # Turns should be strictly monotonic 1..N
    turn_indices = [t["turn"] for t in traj]
    assert turn_indices == list(range(1, len(traj) + 1))


def test_baseline_b_runner_max_turns_truncation(scenario_2_dir: Path) -> None:
    """Tests that BaselineBRunner respects max_turns budget and emits uniform partial diagnosis."""
    manifest = BenchmarkManifest(
        random_seed=42,
        state_isolation=True,
        baseline_a=ModelRunConfig("m", "mock", 0.0, 5, PricingConfig(1.0, 1.0)),
        baseline_b=ModelRunConfig(
            model_id="mock-signals-agent",
            provider="mock",
            temperature=0.0,
            max_turns=2,
            pricing=PricingConfig(2.0, 8.0),
        ),
        iam_advisor=ModelRunConfig("m", "local", 0.0, 1, PricingConfig(0.2, 0.2)),
        judge=ModelRunConfig("m", "mock", 0.0, 1, PricingConfig(2.5, 10.0)),
    )
    runner = BaselineBRunner(manifest=manifest)
    result = runner.execute(scenario_2_dir)

    assert result.normalized_rca.root_cause == RootCauseClass.UNKNOWN
    assert result.tool_iterations == 2
    traj = result.metadata["trajectory"]
    turn_indices = [t["turn"] for t in traj]
    assert turn_indices == list(range(1, len(traj) + 1))
    assert "Turn limit reached. Partial diagnosis" in traj[-1]["response"]


def test_baseline_b_runner_dynamic_fallback(tmp_path: Path, scenario_2_dir: Path) -> None:
    """Tests dynamic signals-first triage when mock_baseline_b_trajectory.yaml is absent."""
    import shutil
    shutil.copy(scenario_2_dir / "metrics.csv", tmp_path / "metrics.csv")
    shutil.copy(scenario_2_dir / "k8s_events.json", tmp_path / "k8s_events.json")
    shutil.copy(scenario_2_dir / "signals.json", tmp_path / "signals.json")

    manifest = BenchmarkManifest(
        random_seed=42,
        state_isolation=True,
        baseline_a=ModelRunConfig("m", "mock", 0.0, 5, PricingConfig(1.0, 1.0)),
        baseline_b=ModelRunConfig(
            model_id="mock-dynamic-signals",
            provider="mock",
            temperature=0.0,
            max_turns=5,
            pricing=PricingConfig(1.0, 1.0),
        ),
        iam_advisor=ModelRunConfig("m", "local", 0.0, 1, PricingConfig(0.2, 0.2)),
        judge=ModelRunConfig("m", "mock", 0.0, 1, PricingConfig(2.5, 10.0)),
    )
    runner = BaselineBRunner(manifest=manifest)
    result = runner.execute(tmp_path)

    traj = result.metadata["trajectory"]
    assert len(traj) >= 2
    # First turn must query list_signals
    assert traj[0]["tool"] == "list_signals"
    # Turns must be strictly monotonic
    assert [t["turn"] for t in traj] == list(range(1, len(traj) + 1))


def test_baseline_b_runner_openai_react_loop(scenario_1_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests live OpenAI tool-calling loop for Baseline B with list_signals."""
    manifest = BenchmarkManifest(
        random_seed=42,
        state_isolation=True,
        baseline_a=ModelRunConfig("m", "mock", 0.0, 1, PricingConfig(1.0, 1.0)),
        baseline_b=ModelRunConfig(
            model_id="gpt-4o",
            provider="openai",
            temperature=0.0,
            max_turns=3,
            pricing=PricingConfig(5.0, 15.0),
        ),
        iam_advisor=ModelRunConfig("m", "local", 0.0, 1, PricingConfig(0.2, 0.2)),
        judge=ModelRunConfig("m", "mock", 0.0, 1, PricingConfig(2.5, 10.0)),
    )
    runner = BaselineBRunner(manifest=manifest)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key")

    class FakeToolCall:
        def __init__(self, tc_id: str, name: str, args: str):
            self.id = tc_id
            self.function = MagicMock(name=name, arguments=args)
            self.function.name = name
            self.function.arguments = args

    class FakeMessage:
        def __init__(self, tool_calls=None, content=None):
            self.tool_calls = tool_calls
            self.content = content

        def to_dict(self):
            return {"role": "assistant", "content": self.content, "tool_calls": []}

    class FakeCompletion:
        def __init__(self, msg):
            self.choices = [MagicMock(message=msg)]
            self.usage = MagicMock(prompt_tokens=100, completion_tokens=50)

    t1 = FakeToolCall("tc_sig", "list_signals", '{"service": "payment-service"}')
    m1 = FakeMessage(tool_calls=[t1])
    m2 = FakeMessage(
        content=(
            "Signals indicate memory leak on payment-service.\n\n"
            "ROOT_CAUSE: MEMORY_LEAK\n"
            "ENTITY: payment-service\n"
            "WINDOW: 2026-09-07T14:30:00Z to 2026-09-07T15:45:00Z\n"
            "EVIDENCE: memory_usage, trend\n"
        )
    )

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [FakeCompletion(m1), FakeCompletion(m2)]
    mock_openai = MagicMock()
    mock_openai.OpenAI.return_value = mock_client
    monkeypatch.setitem(pytest.importorskip("sys").modules, "openai", mock_openai)

    result = runner.execute(scenario_1_dir)
    assert result.normalized_rca.root_cause == RootCauseClass.MEMORY_LEAK
    assert result.normalized_rca.entity == "payment-service"
    assert result.token_usage == 300
    assert result.tool_iterations == 1


# ==============================================================================
# 4. Statistical Agreement Metrics (Fleiss' Kappa & Krippendorff's Alpha)
# ==============================================================================

def test_calculate_fleiss_kappa_properties() -> None:
    """Tests Fleiss' kappa on perfect agreement and known matrix distributions."""
    # 1. Perfect agreement
    perfect = [[5, 5, 5], [4, 4, 4], [1, 1, 1]]
    assert calculate_fleiss_kappa(perfect, num_categories=5) == 1.0

    # 2. Degenerate empty / 1-rater edge cases
    assert calculate_fleiss_kappa([], num_categories=5) == 1.0
    assert calculate_fleiss_kappa([[5]], num_categories=5) == 1.0

    # 3. Mixed ratings
    mixed = [[1, 2, 2], [2, 2, 3], [3, 3, 3], [4, 4, 5]]
    k = calculate_fleiss_kappa(mixed, num_categories=5)
    assert -1.0 <= k <= 1.0
    assert round(k, 4) == 0.3208


def test_calculate_krippendorff_alpha_properties() -> None:
    """Tests Krippendorff's alpha reliability coefficient on ordinal data and missing values."""
    # 1. Perfect agreement
    perfect = [[5.0, 5.0, 5.0], [1.0, 1.0, 1.0]]
    assert calculate_krippendorff_alpha(perfect, level_of_measurement="ordinal") == 1.0

    # 2. Missing data support
    with_nones = [
        [1.0, 2.0, None],
        [2.0, 2.0, 3.0],
        [None, 3.0, 3.0],
    ]
    alpha = calculate_krippendorff_alpha(with_nones, level_of_measurement="ordinal")
    assert -1.0 <= alpha <= 1.0


# ==============================================================================
# 5. Calibrated Judge Evaluator
# ==============================================================================

def test_judge_evaluator_mock_deterministic(scenario_1_dir: Path) -> None:
    """Tests deterministic calibrated scoring and agreement metrics in JudgeEvaluator."""
    gt = yaml.safe_load((scenario_1_dir / "ground_truth.yaml").read_text(encoding="utf-8"))
    evaluator = JudgeEvaluator()

    # Case A: Correct diagnosis
    run_res_correct = BenchmarkRunResult(
        runner_id="test-runner",
        scenario_id="scenario_01_resource_degradation",
        normalized_rca=NormalizedRCA(
            entity="payment-service",
            root_cause=RootCauseClass.MEMORY_LEAK,
            evidence_keys=["memory_usage", "trend"],
            raw_summary="Memory leak on payment-service.",
        ),
        execution_time_seconds=0.5,
        token_usage=100,
        cost_usd=0.01,
    )
    eval_correct = evaluator.evaluate(run_res_correct, gt)
    assert eval_correct.consensus.attribution == 5
    assert eval_correct.consensus.actionability == 5
    assert eval_correct.fleiss_kappa == 1.0
    assert eval_correct.krippendorff_alpha == 1.0
    assert len(eval_correct.scores) == 3

    # Case B: False diagnosis
    run_res_wrong = BenchmarkRunResult(
        runner_id="test-runner",
        scenario_id="scenario_01_resource_degradation",
        normalized_rca=NormalizedRCA(
            entity="frontend-service",
            root_cause=RootCauseClass.DISTRIBUTED_DEADLOCK,
            evidence_keys=[],
            raw_summary="Deadlock somewhere.",
        ),
        execution_time_seconds=0.5,
        token_usage=100,
        cost_usd=0.01,
    )
    eval_wrong = evaluator.evaluate(run_res_wrong, gt)
    assert eval_wrong.consensus.attribution <= 2
    assert eval_wrong.consensus.grounding <= 2


def test_judge_evaluator_live_openai(scenario_1_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests live OpenAI judge rater sampling and JSON parsing."""
    manifest = BenchmarkManifest(
        random_seed=42,
        state_isolation=True,
        baseline_a=ModelRunConfig("m", "mock", 0.0, 1, PricingConfig(1.0, 1.0)),
        baseline_b=ModelRunConfig("m", "mock", 0.0, 1, PricingConfig(1.0, 1.0)),
        iam_advisor=ModelRunConfig("m", "local", 0.0, 1, PricingConfig(0.2, 0.2)),
        judge=ModelRunConfig(
            model_id="gpt-4o-mini",
            provider="openai",
            temperature=0.2,
            max_turns=1,
            pricing=PricingConfig(0.15, 0.60),
        ),
    )
    evaluator = JudgeEvaluator(manifest=manifest, num_raters=2)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-judge-key")

    class FakeChoice:
        def __init__(self, content):
            self.message = MagicMock(content=content)

    class FakeJudgeResp:
        def __init__(self, content):
            self.choices = [FakeChoice(content)]
            self.usage = MagicMock(prompt_tokens=200, completion_tokens=50)

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        FakeJudgeResp('{"attribution": 5, "grounding": 4, "actionability": 5, "justification": "Clear RCA"}'),
        FakeJudgeResp('{"attribution": 4, "grounding": 4, "actionability": 5, "justification": "Good evidence"}'),
    ]
    mock_openai = MagicMock()
    mock_openai.OpenAI.return_value = mock_client
    monkeypatch.setitem(pytest.importorskip("sys").modules, "openai", mock_openai)

    gt = yaml.safe_load((scenario_1_dir / "ground_truth.yaml").read_text(encoding="utf-8"))
    run_res = BenchmarkRunResult(
        runner_id="iam_slice_runner",
        scenario_id="scenario_01_resource_degradation",
        normalized_rca=NormalizedRCA(
            entity="payment-service",
            root_cause=RootCauseClass.MEMORY_LEAK,
            evidence_keys=["memory_usage"],
            raw_summary="Summary",
        ),
        execution_time_seconds=0.1,
        token_usage=0,
        cost_usd=0.0,
    )

    eval_res = evaluator.evaluate(run_res, gt)
    assert eval_res.consensus.attribution in (4, 5)
    assert eval_res.consensus.grounding == 4
    assert eval_res.consensus.actionability == 5
    assert len(eval_res.scores) == 2
    assert eval_res.token_usage == 500


# ==============================================================================
# 6. Multi-Scenario Comparison & Pareto Report Generation
# ==============================================================================

def test_run_benchmark_comparison_end_to_end(scenario_2_dir: Path) -> None:
    """Tests run_benchmark_comparison on Scenario 2 across IAM, Baseline A, and Baseline B."""
    results = run_benchmark_comparison(
        scenario_dir=scenario_2_dir,
        include_baseline_b=True,
        include_judge=True,
    )

    assert results["scenario"] == "scenario_02_cascading_failure"
    assert "iam" in results
    assert "baseline_a" in results
    assert "baseline_b" in results

    iam = results["iam"]
    base_a = results["baseline_a"]
    base_b = results["baseline_b"]

    assert iam["evaluation"].root_cause_match is True
    assert base_a["evaluation"].root_cause_match is True
    assert base_b["evaluation"].root_cause_match is True

    # Check token Pareto dominance: IAM (0) < Baseline B < Baseline A
    assert iam["run"].token_usage == 0
    assert base_b["run"].token_usage < base_a["run"].token_usage


def test_generate_benchmark_reports(tmp_path: Path, scenario_1_dir: Path, scenario_2_dir: Path) -> None:
    """Tests generating benchmark_report.md and benchmark_report.json across multiple scenarios."""
    res1 = run_benchmark_comparison(scenario_1_dir)
    res2 = run_benchmark_comparison(scenario_2_dir)

    md_path, json_path = generate_benchmark_reports([res1, res2], output_dir=tmp_path)

    assert md_path.exists()
    assert json_path.exists()

    md_text = md_path.read_text(encoding="utf-8")
    assert "# IAM vs. Agentic LLM Benchmark Report" in md_text
    assert "Executive Summary & Pareto Frontier Scorecard" in md_text
    assert "scenario_01_resource_degradation" in md_text
    assert "scenario_02_cascading_failure" in md_text
    assert "Fleiss'" in md_text
    assert "Krippendorff" in md_text

    json_data = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(json_data) == 2
    assert json_data[0]["scenario"] == "scenario_01_resource_degradation"
    assert "iam" in json_data[0]
    assert "baseline_a" in json_data[0]
    assert "baseline_b" in json_data[0]


def test_react_execution_result_contract() -> None:
    """Verifies ReActExecutionResult attributes, total_tokens, and 5-tuple unpacking compatibility."""
    res = ReActExecutionResult(
        final_text="test conclusion",
        input_tokens=100,
        output_tokens=50,
        trajectory=[{"turn": 1}],
        tool_calls_count=2,
    )
    assert res.final_text == "test conclusion"
    assert res.input_tokens == 100
    assert res.output_tokens == 50
    assert res.total_tokens == 150
    assert res.trajectory == [{"turn": 1}]
    assert res.tool_calls_count == 2

    # Backward-compatible 5-tuple unpacking
    text, in_tok, out_tok, traj, tc = res
    assert text == "test conclusion"
    assert in_tok == 100
    assert out_tok == 50
    assert traj == [{"turn": 1}]
    assert tc == 2


def test_fact_catalog_trend_present() -> None:
    """Verifies trend.present is formally registered in the behavioral fact catalog."""
    assert "trend.present" in FACT_KEYS
    assert "trend.slope" in FACT_KEYS


def test_krippendorff_alpha_subject_rater_matrix() -> None:
    """Verifies calculate_krippendorff_alpha with (num_subjects, num_raters) matrix."""
    # 3 subjects evaluated by 3 raters
    ratings = [
        [1.0, 1.0, 1.0],
        [2.0, 2.0, 2.0],
        [3.0, 3.0, 3.0],
    ]
    # Perfect agreement across all subjects
    alpha = calculate_krippendorff_alpha(ratings, level_of_measurement="ordinal")
    assert alpha == 1.0

    # With missing data (None)
    ratings_sparse = [
        [1.0, 1.0, None],
        [2.0, None, 2.0],
        [None, 3.0, 3.0],
    ]
    alpha_sparse = calculate_krippendorff_alpha(ratings_sparse, level_of_measurement="ordinal")
    assert alpha_sparse == 1.0

