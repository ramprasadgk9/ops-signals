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


class MockSignalsAgent:
    """Deterministic simulated Signals-Augmented SRE agent for offline, zero-token CI testing.
    
    Executes a scenario-driven or dynamically derived ReAct sequence equipped with
    both raw observability tools and the list_signals tool against MockToolEnvironment.
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
        mock_script_path = (self.scenario_dir / "mock_baseline_b_trajectory.yaml") if self.scenario_dir else None
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
        current_history_tokens = 220

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

            turn_out = 45
            turn_in = 65
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
            synth_out = 150
            total_in_tokens += current_history_tokens
            total_out_tokens += synth_out
            trajectory.append({
                "turn": len(trajectory) + 1,
                "thought": "Synthesizing signals-augmented investigation into structured diagnosis.",
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
            # Sort by severity if available
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
        return final_text, total_in_tokens, total_out_tokens, trajectory, tool_calls_count


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

    def run_batch_ingest(self, scenario_dir: Path) -> BenchmarkRunResult:
        """Baseline B operates via interactive ReAct tool calling; delegates to execute."""
        return self.execute(scenario_dir)

    def run_react_agent(self, scenario_dir: Path) -> BenchmarkRunResult:
        scenario_id = scenario_dir.name
        env = self.get_query_environment(scenario_dir)

        with state_isolation() as ctx:
            start_time = time.perf_counter()

            provider = self.config.provider.lower().strip()
            if provider == "mock":
                agent = MockSignalsAgent(env=env, config=self.config, scenario_dir=scenario_dir)
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
                runner_id=f"baseline_b_{self.config.model_id}",
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
        """Executes a live OpenAI/OpenRouter tool-calling loop equipped with list_signals."""
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

        tools = env.get_tool_definitions(include_signals=True)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT_SIGNALS},
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
