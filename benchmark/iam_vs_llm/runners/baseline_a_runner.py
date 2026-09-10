from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import yaml

from benchmark.iam_vs_llm.configs.manifest_loader import BenchmarkManifest, ModelRunConfig, load_manifest
from benchmark.iam_vs_llm.evaluators.normalization import NormalizedRCA, normalize_structured_text
from benchmark.iam_vs_llm.runners.base_runner import BaseBenchmarkRunner, BenchmarkRunResult, state_isolation
from benchmark.iam_vs_llm.runners.mock_tool_environment import MockToolEnvironment


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

USER_TRIAGE_PROMPT = """High latency alerts and pod instability have been reported in the cluster over the last two hours.
Investigate the cluster telemetry and determine the root cause, affected entity, fault window, and key evidence.
"""


class MockSREAgent:
    """Deterministic simulated SRE agent for offline, zero-token CI testing.
    
    Executes a scenario-driven or dynamically derived ReAct sequence against
    the MockToolEnvironment, verifying tool mechanics, measuring latency, tracking
    simulated tokens, and emitting the required structured diagnosis tail.
    """

    def __init__(
        self,
        env: MockToolEnvironment,
        config: ModelRunConfig,
        scenario_dir: Path | None = None,
    ) -> None:
        self.env = env
        self.config = config
        self.scenario_dir = Path(scenario_dir) if scenario_dir else None

    def _terminate_turn_limit(
        self,
        trajectory: list[dict[str, Any]],
        tool_calls_count: int,
        entity: str = "unknown",
        total_in_tokens: int = 0,
        total_out_tokens: int = 0,
    ) -> tuple[str, int, int, list[dict[str, Any]], int]:
        forced_text = (
            f"Turn limit reached. Partial diagnosis based on {tool_calls_count} queries:\n\n"
            "ROOT_CAUSE: UNKNOWN\n"
            f"ENTITY: {entity}\n"
        )
        trajectory.append({
            "turn": len(trajectory) + 1,
            "thought": "Turn limit reached; premature termination.",
            "response": forced_text,
        })
        return forced_text, total_in_tokens, total_out_tokens, trajectory, tool_calls_count

    def run(self, max_turns: int = 10) -> tuple[str, int, int, list[dict[str, Any]], int]:
        """Executes simulated ReAct loop respecting max_turns."""
        mock_script_path = (self.scenario_dir / "mock_baseline_trajectory.yaml") if self.scenario_dir else None
        if mock_script_path and mock_script_path.exists():
            return self._run_scripted_trajectory(mock_script_path, max_turns)
        return self._run_dynamic_trajectory(max_turns)

    def _run_scripted_trajectory(
        self,
        script_path: Path,
        max_turns: int,
    ) -> tuple[str, int, int, list[dict[str, Any]], int]:
        with script_path.open("r", encoding="utf-8") as f:
            script_data = yaml.safe_load(f) or {}

        turns = script_data.get("turns", [])
        final_text = str(script_data.get("final_text", "")).strip()

        trajectory: list[dict[str, Any]] = []
        total_in_tokens = 0
        total_out_tokens = 0
        tool_calls_count = 0
        current_history_tokens = 260

        turn_idx = 0
        budget_exhausted = False

        for item in turns:
            turn_idx += 1
            if turn_idx > max_turns:
                budget_exhausted = True
                break

            tool_name = item.get("tool")
            tool_input = item.get("tool_input", {})
            thought = item.get("thought", "")

            output = self.env.dispatch(tool_name, tool_input)
            tool_calls_count += 1

            turn_out = 50
            turn_in = 70
            current_history_tokens += turn_out + turn_in
            total_in_tokens += current_history_tokens
            total_out_tokens += turn_out

            trajectory.append({
                "turn": len(trajectory) + 1,
                "thought": thought,
                "tool": tool_name,
                "tool_input": tool_input,
                "tool_output": output,
            })

        if not budget_exhausted and turn_idx < max_turns:
            # Final synthesis step fits in budget
            synth_out = 160
            total_in_tokens += current_history_tokens
            total_out_tokens += synth_out
            trajectory.append({
                "turn": len(trajectory) + 1,
                "thought": "Synthesizing full investigation into structured diagnosis.",
                "tool": None,
                "tool_input": None,
                "tool_output": None,
                "response": final_text,
            })
            return final_text, total_in_tokens, total_out_tokens, trajectory, tool_calls_count
        else:
            return self._terminate_turn_limit(
                trajectory=trajectory,
                tool_calls_count=tool_calls_count,
                entity="unknown",
                total_in_tokens=total_in_tokens,
                total_out_tokens=total_out_tokens,
            )



    def _run_dynamic_trajectory(
        self,
        max_turns: int,
    ) -> tuple[str, int, int, list[dict[str, Any]], int]:
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
        return final_text, total_in_tokens, total_out_tokens, trajectory, tool_calls_count


class BaselineARunner(BaseBenchmarkRunner):
    """Executes Baseline A: Direct LLM ReAct Agent interacting with observability query tools."""

    def __init__(self, manifest: BenchmarkManifest | None = None) -> None:
        super().__init__(runner_id="baseline_a_react")
        self.manifest = manifest or load_manifest()
        self.config = self.manifest.baseline_a

    def get_query_environment(self, scenario_dir: Path) -> MockToolEnvironment:
        return MockToolEnvironment(scenario_dir)

    def execute(self, scenario_dir: Path) -> BenchmarkRunResult:
        """Polymorphic execution entrypoint; runs the ReAct agent."""
        return self.run_react_agent(scenario_dir)

    def run_batch_ingest(self, scenario_dir: Path) -> BenchmarkRunResult:
        """Baseline A operates via interactive ReAct tool calling; delegates to execute."""
        return self.execute(scenario_dir)

    def run_react_agent(self, scenario_dir: Path) -> BenchmarkRunResult:
        scenario_id = scenario_dir.name
        env = self.get_query_environment(scenario_dir)

        with state_isolation() as ctx:
            start_time = time.perf_counter()

            provider = self.config.provider.lower().strip()
            if provider == "mock":
                agent = MockSREAgent(env=env, config=self.config, scenario_dir=scenario_dir)
                final_text, in_tokens, out_tokens, trajectory, tool_calls = agent.run(
                    max_turns=self.config.max_turns
                )
            elif provider in ("openai", "openrouter"):
                final_text, in_tokens, out_tokens, trajectory, tool_calls = self._run_openai_react(
                    env=env,
                    config=self.config,
                )
            else:
                raise ValueError(
                    f"Unsupported provider '{self.config.provider}'. "
                    f"Supported providers: 'mock', 'openai', 'openrouter'."
                )

            duration = time.perf_counter() - start_time
            normalized_rca = normalize_structured_text(final_text)
            cost_usd = self.config.pricing.calculate_cost(in_tokens, out_tokens)

            return BenchmarkRunResult(
                runner_id=f"baseline_a_{self.config.model_id}",
                scenario_id=scenario_id,
                normalized_rca=normalized_rca,
                execution_time_seconds=round(duration, 4),
                token_usage=in_tokens + out_tokens,
                cost_usd=cost_usd,
                tool_iterations=tool_calls,
                metadata={
                    "model_id": self.config.model_id,
                    "provider": self.config.provider,
                    "input_tokens": in_tokens,
                    "output_tokens": out_tokens,
                    "trajectory_turns": len(trajectory),
                    "trajectory": trajectory,
                },
            )

    def _run_openai_react(
        self,
        env: MockToolEnvironment,
        config: ModelRunConfig,
    ) -> tuple[str, int, int, list[dict[str, Any]], int]:
        """Executes a live OpenAI/OpenRouter tool-calling loop."""
        provider = (config.provider or "openai").lower().strip()
        if provider == "openrouter":
            api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("BENCHMARK_LLM_API_KEY")
            base_url = os.environ.get("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1"
        else:
            api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("BENCHMARK_LLM_API_KEY")
            base_url = os.environ.get("OPENAI_BASE_URL")

        if not api_key:
            key_name = "OPENROUTER_API_KEY" if provider == "openrouter" else "OPENAI_API_KEY"
            raise ValueError(
                f"API key missing. Set {key_name} or BENCHMARK_LLM_API_KEY in environment "
                "or configure provider: 'mock' in benchmark_manifest.yaml."
            )

        try:
            from openai import OpenAI
        except ImportError as e:
            raise ImportError("openai package required for live LLM execution. Run: pip install openai") from e

        client = OpenAI(api_key=api_key, base_url=base_url)

        tools = env.get_tool_definitions()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_TRIAGE_PROMPT},
        ]

        trajectory: list[dict[str, Any]] = []
        total_in_tokens = 0
        total_out_tokens = 0
        tool_calls_count = 0
        final_text = ""

        for turn in range(1, config.max_turns + 1):
            response = client.chat.completions.create(
                model=config.model_id,
                messages=messages,
                tools=tools,
                temperature=config.temperature,
            )

            usage = response.usage
            if usage:
                total_in_tokens += usage.prompt_tokens
                total_out_tokens += usage.completion_tokens

            msg = response.choices[0].message
            tool_calls = msg.tool_calls

            if not tool_calls:
                final_text = msg.content or ""
                trajectory.append({
                    "turn": len(trajectory) + 1,
                    "thought": "Final diagnosis emitted.",
                    "response": final_text,
                })
                break

            # Process tool calls
            messages.append(msg.to_dict() if hasattr(msg, "to_dict") else {
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ],
            })

            for tc in tool_calls:
                tool_calls_count += 1
                func_name = tc.function.name
                try:
                    tool_args = json.loads(tc.function.arguments or "{}")
                    if not isinstance(tool_args, dict):
                        raise TypeError(f"Tool arguments must be a JSON object, got {type(tool_args).__name__}")
                except (json.JSONDecodeError, TypeError) as err:
                    tool_args = {"raw_arguments": tc.function.arguments}
                    result = {"error": f"Invalid JSON arguments: {err}"}
                else:
                    result = env.dispatch(func_name, tool_args)

                result_str = json.dumps(result, default=str)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": func_name,
                    "content": result_str,
                })
                trajectory.append({
                    "turn": len(trajectory) + 1,
                    "tool": func_name,
                    "tool_input": tool_args,
                    "tool_output": result,
                })
        else:
            # Reached max turns without natural termination, ask for summary
            messages.append({
                "role": "user",
                "content": "Turn limit reached. Please provide your immediate root cause conclusion and structured tail.",
            })
            forced_resp = client.chat.completions.create(
                model=config.model_id,
                messages=messages,
                temperature=config.temperature,
            )
            final_text = forced_resp.choices[0].message.content or ""
            if forced_resp.usage:
                total_in_tokens += forced_resp.usage.prompt_tokens
                total_out_tokens += forced_resp.usage.completion_tokens
            trajectory.append({
                "turn": len(trajectory) + 1,
                "thought": "Turn limit reached; forced summary emitted.",
                "response": final_text,
            })


        return final_text, total_in_tokens, total_out_tokens, trajectory, tool_calls_count
