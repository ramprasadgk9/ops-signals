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
    BaseReActRunner,
    ReActExecutionResult,
    USER_TRIAGE_PROMPT,
    run_live_openai_react_loop,
)


SYSTEM_PROMPT = """You are a Principal Site Reliability Engineer (SRE) tasked with triaging an ongoing production incident.
You have access to tools allowing you to list services, list Prometheus metrics, query PromQL time-series metrics, and query Kubernetes cluster events.

Investigate methodically:
1. Discover active services in the cluster.
2. Check recent Kubernetes events for anomalies, crashes, or pod terminations.
3. Query metric time-series to identify leading anomalies versus downstream symptoms.
4. Synthesize your findings into a definitive root cause diagnosis.

When your investigation is complete, you MUST conclude your response with the following structured block:
ROOT_CAUSE: <one of MEMORY_LEAK, CPU_STARVATION, CONFIG_REGRESSION, POOL_EXHAUSTION, DISTRIBUTED_DEADLOCK, BENIGN_MAINTENANCE, UNKNOWN>
ENTITY: <service_name>
WINDOW: <start_iso_timestamp> to <end_iso_timestamp>
EVIDENCE: <comma_separated_metric_or_signal_names>
"""


class MockSREAgent(BaseMockReActAgent):
    """Deterministic simulated SRE agent for offline, zero-token CI testing.
    
    Executes a scenario-driven or dynamically derived ReAct sequence against
    the MockToolEnvironment, verifying tool mechanics, measuring latency, tracking
    simulated tokens, and emitting the required structured diagnosis tail.
    """

    default_script_name: str = "mock_baseline_trajectory.yaml"

    def _run_dynamic_trajectory(self, max_turns: int) -> ReActExecutionResult:
        """Dynamic fallback when no pre-recorded scenario script is present."""
        trajectory: list[dict[str, Any]] = []
        total_in_tokens = 0
        total_out_tokens = 0
        tool_calls_count = 0
        current_history_tokens = 260
        turn = 0

        # Turn 1: list_services
        turn += 1
        if turn > max_turns:
            return self._terminate_turn_limit(
                trajectory, tool_calls_count, "unknown-service", total_in_tokens, total_out_tokens
            )

        services = self.env.dispatch("list_services")
        if isinstance(services, dict) and "error" in services:
            services = []
        tool_calls_count += 1
        trajectory.append({
            "turn": len(trajectory) + 1,
            "thought": "Discovering active services.",
            "tool": "list_services",
            "tool_input": {},
            "tool_output": services,
        })
        current_history_tokens += 75
        total_in_tokens += current_history_tokens
        total_out_tokens += 45

        # Turn 2: query_k8s_events
        turn += 1
        if turn > max_turns:
            return self._terminate_turn_limit(
                trajectory, tool_calls_count, services[0] if services else "unknown-service", total_in_tokens, total_out_tokens
            )

        k8s_events = self.env.dispatch("query_k8s_events")
        if isinstance(k8s_events, dict) and "error" in k8s_events:
            k8s_events = []
        tool_calls_count += 1
        trajectory.append({
            "turn": len(trajectory) + 1,
            "thought": "Checking Kubernetes events for crashes or warnings.",
            "tool": "query_k8s_events",
            "tool_input": {},
            "tool_output": k8s_events,
        })
        current_history_tokens += 120
        total_in_tokens += current_history_tokens
        total_out_tokens += 55

        # Find impacted service from warning/error events
        target_service = None
        for ev in k8s_events:
            if ev.get("service") and (ev.get("type") in ("Warning", "Error") or "OOM" in ev.get("reason", "")):
                target_service = ev.get("service")
                break

        # If no events indicate an issue, inspect delta across services to identify anomaly
        if not target_service and services:
            target_service = services[0]
            service_deltas: dict[str, float] = {}
            for svc in services:
                if turn >= max_turns:
                    break
                metrics = self.env.dispatch("list_metrics", {"service": svc})
                if isinstance(metrics, dict) and "error" in metrics:
                    metrics = []
                turn += 1
                tool_calls_count += 1
                trajectory.append({
                    "turn": len(trajectory) + 1,
                    "thought": f"Listing metrics for candidate service {svc}.",
                    "tool": "list_metrics",
                    "tool_input": {"service": svc},
                    "tool_output": metrics,
                })
                current_history_tokens += 60
                total_in_tokens += current_history_tokens
                total_out_tokens += 35

                for m in metrics:
                    if turn >= max_turns:
                        break
                    turn += 1
                    tool_calls_count += 1
                    res = self.env.dispatch("query_prometheus", {"query": f'{m}{{service="{svc}"}}'})
                    trajectory.append({
                        "turn": len(trajectory) + 1,
                        "thought": f"Querying metric {m} for service {svc}.",
                        "tool": "query_prometheus",
                        "tool_input": {"query": f'{m}{{service="{svc}"}}'},
                        "tool_output": res,
                    })
                    current_history_tokens += 90
                    total_in_tokens += current_history_tokens
                    total_out_tokens += 45
                    delta = (
                        abs(res.get("data", {}).get("summary", {}).get("delta", 0.0))
                        if isinstance(res, dict)
                        else 0.0
                    )
                    service_deltas[svc] = max(service_deltas.get(svc, 0.0), delta)

            if service_deltas:
                target_service = max(service_deltas, key=service_deltas.get)

        target_service = target_service or "unknown-service"

        # If we have turns left, list metrics for target_service
        if turn < max_turns:
            turn += 1
            metrics = self.env.dispatch("list_metrics", {"service": target_service})
            tool_calls_count += 1
            trajectory.append({
                "turn": len(trajectory) + 1,
                "thought": f"Inspecting metrics for impacted service {target_service}.",
                "tool": "list_metrics",
                "tool_input": {"service": target_service},
                "tool_output": metrics,
            })
            current_history_tokens += 75
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
            "thought": "Dynamic fallback synthesis complete.",
            "response": final_text,
        })
        return ReActExecutionResult(
            final_text=final_text,
            input_tokens=total_in_tokens,
            output_tokens=total_out_tokens,
            trajectory=trajectory,
            tool_calls_count=tool_calls_count,
        )


class BaselineARunner(BaseReActRunner):
    """Executes Baseline A: Direct LLM ReAct Agent interacting with observability query tools."""

    runner_prefix: str = "baseline_a"

    def __init__(self, manifest: BenchmarkManifest | None = None) -> None:
        manifest = manifest or load_manifest()
        super().__init__(
            runner_id="baseline_a_react",
            config=manifest.baseline_a,
            manifest=manifest,
        )

    def _create_mock_agent(self, env: MockToolEnvironment, scenario_dir: Path) -> BaseMockReActAgent:
        return MockSREAgent(env=env, config=self.config, scenario_dir=scenario_dir)

    def _run_live_agent(self, env: MockToolEnvironment) -> ReActExecutionResult:
        return run_live_openai_react_loop(
            env=env,
            config=self.config,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=USER_TRIAGE_PROMPT,
            include_signals=False,
        )

    def _run_openai_react(
        self,
        env: MockToolEnvironment,
        config: ModelRunConfig | None = None,
    ) -> ReActExecutionResult:
        """Backward-compatible method for live execution."""
        return self._run_live_agent(env)
