from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from benchmark.iam_vs_llm.configs.manifest_loader import BenchmarkManifest, ModelRunConfig, load_manifest
from benchmark.iam_vs_llm.evaluators.normalization import NormalizedRCA, normalize_structured_text
from benchmark.iam_vs_llm.runners.base_runner import BaseBenchmarkRunner, BenchmarkRunResult, state_isolation
from benchmark.iam_vs_llm.runners.mock_tool_environment import MockToolEnvironment
from benchmark.iam_vs_llm.runners.react_base import (
    BaseMockReActAgent,
    ReActExecutionResult,
    run_live_openai_react_loop,
)


SYSTEM_PROMPT_SIGNALS = """You are a Principal Site Reliability Engineer (SRE) tasked with triaging an ongoing production incident.
You have access to tools allowing you to list services, list Prometheus metrics, query PromQL time-series metrics, query Kubernetes cluster events, AND query extracted operational signals (anomalies, change points, threshold breaches) across services.

Investigate methodically:
1. Inspect operational signals via `list_signals` to quickly identify services exhibiting anomalous behavior.
2. Correlate detected signals with Kubernetes events and raw Prometheus metrics.
3. Distinguish root causes from downstream symptoms.
4. Synthesize your findings into a definitive root cause diagnosis.

When your investigation is complete, you MUST conclude your response with the following structured block:
ROOT_CAUSE: <one of MEMORY_LEAK, CPU_STARVATION, CONFIG_REGRESSION, POOL_EXHAUSTION, DISTRIBUTED_DEADLOCK, BENIGN_MAINTENANCE, UNKNOWN>
ENTITY: <service_name>
WINDOW: <start_iso_timestamp> to <end_iso_timestamp>
EVIDENCE: <comma_separated_metric_or_signal_names>
"""

USER_TRIAGE_PROMPT = """High latency alerts and pod instability have been reported in the cluster over the last two hours.
Investigate the cluster telemetry and determine the root cause, affected entity, fault window, and key evidence.
"""


class MockSignalsAgent(BaseMockReActAgent):
    """Deterministic simulated Signals-Augmented SRE agent for offline, zero-token CI testing.
    
    Executes a scenario-driven or dynamically derived ReAct sequence equipped with
    both raw observability tools and the list_signals tool against MockToolEnvironment.
    """

    default_script_name: str = "mock_baseline_b_trajectory.yaml"

    def _run_dynamic_trajectory(self, max_turns: int) -> ReActExecutionResult:
        """Dynamic signals-first fallback when no pre-recorded scenario script is present."""
        trajectory: list[dict[str, Any]] = []
        total_in_tokens = 0
        total_out_tokens = 0
        tool_calls_count = 0
        current_history_tokens = 220
        turn = 0

        # Turn 1: list_signals
        turn += 1
        if turn > max_turns:
            return self._terminate_turn_limit(
                trajectory, tool_calls_count, "unknown-service", total_in_tokens, total_out_tokens
            )

        signals = self.env.dispatch("list_signals")
        if isinstance(signals, dict) and "error" in signals:
            signals = []
        tool_calls_count += 1
        trajectory.append({
            "turn": len(trajectory) + 1,
            "thought": "Querying extracted operational signals to identify candidate anomalies.",
            "tool": "list_signals",
            "tool_input": {},
            "tool_output": signals,
        })
        current_history_tokens += 120
        total_in_tokens += current_history_tokens
        total_out_tokens += 50

        # Identify primary culprit service from signals (highest severity)
        target_service = "unknown-service"
        target_metric = None
        if signals:
            sorted_sig = sorted(signals, key=lambda s: s.get("confidence", 0.0), reverse=True)
            top_sig = sorted_sig[0]
            target_service = top_sig.get("service", "unknown-service")
            target_metric = top_sig.get("metric_name")

        # Turn 2: inspect Prometheus metric or k8s events for that service
        if turn < max_turns:
            turn += 1
            if target_metric:
                query_str = f'{target_metric}{{service="{target_service}"}}'
                res = self.env.dispatch("query_prometheus", {"query": query_str})
                tool_calls_count += 1
                trajectory.append({
                    "turn": len(trajectory) + 1,
                    "thought": f"Validating raw metric {target_metric} on {target_service}.",
                    "tool": "query_prometheus",
                    "tool_input": {"query": query_str},
                    "tool_output": res,
                })
            else:
                k8s_res = self.env.dispatch("query_k8s_events", {"service": target_service})
                tool_calls_count += 1
                trajectory.append({
                    "turn": len(trajectory) + 1,
                    "thought": f"Checking Kubernetes events for {target_service}.",
                    "tool": "query_k8s_events",
                    "tool_input": {"service": target_service},
                    "tool_output": k8s_res,
                })
            current_history_tokens += 85
            total_in_tokens += current_history_tokens
            total_out_tokens += 40

        if turn >= max_turns:
            return self._terminate_turn_limit(
                trajectory, tool_calls_count, target_service, total_in_tokens, total_out_tokens
            )

        final_text = (
            f"Investigation Complete for {target_service}.\n\n"
            f"ROOT_CAUSE: UNKNOWN\n"
            f"ENTITY: {target_service}\n"
        )
        trajectory.append({
            "turn": len(trajectory) + 1,
            "thought": "Dynamic signals fallback synthesis complete.",
            "response": final_text,
        })
        return ReActExecutionResult(
            final_text=final_text,
            input_tokens=total_in_tokens,
            output_tokens=total_out_tokens,
            trajectory=trajectory,
            tool_calls_count=tool_calls_count,
        )


class BaselineBRunner(BaseBenchmarkRunner):
    """Executes Baseline B: Signals-Augmented LLM ReAct Agent interacting with query tools and list_signals."""

    def __init__(self, manifest: BenchmarkManifest | None = None) -> None:
        super().__init__(runner_id="baseline_b_signals_react")
        self.manifest = manifest or load_manifest()
        self.config = self.manifest.baseline_b

    def get_query_environment(self, scenario_dir: Path) -> MockToolEnvironment:
        return MockToolEnvironment(scenario_dir)

    def execute(self, scenario_dir: Path) -> BenchmarkRunResult:
        """Polymorphic execution entrypoint; runs the signals-augmented ReAct agent."""
        return self.run_react_agent(scenario_dir)

    def run_react_agent(self, scenario_dir: Path) -> BenchmarkRunResult:
        scenario_id = scenario_dir.name
        env = self.get_query_environment(scenario_dir)

        with state_isolation() as ctx:
            start_time = time.perf_counter()

            provider = self.config.provider.lower().strip()
            if provider == "mock":
                agent = MockSignalsAgent(env=env, config=self.config, scenario_dir=scenario_dir)
                exec_res = agent.run(max_turns=self.config.max_turns)
            elif provider in ("openai", "openrouter"):
                exec_res = self._run_openai_react(env=env, config=self.config)
            else:
                raise ValueError(
                    f"Unsupported provider '{self.config.provider}'. "
                    f"Supported providers: 'mock', 'openai', 'openrouter'."
                )

            duration = time.perf_counter() - start_time
            normalized_rca = normalize_structured_text(exec_res.final_text)
            cost_usd = self.config.pricing.calculate_cost(exec_res.input_tokens, exec_res.output_tokens)

            return BenchmarkRunResult(
                runner_id=f"baseline_b_{self.config.model_id}",
                scenario_id=scenario_id,
                normalized_rca=normalized_rca,
                execution_time_seconds=round(duration, 4),
                token_usage=exec_res.total_tokens,
                cost_usd=cost_usd,
                tool_iterations=exec_res.tool_calls_count,
                metadata={
                    "model_id": self.config.model_id,
                    "provider": self.config.provider,
                    "input_tokens": exec_res.input_tokens,
                    "output_tokens": exec_res.output_tokens,
                    "trajectory_turns": len(exec_res.trajectory),
                    "trajectory": exec_res.trajectory,
                },
            )

    def _run_openai_react(
        self,
        env: MockToolEnvironment,
        config: ModelRunConfig,
    ) -> ReActExecutionResult:
        """Executes a live OpenAI/OpenRouter tool-calling loop equipped with list_signals."""
        return run_live_openai_react_loop(
            env=env,
            config=config,
            system_prompt=SYSTEM_PROMPT_SIGNALS,
            user_prompt=USER_TRIAGE_PROMPT,
            include_signals=True,
        )
