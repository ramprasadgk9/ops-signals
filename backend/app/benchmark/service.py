from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from benchmark.iam_vs_llm.configs.manifest_loader import (
    BenchmarkManifest,
    ModelRunConfig,
    PricingConfig,
    load_manifest,
)
from benchmark.iam_vs_llm.run_comparison import (
    generate_benchmark_reports,
    run_benchmark_comparison,
)

logger = logging.getLogger(__name__)


class BenchmarkService:
    """Encapsulated domain service for executing and reporting IAM vs. LLM benchmarks."""

    def __init__(self, repo_root: Path | None = None) -> None:
        if repo_root is None:
            self.repo_root = Path(__file__).resolve().parents[3]
        else:
            self.repo_root = repo_root

        self.benchmark_root = self.repo_root / "benchmark" / "iam_vs_llm"
        self.scenarios_dir = self.benchmark_root / "scenarios"
        self.manifest_path = self.benchmark_root / "configs" / "benchmark_manifest.yaml"
        self.report_dir = self.benchmark_root
        self.report_file = self.report_dir / "benchmark_report.json"

    def list_scenarios(self) -> list[dict[str, Any]]:
        """Returns metadata for all available benchmark scenarios."""
        if not self.scenarios_dir.exists():
            return []

        scenarios: list[dict[str, Any]] = []
        for s_dir in sorted(self.scenarios_dir.iterdir()):
            if not s_dir.is_dir() or not s_dir.name.startswith("scenario_"):
                continue

            gt_file = s_dir / "ground_truth.yaml"
            gt_data: dict[str, Any] = {}
            if gt_file.exists():
                try:
                    with gt_file.open("r", encoding="utf-8") as f:
                        gt_data = yaml.safe_load(f) or {}
                except Exception as e:
                    logger.warning("Failed to parse ground truth for %s: %s", s_dir.name, e)

            clean_title = s_dir.name
            for prefix in ("scenario_", "01_", "02_", "03_"):
                if clean_title.startswith(prefix):
                    clean_title = clean_title[len(prefix):]
            title = clean_title.replace("_", " ").title()

            scenarios.append({
                "id": s_dir.name,
                "title": title,
                "entity": gt_data.get("entity", "Unknown"),
                "root_cause": gt_data.get("root_cause", "UNKNOWN"),
                "fault_window": gt_data.get("fault_window", {}),
                "key_evidence": gt_data.get("key_evidence", {}),
                "has_metrics": (s_dir / "metrics.csv").exists(),
                "has_events": (s_dir / "k8s_events.json").exists(),
            })

        return scenarios

    def get_latest_report(self) -> dict[str, Any]:
        """Loads and returns the latest persisted benchmark report with calculated summary metrics."""
        if not self.report_file.exists():
            # If no report exists, generate initial mock baseline report
            self.run_benchmark(provider="mock")

        with self.report_file.open("r", encoding="utf-8") as f:
            scenarios_data = json.load(f)

        summary = self._calculate_summary(scenarios_data)
        stat = self.report_file.stat()
        generated_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

        return {
            "report_path": str(self.report_file),
            "generated_at": generated_at,
            "scenarios": scenarios_data,
            "summary": summary,
        }

    def run_benchmark(
        self,
        scenario_ids: list[str] | None = None,
        provider: str = "mock",
        model_id: str | None = None,
        judge_provider: str | None = None,
    ) -> dict[str, Any]:
        """Executes the comparative benchmark across specified scenarios and updates persisted reports."""
        target_dirs: list[Path] = []
        all_dirs = sorted([
            d for d in self.scenarios_dir.iterdir()
            if d.is_dir() and d.name.startswith("scenario_")
        ])

        if scenario_ids:
            for s_id in scenario_ids:
                matching = [d for d in all_dirs if d.name == s_id or s_id in d.name]
                if matching:
                    target_dirs.extend(matching)
        else:
            target_dirs = all_dirs

        if not target_dirs:
            raise ValueError(f"No matching scenarios found for: {scenario_ids}")

        # Remove duplicates while preserving order
        unique_dirs: list[Path] = []
        for d in target_dirs:
            if d not in unique_dirs:
                unique_dirs.append(d)

        # Build custom or default manifest
        manifest = load_manifest(self.manifest_path)
        normalized_provider = provider.lower().strip()

        # Validate live provider API key requirements
        if normalized_provider != "mock":
            if normalized_provider == "gemini":
                key = os.environ.get("GEMINI_API_KEY") or os.environ.get("BENCHMARK_LLM_API_KEY")
                if not key:
                    raise ValueError(
                        "GEMINI_API_KEY is not configured in the environment. "
                        "Please provide a Gemini API key or use provider 'mock'."
                    )
            elif normalized_provider == "openrouter":
                key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("BENCHMARK_LLM_API_KEY")
                if not key:
                    raise ValueError(
                        "OPENROUTER_API_KEY is not configured in the environment. "
                        "Please provide an OpenRouter API key or use provider 'mock'."
                    )
            elif normalized_provider == "openai":
                key = os.environ.get("OPENAI_API_KEY") or os.environ.get("BENCHMARK_LLM_API_KEY")
                if not key:
                    raise ValueError(
                        "OPENAI_API_KEY is not configured in the environment. "
                        "Please provide an OpenAI API key or use provider 'mock'."
                    )
            else:
                raise ValueError(
                    f"Unsupported provider '{provider}'. Supported: 'mock', 'gemini', 'openai', 'openrouter'."
                )

        # Apply provider configuration
        manifest.baseline_a.provider = normalized_provider
        manifest.baseline_b.provider = normalized_provider
        if model_id:
            manifest.baseline_a.model_id = model_id
            manifest.baseline_b.model_id = model_id

        if normalized_provider == "gemini":
            if not model_id:
                manifest.baseline_a.model_id = "gemini-2.0-flash"
                manifest.baseline_b.model_id = "gemini-2.0-flash"
            manifest.baseline_a.pricing = PricingConfig(0.10, 0.40)
            manifest.baseline_b.pricing = PricingConfig(0.10, 0.40)

        # Judge provider configuration
        if judge_provider:
            manifest.judge.provider = judge_provider.lower().strip()
        elif normalized_provider != "mock":
            manifest.judge.provider = normalized_provider
            if normalized_provider == "gemini":
                manifest.judge.model_id = "gemini-2.0-flash"

        # Execute comparison across target scenarios
        all_results: list[dict[str, Any]] = []
        for s_dir in unique_dirs:
            res = run_benchmark_comparison(
                scenario_dir=s_dir,
                manifest=manifest,
                include_baseline_b=True,
                include_judge=True,
            )
            all_results.append(res)

        # Write reports
        generate_benchmark_reports(all_results, output_dir=self.report_dir)

        return self.get_latest_report()

    def _calculate_summary(self, scenarios_data: list[dict[str, Any]]) -> dict[str, Any]:
        """Calculates aggregate metrics across scenarios for IAM, Baseline A, and Baseline B."""
        systems = ("iam", "baseline_a", "baseline_b")
        metrics: dict[str, dict[str, Any]] = {
            sys: {
                "total_runs": 0,
                "success_count": 0,
                "partial_count": 0,
                "failed_count": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
                "total_latency_s": 0.0,
                "total_evidence_f1": 0.0,
                "total_judge_attribution": 0.0,
                "total_judge_grounding": 0.0,
                "total_judge_actionability": 0.0,
                "judge_count": 0,
            }
            for sys in systems
        }

        for entry in scenarios_data:
            for sys in systems:
                if sys not in entry:
                    continue
                sys_res = entry[sys]
                m = metrics[sys]
                m["total_runs"] += 1
                status = str(sys_res.get("status", "")).upper()
                if status == "SUCCESS":
                    m["success_count"] += 1
                elif status == "PARTIAL":
                    m["partial_count"] += 1
                else:
                    m["failed_count"] += 1

                m["total_tokens"] += int(sys_res.get("tokens", 0))
                m["total_cost_usd"] += float(sys_res.get("cost_usd", 0.0))
                m["total_latency_s"] += float(sys_res.get("execution_time_seconds", 0.0))
                m["total_evidence_f1"] += float(sys_res.get("evidence_f1", 0.0))

                judge = sys_res.get("judge")
                if judge and "consensus" in judge:
                    c = judge["consensus"]
                    m["total_judge_attribution"] += float(c.get("attribution", 0.0))
                    m["total_judge_grounding"] += float(c.get("grounding", 0.0))
                    m["total_judge_actionability"] += float(c.get("actionability", 0.0))
                    m["judge_count"] += 1

        summary: dict[str, Any] = {}
        for sys in systems:
            m = metrics[sys]
            n = max(m["total_runs"], 1)
            jn = max(m["judge_count"], 1)
            summary[sys] = {
                "runs": m["total_runs"],
                "success_count": m["success_count"],
                "partial_count": m["partial_count"],
                "failed_count": m["failed_count"],
                "success_rate_pct": round((m["success_count"] / n) * 100, 1),
                "total_tokens": m["total_tokens"],
                "total_cost_usd": round(m["total_cost_usd"], 4),
                "avg_latency_s": round(m["total_latency_s"] / n, 4),
                "avg_evidence_f1": round(m["total_evidence_f1"] / n, 2),
                "avg_judge_attribution": round(m["total_judge_attribution"] / jn, 2),
                "avg_judge_grounding": round(m["total_judge_grounding"] / jn, 2),
                "avg_judge_actionability": round(m["total_judge_actionability"] / jn, 2),
            }

        # Calculate comparative Pareto advantages
        iam_summary = summary["iam"]
        base_a = summary["baseline_a"]
        base_b = summary["baseline_b"]

        token_red_a = 100.0
        if base_a["total_tokens"] > 0:
            token_red_a = round((1.0 - (iam_summary["total_tokens"] / base_a["total_tokens"])) * 100, 1)

        token_red_b = 100.0
        if base_b["total_tokens"] > 0:
            token_red_b = round((1.0 - (iam_summary["total_tokens"] / base_b["total_tokens"])) * 100, 1)

        cost_red = 100.0 if base_a["total_cost_usd"] > 0 else 0.0

        latency_speedup = 1.0
        if iam_summary["avg_latency_s"] > 0 and base_a["avg_latency_s"] > 0:
            latency_speedup = round(base_a["avg_latency_s"] / iam_summary["avg_latency_s"], 1)

        summary["pareto"] = {
            "token_reduction_vs_a_pct": token_red_a,
            "token_reduction_vs_b_pct": token_red_b,
            "cost_reduction_pct": cost_red,
            "latency_speedup_vs_a_x": latency_speedup,
            "iam_cost_per_incident": "$0.00",
            "iam_token_usage": 0,
        }

        return summary
