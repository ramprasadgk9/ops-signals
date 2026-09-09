from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from benchmark.iam_vs_llm.configs.manifest_loader import (
    BenchmarkManifest,
    ModelRunConfig,
    PricingConfig,
    load_manifest,
)
from benchmark.iam_vs_llm.evaluators.taxonomy import RootCauseClass
from benchmark.iam_vs_llm.run_comparison import run_benchmark_comparison
from benchmark.iam_vs_llm.runners.baseline_a_runner import BaselineARunner
from benchmark.iam_vs_llm.runners.mock_tool_environment import MockToolEnvironment


@pytest.fixture
def scenario_dir() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    path = repo_root / "benchmark" / "iam_vs_llm" / "scenarios" / "scenario_01_resource_degradation"
    assert path.exists()
    return path


def test_mock_tool_environment_services_and_metrics(scenario_dir: Path) -> None:
    env = MockToolEnvironment(scenario_dir)

    services = env.list_services()
    assert services == ["auth-service", "payment-service"]

    payment_metrics = env.list_metrics("payment-service")
    assert "memory_usage" in payment_metrics
    assert "cpu_throttled_seconds" in payment_metrics
    assert "cpu_usage" in payment_metrics

    auth_metrics = env.list_metrics("auth-service")
    assert "memory_usage" in auth_metrics


def test_mock_tool_environment_prometheus_queries(scenario_dir: Path) -> None:
    env = MockToolEnvironment(scenario_dir)

    # 1. Standard query with service filter
    res = env.query_prometheus('memory_usage{service="payment-service"}')
    assert res["status"] == "success"
    data = res["data"]
    assert data["metric"] == "memory_usage"
    assert data["service"] == "payment-service"
    summary = data["summary"]
    assert summary["trend"] == "upward"
    assert summary["max"] >= 900.0
    assert len(data["sample_points"]) > 0

    # 2. Window-filtered query
    res_window = env.query_prometheus(
        'memory_usage{service="payment-service"}',
        start_time="2026-09-07T10:30:00+00:00",
        end_time="2026-09-07T11:00:00+00:00",
    )
    assert res_window["status"] == "success"
    assert res_window["data"]["summary"]["point_count"] < summary["point_count"]

    # 3. Non-existent metric
    res_empty = env.query_prometheus("non_existent_metric")
    assert res_empty["status"] == "success"
    assert res_empty["data"]["result"] == []

    # 4. Malformed query
    res_malformed = env.query_prometheus("!!invalid!!")
    assert res_malformed["status"] == "error"


def test_mock_tool_environment_k8s_events(scenario_dir: Path) -> None:
    env = MockToolEnvironment(scenario_dir)

    all_events = env.query_k8s_events()
    assert len(all_events) >= 1

    oom_events = env.query_k8s_events(service="payment-service", event_type="OOMKilled")
    assert len(oom_events) == 1
    assert oom_events[0]["service"] == "payment-service"
    assert "1000Mi" in oom_events[0]["message"]

    auth_events = env.query_k8s_events(service="auth-service")
    assert len(auth_events) == 0


def test_mock_tool_definitions_schema(scenario_dir: Path) -> None:
    env = MockToolEnvironment(scenario_dir)
    tools = env.get_tool_definitions()

    assert len(tools) == 4
    tool_names = {t["function"]["name"] for t in tools}
    assert tool_names == {"list_services", "list_metrics", "query_prometheus", "query_k8s_events"}
    for tool in tools:
        assert tool["type"] == "function"
        assert "description" in tool["function"]
        assert "parameters" in tool["function"]


def test_pricing_config_calculation() -> None:
    pricing = PricingConfig(input_per_mtok=3.00, output_per_mtok=15.00)
    # 1,000,000 input ($3.00) + 1,000,000 output ($15.00) = $18.00
    cost = pricing.calculate_cost(1_000_000, 1_000_000)
    assert cost == 18.00

    # Small numbers: 10,000 in, 1,000 out
    cost_small = pricing.calculate_cost(10_000, 1_000)
    expected = (10_000 / 1e6) * 3.00 + (1_000 / 1e6) * 15.00
    assert cost_small == round(expected, 6)


def test_manifest_loader_env_expansion(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manifest_yaml = tmp_path / "test_manifest.yaml"
    manifest_yaml.write_text(
        """
harness:
  random_seed: 99
  state_isolation: true

baselines:
  baseline_a:
    model_id: "${CUSTOM_MODEL:-default-model}"
    provider: "${CUSTOM_PROVIDER:-mock}"
    pricing_per_mtok:
      input: 5.00
      output: 20.00
  baseline_b:
    model_id: "b-model"
    provider: "mock"
    pricing_per_mtok:
      input: 5.00
      output: 20.00

iam_system:
  advisor_model_id: "advisor"
  provider: "local"

judge:
  model_id: "judge"
  provider: "mock"
""",
        encoding="utf-8",
    )

    # 1. Default fallback without env var
    manifest = load_manifest(manifest_yaml)
    assert manifest.random_seed == 99
    assert manifest.baseline_a.model_id == "default-model"
    assert manifest.baseline_a.provider == "mock"

    # 2. Dynamic override via env var
    monkeypatch.setenv("CUSTOM_MODEL", "gpt-4o-custom")
    monkeypatch.setenv("CUSTOM_PROVIDER", "openai")
    manifest_custom = load_manifest(manifest_yaml)
    assert manifest_custom.baseline_a.model_id == "gpt-4o-custom"
    assert manifest_custom.baseline_a.provider == "openai"


def test_baseline_a_runner_mock_execution(scenario_dir: Path) -> None:
    runner = BaselineARunner()
    result = runner.run_react_agent(scenario_dir)

    assert result.runner_id == f"baseline_a_{runner.config.model_id}"
    assert result.scenario_id == scenario_dir.name
    assert result.execution_time_seconds < 1.0
    assert result.token_usage > 0
    assert result.cost_usd > 0.0
    assert result.tool_iterations >= 5

    # Check normalized RCA parsed from structured tail
    rca = result.normalized_rca
    assert rca.entity == "payment-service"
    assert rca.root_cause == RootCauseClass.MEMORY_LEAK
    assert rca.fault_window is not None
    assert "memory_usage" in rca.evidence_keys
    assert "cpu_throttled_seconds" in rca.evidence_keys
    assert "trend" in rca.evidence_keys

    # Check trajectory metadata
    meta = result.metadata
    assert meta["model_id"] == runner.config.model_id
    assert meta["provider"] == "mock"
    assert meta["input_tokens"] > 0
    assert meta["output_tokens"] > 0
    assert len(meta["trajectory"]) == 6


def test_baseline_a_runner_unsupported_provider(scenario_dir: Path) -> None:
    manifest = load_manifest()
    # Create copy of config with unsupported provider
    unsupported_config = ModelRunConfig(
        model_id="test",
        provider="unsupported_provider",
        temperature=0.0,
        max_turns=5,
        pricing=manifest.baseline_a.pricing,
    )
    manifest.baseline_a = unsupported_config
    runner = BaselineARunner(manifest=manifest)

    with pytest.raises(ValueError, match="Unsupported provider"):
        runner.run_react_agent(scenario_dir)


def test_baseline_a_runner_missing_api_key(monkeypatch: pytest.MonkeyPatch, scenario_dir: Path) -> None:
    manifest = load_manifest()
    openai_config = ModelRunConfig(
        model_id="gpt-4o",
        provider="openai",
        temperature=0.0,
        max_turns=5,
        pricing=manifest.baseline_a.pricing,
    )
    manifest.baseline_a = openai_config
    runner = BaselineARunner(manifest=manifest)

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("BENCHMARK_LLM_API_KEY", raising=False)

    with pytest.raises(ValueError, match="API key missing"):
        runner.run_react_agent(scenario_dir)


def test_comparative_benchmark_end_to_end(scenario_dir: Path) -> None:
    results = run_benchmark_comparison(scenario_dir=scenario_dir)

    assert results["scenario"] == scenario_dir.name
    iam_eval = results["iam"]["evaluation"]
    base_a_eval = results["baseline_a"]["evaluation"]

    # Both systems should achieve SUCCESS status on Scenario 1
    assert iam_eval.passed is True
    assert iam_eval.status == "SUCCESS"
    assert iam_eval.entity_match is True
    assert iam_eval.root_cause_match is True

    assert base_a_eval.passed is True
    assert base_a_eval.status == "SUCCESS"
    assert base_a_eval.entity_match is True
    assert base_a_eval.root_cause_match is True

    # Cost-Accuracy Pareto verification:
    # IAM achieved SUCCESS with 0 tokens and $0.00 cost
    iam_run = results["iam"]["run"]
    base_a_run = results["baseline_a"]["run"]

    assert iam_run.token_usage == 0
    assert iam_run.cost_usd == 0.0

    assert base_a_run.token_usage > 0
    assert base_a_run.cost_usd > 0.0
    assert base_a_run.tool_iterations >= 5
