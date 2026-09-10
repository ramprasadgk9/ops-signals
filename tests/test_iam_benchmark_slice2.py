from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

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
    # Objective statistics (no conclusion leakage)
    assert summary["max"] >= 900.0
    assert summary["start_value"] < summary["max"]
    assert "trend" not in summary
    assert len(data["sample_points"]) > 0

    # 1b. Single-quoted service filter
    res_sq = env.query_prometheus("memory_usage{service='payment-service'}")
    assert res_sq["status"] == "success"
    assert res_sq["data"]["service"] == "payment-service"
    assert res_sq["data"]["summary"]["max"] == summary["max"]

    # 2. Window-filtered query
    res_window = env.query_prometheus(
        'memory_usage{service="payment-service"}',
        start_time="2026-09-07T10:30:00+00:00",
        end_time="2026-09-07T11:00:00+00:00",
    )
    assert res_window["status"] == "success"
    assert res_window["data"]["summary"]["point_count"] < summary["point_count"]

    # 3. Resampling with step
    res_step_5m = env.query_prometheus('memory_usage{service="payment-service"}', step="5m")
    res_step_30m = env.query_prometheus('memory_usage{service="payment-service"}', step="30m")
    assert len(res_step_30m["data"]["sample_points"]) < len(res_step_5m["data"]["sample_points"])

    # 4. Non-existent metric
    res_empty = env.query_prometheus("non_existent_metric")
    assert res_empty["status"] == "success"
    assert res_empty["data"]["result"] == []

    # 5. Malformed query
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
    
    # Exposes step parameter
    prom_tool = next(t for t in tools if t["function"]["name"] == "query_prometheus")
    assert "step" in prom_tool["function"]["parameters"]["properties"]


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


def test_baseline_a_runner_max_turns_truncation(scenario_dir: Path) -> None:
    """Verifies that MockSREAgent respects max_turns budget and emits early UNKNOWN diagnosis."""
    manifest = load_manifest()
    truncated_config = ModelRunConfig(
        model_id="mock-frontier-sre",
        provider="mock",
        temperature=0.0,
        max_turns=2,  # Truncate after 2 turns
        pricing=manifest.baseline_a.pricing,
    )
    manifest.baseline_a = truncated_config
    runner = BaselineARunner(manifest=manifest)
    result = runner.run_react_agent(scenario_dir)

    assert result.normalized_rca.root_cause == RootCauseClass.UNKNOWN
    assert result.tool_iterations == 2
    assert "Turn limit reached" in result.normalized_rca.raw_summary


def test_baseline_a_runner_unsupported_provider(scenario_dir: Path) -> None:
    manifest = load_manifest()
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


def test_baseline_a_runner_openai_react_loop_and_error_recovery(
    monkeypatch: pytest.MonkeyPatch,
    scenario_dir: Path,
) -> None:
    """Tests live OpenAI execution loop, verifying:
    1. Multi-turn tool execution
    2. Malformed JSON argument handling (recovery without crashing)
    3. Unknown tool call handling
    4. Token usage accounting
    5. Trajectory recording
    """
    manifest = load_manifest()
    manifest.baseline_a = ModelRunConfig(
        model_id="gpt-4o-stub",
        provider="openai",
        temperature=0.0,
        max_turns=5,
        pricing=manifest.baseline_a.pricing,
    )
    runner = BaselineARunner(manifest=manifest)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-mock")

    # Helper mock classes for OpenAI responses
    class FakeUsage:
        prompt_tokens = 100
        completion_tokens = 30

    class FakeFunction:
        def __init__(self, name: str, arguments: str):
            self.name = name
            self.arguments = arguments

    class FakeToolCall:
        def __init__(self, id: str, name: str, arguments: str):
            self.id = id
            self.function = FakeFunction(name, arguments)

    class FakeMessage:
        def __init__(self, content: str | None, tool_calls: list[Any] | None = None):
            self.content = content
            self.tool_calls = tool_calls or []

        def to_dict(self) -> dict[str, Any]:
            return {
                "role": "assistant",
                "content": self.content,
                "tool_calls": [
                    {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in self.tool_calls
                ],
            }

    class FakeChoice:
        def __init__(self, message: FakeMessage):
            self.message = message

    class FakeCompletion:
        def __init__(self, message: FakeMessage):
            self.choices = [FakeChoice(message)]
            self.usage = FakeUsage()

    # Turn sequence:
    # Turn 1: Valid tool call `list_services`
    # Turn 2: Tool call with malformed JSON arguments
    # Turn 3: Tool call with unknown function name
    # Turn 4: Final response with structured tail
    responses = [
        FakeCompletion(FakeMessage(
            content=None,
            tool_calls=[FakeToolCall("call_1", "list_services", "{}")],
        )),
        FakeCompletion(FakeMessage(
            content=None,
            tool_calls=[FakeToolCall("call_2", "query_prometheus", "{invalid_json,")],
        )),
        FakeCompletion(FakeMessage(
            content=None,
            tool_calls=[FakeToolCall("call_3", "nonexistent_tool", '{"foo": "bar"}')],
        )),
        FakeCompletion(FakeMessage(
            content=(
                "Analysis complete.\n\n"
                "ROOT_CAUSE: MEMORY_LEAK\n"
                "ENTITY: payment-service\n"
                "WINDOW: 2026-09-07T10:30:00Z to 2026-09-07T11:45:00Z\n"
                "EVIDENCE: memory_usage, cpu_throttled_seconds, trend"
            ),
            tool_calls=None,
        )),
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = responses

    mock_openai_module = MagicMock()
    mock_openai_module.OpenAI.return_value = mock_client
    monkeypatch.setitem(pytest.importorskip("sys").modules, "openai", mock_openai_module)

    result = runner.run_react_agent(scenario_dir)

    assert result.runner_id == "baseline_a_gpt-4o-stub"
    assert result.normalized_rca.root_cause == RootCauseClass.MEMORY_LEAK
    assert result.normalized_rca.entity == "payment-service"
    assert result.tool_iterations == 3
    # 4 responses * 130 tokens per response
    assert result.token_usage == 4 * 130
    assert result.cost_usd > 0.0

    # Verify trajectory captured turns and error recovery
    traj = result.metadata["trajectory"]
    assert len(traj) == 4
    # Turn 2 handled malformed json gracefully
    assert "Invalid JSON" in str(traj[1]["tool_output"])
    # Turn 3 handled unknown tool gracefully
    assert "Unknown tool" in str(traj[2]["tool_output"])


def test_baseline_a_runner_openai_max_turns_truncation(
    monkeypatch: pytest.MonkeyPatch,
    scenario_dir: Path,
) -> None:
    """Verifies that reaching max_turns in OpenAI loop triggers forced summary and records it."""
    manifest = load_manifest()
    manifest.baseline_a = ModelRunConfig(
        model_id="gpt-4o-stub",
        provider="openai",
        temperature=0.0,
        max_turns=2,
        pricing=manifest.baseline_a.pricing,
    )
    runner = BaselineARunner(manifest=manifest)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-mock")

    class FakeUsage:
        prompt_tokens = 50
        completion_tokens = 20

    class FakeToolCall:
        id = "call_loop"
        function = MagicMock(name="list_services", arguments="{}")

    class FakeMessage:
        content = None
        tool_calls = [FakeToolCall()]
        def to_dict(self):
            return {"role": "assistant", "content": None, "tool_calls": []}

    class FakeCompletion:
        def __init__(self, content=None, is_tool=True):
            if is_tool:
                self.choices = [MagicMock(message=FakeMessage())]
            else:
                self.choices = [MagicMock(message=MagicMock(content=content))]
            self.usage = FakeUsage()

    # 2 turns requesting tools, then 1 forced completion response
    responses = [
        FakeCompletion(is_tool=True),
        FakeCompletion(is_tool=True),
        FakeCompletion(content="Forced termination response.\nROOT_CAUSE: UNKNOWN\nENTITY: unknown", is_tool=False),
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = responses
    mock_openai_module = MagicMock()
    mock_openai_module.OpenAI.return_value = mock_client
    monkeypatch.setitem(pytest.importorskip("sys").modules, "openai", mock_openai_module)

    result = runner.run_react_agent(scenario_dir)

    assert result.normalized_rca.root_cause == RootCauseClass.UNKNOWN
    traj = result.metadata["trajectory"]
    # 2 tool turns + 1 forced summary turn
    assert len(traj) == 3
    assert "Turn limit reached" in traj[-1]["thought"]


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


def test_baseline_a_runner_openai_non_dict_arguments_recovery(
    scenario_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies that non-dict JSON tool arguments (e.g. primitive '123') are gracefully recovered."""
    from unittest.mock import MagicMock
    from benchmark.iam_vs_llm.configs.manifest_loader import BenchmarkManifest, ModelRunConfig, PricingConfig
    from benchmark.iam_vs_llm.runners.baseline_a_runner import BaselineARunner

    manifest = BenchmarkManifest(
        random_seed=42,
        state_isolation=True,
        baseline_a=ModelRunConfig(
            model_id="mock-frontier-sre",
            provider="openai",
            temperature=0.0,
            max_turns=3,
            pricing=PricingConfig(input_per_mtok=3.0, output_per_mtok=15.0),
        ),
        baseline_b=ModelRunConfig("m", "mock", 0.0, 1, PricingConfig(1.0, 1.0)),
        iam_advisor=ModelRunConfig("m", "local", 0.0, 1, PricingConfig(0.2, 0.2)),
        judge=ModelRunConfig("m", "mock", 0.0, 1, PricingConfig(2.5, 10.0)),
    )
    runner = BaselineARunner(manifest=manifest)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

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
            self.usage = MagicMock(prompt_tokens=50, completion_tokens=25)

    # First turn: model emits primitive integer argument '123' to list_metrics
    # Second turn: model recovers and emits diagnosis
    t1 = FakeToolCall("tc_1", "list_metrics", "123")
    m1 = FakeMessage(tool_calls=[t1])
    m2 = FakeMessage(content="Recovery complete.\nROOT_CAUSE: UNKNOWN\nENTITY: payment-service")

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [FakeCompletion(m1), FakeCompletion(m2)]
    mock_openai_module = MagicMock()
    mock_openai_module.OpenAI.return_value = mock_client
    monkeypatch.setitem(pytest.importorskip("sys").modules, "openai", mock_openai_module)

    result = runner.run_react_agent(scenario_dir)
    assert result.normalized_rca.entity == "payment-service"
    # Trajectory should record error gracefully without crash
    assert result.tool_iterations == 1
    traj = result.metadata["trajectory"]
    assert "error" in traj[0]["tool_output"]
    assert "Invalid JSON arguments" in traj[0]["tool_output"]["error"]


def test_base_benchmark_runner_polymorphic_execute(scenario_dir: Path) -> None:
    """Verifies that BaseBenchmarkRunner.execute() functions polymorphically on both runners."""
    from benchmark.iam_vs_llm.runners.base_runner import BaseBenchmarkRunner
    from benchmark.iam_vs_llm.runners.iam_slice_runner import IAMSliceRunner
    from benchmark.iam_vs_llm.runners.baseline_a_runner import BaselineARunner

    iam_runner: BaseBenchmarkRunner = IAMSliceRunner()
    assert iam_runner.get_query_environment(scenario_dir) is None
    iam_res = iam_runner.execute(scenario_dir)
    assert iam_res.token_usage == 0
    assert iam_res.scenario_id == scenario_dir.name

    base_runner: BaseBenchmarkRunner = BaselineARunner()
    assert base_runner.get_query_environment(scenario_dir) is not None
    base_res = base_runner.execute(scenario_dir)
    assert base_res.token_usage > 0
    assert base_res.scenario_id == scenario_dir.name


def test_mock_sre_agent_dynamic_trajectory_budget(tmp_path: Path, scenario_dir: Path) -> None:
    """Verifies that MockSREAgent._run_dynamic_trajectory enforces max_turns and tracks tools."""
    import shutil
    from benchmark.iam_vs_llm.configs.manifest_loader import ModelRunConfig, PricingConfig
    from benchmark.iam_vs_llm.runners.baseline_a_runner import MockSREAgent
    from benchmark.iam_vs_llm.runners.mock_tool_environment import MockToolEnvironment

    # Create scenario without mock_baseline_trajectory.yaml to force dynamic trajectory
    dyn_dir = tmp_path / "dyn_scenario"
    dyn_dir.mkdir()
    shutil.copy(scenario_dir / "metrics.csv", dyn_dir / "metrics.csv")
    shutil.copy(scenario_dir / "k8s_events.json", dyn_dir / "k8s_events.json")

    env = MockToolEnvironment(dyn_dir)
    config = ModelRunConfig(
        model_id="mock-frontier-sre",
        provider="mock",
        temperature=0.0,
        max_turns=2,
        pricing=PricingConfig(3.0, 15.0),
    )
    agent = MockSREAgent(env=env, config=config, scenario_dir=dyn_dir)

    final_text, in_tok, out_tok, traj, tool_calls = agent.run(max_turns=2)
    assert "Turn limit reached" in final_text or "ROOT_CAUSE: UNKNOWN" in final_text
    assert tool_calls <= 2
    assert len(traj) <= 3


def test_mock_tool_environment_get_dispatcher(scenario_dir: Path) -> None:
    """Verifies that MockToolEnvironment provides a canonical callable dispatcher."""
    env = MockToolEnvironment(scenario_dir)
    dispatcher = env.get_dispatcher()
    assert set(dispatcher.keys()) == {"list_services", "list_metrics", "query_prometheus", "query_k8s_events"}
    services = dispatcher["list_services"]({})
    assert "payment-service" in services


def test_baseline_a_runner_openai_tool_execution_error_separation(
    scenario_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies that internal tool execution exceptions are not mislabeled as JSON parse errors."""
    from unittest.mock import MagicMock
    from benchmark.iam_vs_llm.configs.manifest_loader import BenchmarkManifest, ModelRunConfig, PricingConfig
    from benchmark.iam_vs_llm.runners.baseline_a_runner import BaselineARunner

    manifest = BenchmarkManifest(
        random_seed=42,
        state_isolation=True,
        baseline_a=ModelRunConfig(
            model_id="mock-frontier-sre",
            provider="openai",
            temperature=0.0,
            max_turns=2,
            pricing=PricingConfig(3.0, 15.0),
        ),
        baseline_b=ModelRunConfig("m", "mock", 0.0, 1, PricingConfig(1.0, 1.0)),
        iam_advisor=ModelRunConfig("m", "local", 0.0, 1, PricingConfig(0.2, 0.2)),
        judge=ModelRunConfig("m", "mock", 0.0, 1, PricingConfig(2.5, 10.0)),
    )
    runner = BaselineARunner(manifest=manifest)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

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
            self.usage = MagicMock(prompt_tokens=50, completion_tokens=25)

    # Valid JSON args, but we mock the tool dispatcher to raise a runtime exception
    t1 = FakeToolCall("tc_1", "query_prometheus", '{"query": "broken"}')
    m1 = FakeMessage(tool_calls=[t1])
    m2 = FakeMessage(content="Recovery.\nROOT_CAUSE: UNKNOWN\nENTITY: payment-service")

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [FakeCompletion(m1), FakeCompletion(m2)]
    mock_openai_module = MagicMock()
    mock_openai_module.OpenAI.return_value = mock_client
    monkeypatch.setitem(pytest.importorskip("sys").modules, "openai", mock_openai_module)

    # Patch env.get_dispatcher to throw an error on query_prometheus
    orig_get_env = runner.get_query_environment

    def patched_get_env(s_dir):
        real_env = orig_get_env(s_dir)
        orig_disp = real_env.get_dispatcher()
        orig_disp["query_prometheus"] = MagicMock(side_effect=RuntimeError("Database connection lost"))
        real_env.get_dispatcher = lambda: orig_disp
        return real_env

    monkeypatch.setattr(runner, "get_query_environment", patched_get_env)

    result = runner.run_react_agent(scenario_dir)
    traj = result.metadata["trajectory"]
    assert "Tool execution failed: Database connection lost" in traj[0]["tool_output"]["error"]


def test_baseline_a_runner_openrouter_provider_isolation(
    scenario_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies that OpenRouter provider resolves canonical endpoint and isolates from OPENAI_BASE_URL."""
    from unittest.mock import MagicMock
    from benchmark.iam_vs_llm.configs.manifest_loader import BenchmarkManifest, ModelRunConfig, PricingConfig
    from benchmark.iam_vs_llm.runners.baseline_a_runner import BaselineARunner

    manifest = BenchmarkManifest(
        random_seed=42,
        state_isolation=True,
        baseline_a=ModelRunConfig(
            model_id="anthropic/claude-3.5-sonnet",
            provider="openrouter",
            temperature=0.0,
            max_turns=1,
            pricing=PricingConfig(3.0, 15.0),
        ),
        baseline_b=ModelRunConfig("m", "mock", 0.0, 1, PricingConfig(1.0, 1.0)),
        iam_advisor=ModelRunConfig("m", "local", 0.0, 1, PricingConfig(0.2, 0.2)),
        judge=ModelRunConfig("m", "mock", 0.0, 1, PricingConfig(2.5, 10.0)),
    )
    runner = BaselineARunner(manifest=manifest)

    # Set both OpenRouter and OpenAI variables
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-should-be-ignored")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11434/v1")  # local proxy that must NOT be used

    mock_openai_cls = MagicMock()
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client

    class FakeMessage:
        tool_calls = None
        content = "Diagnosis.\nROOT_CAUSE: UNKNOWN\nENTITY: payment-service"

    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=FakeMessage())],
        usage=MagicMock(prompt_tokens=100, completion_tokens=50),
    )

    fake_openai_mod = MagicMock(OpenAI=mock_openai_cls)
    monkeypatch.setitem(pytest.importorskip("sys").modules, "openai", fake_openai_mod)

    runner.run_react_agent(scenario_dir)

    # Verify OpenAI client initialization arguments
    mock_openai_cls.assert_called_once_with(
        api_key="sk-or-test-key",
        base_url="https://openrouter.ai/api/v1",
    )


def test_manifest_loader_name_overrides(tmp_path: Path) -> None:
    """Verifies that user name overrides in YAML for all model configs are respected."""
    manifest_yaml = tmp_path / "custom_names_manifest.yaml"
    manifest_yaml.write_text(
        """
harness:
  random_seed: 99
  state_isolation: true

baselines:
  baseline_a:
    name: "Custom Baseline A"
    model_id: "test-model-a"
  baseline_b:
    name: "Custom Baseline B"
    model_id: "test-model-b"

iam_system:
  name: "Custom IAM Advisor"
  advisor_model_id: "test-iam-advisor"

judge:
  name: "Custom Panel Judge"
  model_id: "test-judge"
"""
    )
    manifest = load_manifest(manifest_yaml)
    assert manifest.baseline_a.name == "Custom Baseline A"
    assert manifest.baseline_b.name == "Custom Baseline B"
    assert manifest.iam_advisor.name == "Custom IAM Advisor"
    assert manifest.judge.name == "Custom Panel Judge"


