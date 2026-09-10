from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from benchmark.iam_vs_llm.configs.manifest_loader import BenchmarkManifest, ModelRunConfig, load_manifest
from benchmark.iam_vs_llm.evaluators.normalization import normalize_structured_text
from benchmark.iam_vs_llm.runners.base_runner import BaseBenchmarkRunner, BenchmarkRunResult, state_isolation
from benchmark.iam_vs_llm.runners.mock_tool_environment import MockToolEnvironment


@dataclass(slots=True)
class ReActExecutionResult:
    """Encapsulates the output of a simulated or live ReAct tool-calling loop."""
    final_text: str
    input_tokens: int
    output_tokens: int
    trajectory: list[dict[str, Any]]
    tool_calls_count: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __iter__(self):
        """Allows unpacking as (final_text, in_tokens, out_tokens, trajectory, tool_calls)."""
        return iter((
            self.final_text,
            self.input_tokens,
            self.output_tokens,
            self.trajectory,
            self.tool_calls_count,
        ))


class BaseMockReActAgent:
    """Base simulated ReAct agent for offline zero-token CI testing."""

    default_script_name: str = "mock_baseline_trajectory.yaml"

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
    ) -> ReActExecutionResult:
        """Standardized early termination when turn budget is exhausted."""
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
        return ReActExecutionResult(
            final_text=forced_text,
            input_tokens=total_in_tokens,
            output_tokens=total_out_tokens,
            trajectory=trajectory,
            tool_calls_count=tool_calls_count,
        )

    def run(self, max_turns: int = 10) -> ReActExecutionResult:
        """Executes simulated ReAct loop respecting max_turns."""
        mock_script_path = (self.scenario_dir / self.default_script_name) if self.scenario_dir else None
        if mock_script_path and mock_script_path.exists():
            return self._run_scripted_trajectory(mock_script_path, max_turns)
        return self._run_dynamic_trajectory(max_turns)

    def _run_scripted_trajectory(
        self,
        script_path: Path,
        max_turns: int,
        synthesis_thought: str = "Synthesizing investigation into structured diagnosis.",
    ) -> ReActExecutionResult:
        """Executes pre-recorded scenario trajectory against MockToolEnvironment."""
        with script_path.open("r", encoding="utf-8") as f:
            script_data = yaml.safe_load(f) or {}

        turns = script_data.get("turns", [])
        final_text = str(script_data.get("final_text", "")).strip()

        trajectory: list[dict[str, Any]] = []
        total_in_tokens = 0
        total_out_tokens = 0
        tool_calls_count = 0
        current_history_tokens = 240

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
            synth_out = 150
            total_in_tokens += current_history_tokens
            total_out_tokens += synth_out
            trajectory.append({
                "turn": len(trajectory) + 1,
                "thought": synthesis_thought,
                "tool": None,
                "tool_input": None,
                "tool_output": None,
                "response": final_text,
            })
            return ReActExecutionResult(
                final_text=final_text,
                input_tokens=total_in_tokens,
                output_tokens=total_out_tokens,
                trajectory=trajectory,
                tool_calls_count=tool_calls_count,
            )
        else:
            return self._terminate_turn_limit(
                trajectory=trajectory,
                tool_calls_count=tool_calls_count,
                entity="unknown",
                total_in_tokens=total_in_tokens,
                total_out_tokens=total_out_tokens,
            )

    def _run_dynamic_trajectory(self, max_turns: int) -> ReActExecutionResult:
        """Dynamic fallback to be implemented by baseline-specific agents."""
        raise NotImplementedError


def run_live_openai_react_loop(
    env: MockToolEnvironment,
    config: ModelRunConfig,
    system_prompt: str,
    user_prompt: str,
    include_signals: bool = False,
) -> ReActExecutionResult:
    """Executes a live OpenAI or OpenRouter tool-calling loop."""
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
    tools = env.get_tool_definitions(include_signals=include_signals)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    trajectory: list[dict[str, Any]] = []
    total_in_tokens = 0
    total_out_tokens = 0
    tool_calls_count = 0
    final_text = ""

    for _ in range(1, config.max_turns + 1):
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

    return ReActExecutionResult(
        final_text=final_text,
        input_tokens=total_in_tokens,
        output_tokens=total_out_tokens,
        trajectory=trajectory,
        tool_calls_count=tool_calls_count,
    )


USER_TRIAGE_PROMPT = (
    "You are an expert site reliability engineer investigating a production incident. "
    "Investigate available telemetry and identify the root cause and culprit entity."
)


class BaseReActRunner(BaseBenchmarkRunner):
    """Base benchmark runner orchestrating simulated or live ReAct LLM agents."""

    runner_prefix: str = "baseline"

    def __init__(
        self,
        runner_id: str,
        config: ModelRunConfig,
        manifest: BenchmarkManifest | None = None,
    ) -> None:
        super().__init__(runner_id=runner_id)
        self.manifest = manifest or load_manifest()
        self.config = config

    def get_query_environment(self, scenario_dir: Path) -> MockToolEnvironment:
        return MockToolEnvironment(scenario_dir)

    def execute(self, scenario_dir: Path) -> BenchmarkRunResult:
        """Polymorphic execution entrypoint; runs the ReAct agent."""
        return self.run_react_agent(scenario_dir)

    def _create_mock_agent(
        self,
        env: MockToolEnvironment,
        scenario_dir: Path,
    ) -> BaseMockReActAgent:
        raise NotImplementedError

    def _run_live_agent(
        self,
        env: MockToolEnvironment,
    ) -> ReActExecutionResult:
        raise NotImplementedError

    def run_react_agent(self, scenario_dir: Path) -> BenchmarkRunResult:
        scenario_id = scenario_dir.name
        env = self.get_query_environment(scenario_dir)

        with state_isolation() as ctx:
            start_time = time.perf_counter()

            provider = self.config.provider.lower().strip()
            if provider == "mock":
                agent = self._create_mock_agent(env, scenario_dir)
                exec_res = agent.run(max_turns=self.config.max_turns)
            elif provider in ("openai", "openrouter"):
                exec_res = self._run_live_agent(env)
            else:
                raise ValueError(
                    f"Unsupported provider '{self.config.provider}'. "
                    "Supported providers: 'mock', 'openai', 'openrouter'."
                )

            duration = time.perf_counter() - start_time
            normalized_rca = normalize_structured_text(exec_res.final_text)
            cost_usd = self.config.pricing.calculate_cost(exec_res.input_tokens, exec_res.output_tokens)

            return BenchmarkRunResult(
                runner_id=f"{self.runner_prefix}_{self.config.model_id}",
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
