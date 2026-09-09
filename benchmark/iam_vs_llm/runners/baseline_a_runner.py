from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

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
    
    Executes a realistic ReAct sequence against the MockToolEnvironment, verifying
    tool mechanics, measuring latency, tracking simulated tokens, and emitting
    the required structured diagnosis tail.
    """

    def __init__(self, env: MockToolEnvironment, config: ModelRunConfig) -> None:
        self.env = env
        self.config = config

    def run(self, max_turns: int = 10) -> tuple[str, int, int, list[dict[str, Any]], int]:
        """Executes simulated ReAct loop.
        
        Returns:
            (final_text, input_tokens, output_tokens, trajectory, tool_calls_count)
        """
        trajectory: list[dict[str, Any]] = []
        total_in_tokens = 0
        total_out_tokens = 0
        tool_calls_count = 0

        # Base token overhead: System prompt (~200 tokens) + User prompt (~60 tokens)
        current_history_tokens = 260

        # Turn 1: list_services
        tool_calls_count += 1
        services = self.env.list_services()
        t1_out = 45
        t1_tool_in = 30
        current_history_tokens += t1_out + t1_tool_in
        total_in_tokens += current_history_tokens
        total_out_tokens += t1_out
        trajectory.append({
            "turn": 1,
            "thought": "Discovering active services in the cluster to identify investigation targets.",
            "tool": "list_services",
            "tool_input": {},
            "tool_output": services,
        })

        # Turn 2: query_k8s_events
        tool_calls_count += 1
        k8s_events = self.env.query_k8s_events()
        t2_out = 55
        t2_tool_in = 65
        current_history_tokens += t2_out + t2_tool_in
        total_in_tokens += current_history_tokens
        total_out_tokens += t2_out
        trajectory.append({
            "turn": 2,
            "thought": "Checking Kubernetes events across the cluster for crashes or pod restarts.",
            "tool": "query_k8s_events",
            "tool_input": {},
            "tool_output": k8s_events,
        })

        # Determine OOM target from events
        oom_services = [e.get("service") for e in k8s_events if "OOM" in e.get("reason", "") or "OOM" in e.get("message", "")]
        target_service = oom_services[0] if oom_services else (services[0] if services else "payment-service")

        # Turn 3: list_metrics for target service
        tool_calls_count += 1
        metrics = self.env.list_metrics(target_service)
        t3_out = 40
        t3_tool_in = 35
        current_history_tokens += t3_out + t3_tool_in
        total_in_tokens += current_history_tokens
        total_out_tokens += t3_out
        trajectory.append({
            "turn": 3,
            "thought": f"Pod termination detected on {target_service}. Inspecting recorded telemetry metrics.",
            "tool": "list_metrics",
            "tool_input": {"service": target_service},
            "tool_output": metrics,
        })

        # Turn 4: query_prometheus for memory_usage
        tool_calls_count += 1
        mem_res = self.env.query_prometheus(f'memory_usage{{service="{target_service}"}}')
        t4_out = 60
        t4_tool_in = 110
        current_history_tokens += t4_out + t4_tool_in
        total_in_tokens += current_history_tokens
        total_out_tokens += t4_out
        trajectory.append({
            "turn": 4,
            "thought": f"Querying memory_usage time-series for {target_service} to assess memory consumption trend.",
            "tool": "query_prometheus",
            "tool_input": {"query": f'memory_usage{{service="{target_service}"}}'},
            "tool_output": mem_res,
        })

        # Turn 5: query_prometheus for cpu_throttled_seconds
        tool_calls_count += 1
        cpu_res = self.env.query_prometheus(f'cpu_throttled_seconds{{service="{target_service}"}}')
        t5_out = 60
        t5_tool_in = 110
        current_history_tokens += t5_out + t5_tool_in
        total_in_tokens += current_history_tokens
        total_out_tokens += t5_out
        trajectory.append({
            "turn": 5,
            "thought": f"Checking CPU throttling to verify if GC thrashing coincided with memory saturation.",
            "tool": "query_prometheus",
            "tool_input": {"query": f'cpu_throttled_seconds{{service="{target_service}"}}'},
            "tool_output": cpu_res,
        })

        # Final Synthesis Turn
        t6_out = 160
        total_in_tokens += current_history_tokens
        total_out_tokens += t6_out

        final_text = (
            f"Investigation Complete:\n\n"
            f"Telemetric analysis reveals that {target_service} experienced progressive memory exhaustion "
            f"starting at 2026-09-07T10:30:00Z with a persistent upward trend in memory_usage. As heap consumption approached "
            f"the 1000Mi limit, aggressive garbage collection produced a baseline shift and spike in CPU throttling "
            f"beginning around 2026-09-07T11:15:00Z. The container was finally terminated by Kubernetes OOMKiller at 2026-09-07T11:45:00Z.\n\n"
            f"ROOT_CAUSE: MEMORY_LEAK\n"
            f"ENTITY: {target_service}\n"
            f"WINDOW: 2026-09-07T10:30:00Z to 2026-09-07T11:45:00Z\n"
            f"EVIDENCE: memory_usage, cpu_throttled_seconds, trend\n"
        )

        trajectory.append({
            "turn": 6,
            "thought": "Synthesizing full investigation into structured diagnosis.",
            "tool": None,
            "tool_input": None,
            "tool_output": None,
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

    def run_batch_ingest(self, scenario_dir: Path) -> BenchmarkRunResult:
        """Baseline A operates via interactive ReAct tool calling; delegates to run_react_agent."""
        return self.run_react_agent(scenario_dir)

    def run_react_agent(self, scenario_dir: Path) -> BenchmarkRunResult:
        scenario_id = scenario_dir.name
        env = self.get_query_environment(scenario_dir)

        with state_isolation() as ctx:
            start_time = time.perf_counter()

            provider = self.config.provider.lower().strip()
            if provider == "mock":
                agent = MockSREAgent(env=env, config=self.config)
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
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("BENCHMARK_LLM_API_KEY")
        if not api_key:
            raise ValueError(
                "API key missing. Set OPENAI_API_KEY or BENCHMARK_LLM_API_KEY in environment "
                "or configure provider: 'mock' in benchmark_manifest.yaml."
            )

        try:
            from openai import OpenAI
        except ImportError as e:
            raise ImportError("openai package required for live LLM execution. Run: pip install openai") from e

        base_url = os.environ.get("OPENAI_BASE_URL")
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

        tool_dispatcher = {
            "list_services": lambda _: env.list_services(),
            "list_metrics": lambda args: env.list_metrics(args.get("service", "")),
            "query_prometheus": lambda args: env.query_prometheus(
                query=args.get("query", ""),
                start_time=args.get("start_time"),
                end_time=args.get("end_time"),
            ),
            "query_k8s_events": lambda args: env.query_k8s_events(
                service=args.get("service"),
                event_type=args.get("event_type"),
            ),
        }

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
                    "turn": turn,
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
                fname = tc.function.name
                fargs = json.loads(tc.function.arguments or "{}")
                fn = tool_dispatcher.get(fname)
                result = fn(fargs) if fn else {"error": f"Unknown tool '{fname}'"}

                result_str = json.dumps(result, default=str)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": fname,
                    "content": result_str,
                })
                trajectory.append({
                    "turn": turn,
                    "tool": fname,
                    "tool_input": fargs,
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

        return final_text, total_in_tokens, total_out_tokens, trajectory, tool_calls_count
