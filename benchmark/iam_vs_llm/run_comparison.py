from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

# Ensure repository root is on sys.path
_repo_root = Path(__file__).resolve().parents[2]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import yaml

from benchmark.iam_vs_llm.configs.manifest_loader import load_manifest
from benchmark.iam_vs_llm.evaluators.f1_evaluator import F1Evaluator, F1EvaluationResult
from benchmark.iam_vs_llm.runners.base_runner import BenchmarkRunResult
from benchmark.iam_vs_llm.runners.baseline_a_runner import BaselineARunner
from benchmark.iam_vs_llm.runners.iam_slice_runner import IAMSliceRunner


def run_benchmark_comparison(
    scenario_dir: Path,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Executes IAM and Baseline A against the designated scenario and evaluates both."""
    manifest = load_manifest(manifest_path)
    random.seed(manifest.random_seed)
    try:
        import numpy as np
        np.random.seed(manifest.random_seed)
    except ImportError:
        pass
    gt_path = scenario_dir / "ground_truth.yaml"
    if not gt_path.exists():
        raise FileNotFoundError(f"Missing ground truth at {gt_path}")

    with gt_path.open("r", encoding="utf-8") as f:
        ground_truth = yaml.safe_load(f)

    evaluator = F1Evaluator()

    # 1. Run IAM
    print(f"[*] Executing IAM Slice Runner on {scenario_dir.name}...", file=sys.stderr)
    iam_runner = IAMSliceRunner()
    iam_run_res: BenchmarkRunResult = iam_runner.run_batch_ingest(scenario_dir)
    iam_eval: F1EvaluationResult = evaluator.evaluate(iam_run_res.normalized_rca, ground_truth)

    # 2. Run Baseline A
    print(
        f"[*] Executing Baseline A ({manifest.baseline_a.provider} / {manifest.baseline_a.model_id})...",
        file=sys.stderr,
    )
    base_a_runner = BaselineARunner(manifest=manifest)
    base_a_run_res: BenchmarkRunResult = base_a_runner.run_react_agent(scenario_dir)
    base_a_eval: F1EvaluationResult = evaluator.evaluate(base_a_run_res.normalized_rca, ground_truth)

    return {
        "scenario": scenario_dir.name,
        "ground_truth": ground_truth,
        "iam": {
            "run": iam_run_res,
            "evaluation": iam_eval,
        },
        "baseline_a": {
            "run": base_a_run_res,
            "evaluation": base_a_eval,
        },
    }


def print_comparison_table(results: dict[str, Any]) -> None:
    scenario = results["scenario"]
    iam_run: BenchmarkRunResult = results["iam"]["run"]
    iam_eval: F1EvaluationResult = results["iam"]["evaluation"]
    base_a_run: BenchmarkRunResult = results["baseline_a"]["run"]
    base_a_eval: F1EvaluationResult = results["baseline_a"]["evaluation"]

    print("\n" + "=" * 94)
    print(f"  IAM vs. BASELINE A COMPARATIVE BENCHMARK: {scenario}")
    print("=" * 94)

    header = (
        f"{'System':<24} | {'Status':<8} | {'Entity':<15} | {'Root Cause':<16} | "
        f"{'IoU':<6} | {'Ev-F1':<6} | {'Tokens':<8} | {'Cost ($)':<8} | {'Latency':<7}"
    )
    separator = "-" * len(header)
    print(header)
    print(separator)

    row_iam = (
        f"{'IAM (Ops Signals)':<24} | "
        f"{iam_eval.status:<8} | "
        f"{str(iam_run.normalized_rca.entity):<15} | "
        f"{iam_run.normalized_rca.root_cause.value:<16} | "
        f"{iam_eval.window_iou:<6.2f} | "
        f"{iam_eval.evidence_f1:<6.2f} | "
        f"{iam_run.token_usage:<8d} | "
        f"${iam_run.cost_usd:<7.4f} | "
        f"{iam_run.execution_time_seconds:<6.3f}s"
    )
    print(row_iam)

    row_base_a = (
        f"{'Baseline A (ReAct SRE)':<24} | "
        f"{base_a_eval.status:<8} | "
        f"{str(base_a_run.normalized_rca.entity):<15} | "
        f"{base_a_run.normalized_rca.root_cause.value:<16} | "
        f"{base_a_eval.window_iou:<6.2f} | "
        f"{base_a_eval.evidence_f1:<6.2f} | "
        f"{base_a_run.token_usage:<8d} | "
        f"${base_a_run.cost_usd:<7.4f} | "
        f"{base_a_run.execution_time_seconds:<6.3f}s"
    )
    print(row_base_a)
    print(separator)

    print("\n[+] Detailed Metric Breakdown:")
    print(f"  * Ground Truth: Entity={results['ground_truth']['entity']}, Cause={results['ground_truth']['root_cause']}")
    print(f"  * IAM Composite Score:        {iam_eval.composite_score:.4f} (Analyzers executed: {iam_run.tool_iterations})")
    print(f"  * Baseline A Composite Score: {base_a_eval.composite_score:.4f} (Tool calls executed: {base_a_run.tool_iterations})")

    # Pareto comparison
    token_diff = base_a_run.token_usage - iam_run.token_usage
    cost_diff = base_a_run.cost_usd - iam_run.cost_usd
    print("\n[+] Empirical Pareto Tradeoff Analysis:")
    if iam_run.token_usage == 0:
        print(f"  - Token Efficiency: IAM consumed 0 LLM tokens vs {base_a_run.token_usage:,} tokens for Baseline A.")
    if cost_diff > 0:
        print(f"  - Financial Advantage: IAM triage cost ${iam_run.cost_usd:.4f} vs ${base_a_run.cost_usd:.4f} for Baseline A.")
    if iam_run.execution_time_seconds < base_a_run.execution_time_seconds and iam_run.execution_time_seconds > 0:
        speedup = base_a_run.execution_time_seconds / iam_run.execution_time_seconds
        print(f"  - Latency Speedup: IAM executed {speedup:.1f}x faster than Baseline A ReAct loop.")
    print("=" * 94 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="IAM vs Baseline A Comparative Benchmark Runner")
    default_scenario = (
        Path(__file__).resolve().parent / "scenarios" / "scenario_01_resource_degradation"
    )
    parser.add_argument(
        "--scenario-dir",
        type=Path,
        default=default_scenario,
        help="Path to scenario directory",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Path to benchmark manifest yaml",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON format",
    )

    args = parser.parse_args()

    results = run_benchmark_comparison(
        scenario_dir=args.scenario_dir,
        manifest_path=args.manifest,
    )

    if args.json:
        # Serialize dataclasses to dict
        iam_res = results["iam"]
        base_res = results["baseline_a"]
        payload = {
            "scenario": results["scenario"],
            "iam": {
                "runner_id": iam_res["run"].runner_id,
                "status": iam_res["evaluation"].status,
                "composite_score": iam_res["evaluation"].composite_score,
                "tokens": iam_res["run"].token_usage,
                "cost_usd": iam_res["run"].cost_usd,
                "latency_sec": iam_res["run"].execution_time_seconds,
            },
            "baseline_a": {
                "runner_id": base_res["run"].runner_id,
                "status": base_res["evaluation"].status,
                "composite_score": base_res["evaluation"].composite_score,
                "tokens": base_res["run"].token_usage,
                "cost_usd": base_res["run"].cost_usd,
                "latency_sec": base_res["run"].execution_time_seconds,
            },
        }
        print(json.dumps(payload, indent=2))
    else:
        print_comparison_table(results)

    # Check if both passed
    iam_pass = results["iam"]["evaluation"].passed
    base_pass = results["baseline_a"]["evaluation"].passed
    sys.exit(0 if (iam_pass and base_pass) else 1)


if __name__ == "__main__":
    main()
