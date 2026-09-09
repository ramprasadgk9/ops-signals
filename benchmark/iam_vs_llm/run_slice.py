from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure repository root is on sys.path
_repo_root = Path(__file__).resolve().parents[2]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import yaml

from benchmark.iam_vs_llm.evaluators.f1_evaluator import F1Evaluator
from benchmark.iam_vs_llm.runners.iam_slice_runner import IAMSliceRunner
from benchmark.iam_vs_llm.scenarios.scenario_01_resource_degradation.generator import generate_scenario_1


def main() -> int:
    parser = argparse.ArgumentParser(description="IAM vs. LLM Benchmark: Slice 1 Offline Execution Harness")
    parser.add_argument("--scenario-dir", type=str, default="benchmark/iam_vs_llm/scenarios/scenario_01_resource_degradation", help="Path to scenario directory")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for telemetry generation")
    parser.add_argument("--regenerate", action="store_true", help="Force regeneration of synthetic scenario telemetry")
    args = parser.parse_args()

    scenario_dir = Path(args.scenario_dir)
    ground_truth_file = scenario_dir / "ground_truth.yaml"

    if args.regenerate or not ground_truth_file.exists():
        print(f"Generating synthetic telemetry in {scenario_dir} (seed={args.seed})...")
        generate_scenario_1(output_dir=scenario_dir, seed=args.seed)

    with open(ground_truth_file, "r", encoding="utf-8") as f:
        ground_truth = yaml.safe_load(f)

    print("\n" + "=" * 70)
    print(f"  IAM BENCHMARK: SLICE 1 OFFLINE VALIDATION")
    print(f"  Scenario: {ground_truth.get('scenario_id')}")
    print(f"  Target Entity: {ground_truth.get('entity')}")
    print(f"  Target Root Cause: {ground_truth.get('root_cause')}")
    print("=" * 70 + "\n")

    # 1. Execute IAM Runner
    print("[1/2] Running IAM Algorithmic Pipeline under state isolation...")
    runner = IAMSliceRunner()
    run_result = runner.run_batch_ingest(scenario_dir)
    print(f"      Execution finished in {run_result.execution_time_seconds:.4f}s")
    print(f"      Tokens Consumed: {run_result.token_usage} (Deterministic algorithmic path; advisor LLM bypassed)")
    print(f"      Embeddings Mode: stub_zero_vector (Cold-start isolated mode; vector memory disabled)")
    print(f"      Analyzers Executed: {run_result.metadata.get('executed_analyzers')}")
    print(f"      Findings Count: {run_result.metadata.get('finding_count')} (Behavior Findings: {run_result.metadata.get('behavior_finding_count')})")

    # 2. Evaluate F1 Score
    print("\n[2/2] Evaluating against Ground Truth...")
    evaluator = F1Evaluator()
    eval_result = evaluator.evaluate(run_result.normalized_rca, ground_truth)

    print("\n" + "-" * 70)
    print(f"  DIAGNOSTIC SCORECARD")
    print("-" * 70)
    print(f"  Entity Match:        {'PASS' if eval_result.entity_match else 'FAIL'} ({eval_result.details['predicted_entity']} vs {eval_result.details['expected_entity']})")
    print(f"  Root Cause Match:    {'PASS' if eval_result.root_cause_match else 'FAIL'} ({eval_result.details['predicted_root_cause']} vs {eval_result.details['expected_root_cause']})")
    print(f"  Window IoU:          {eval_result.window_iou:.4f}")
    print(f"  Evidence Precision:  {eval_result.evidence_precision:.4f}")
    print(f"  Evidence Recall:     {eval_result.evidence_recall:.4f}")
    print(f"  Evidence F1:         {eval_result.evidence_f1:.4f}")
    print(f"  Semantic Similarity: {eval_result.semantic_similarity:.4f}")
    print(f"  Composite Score:     {eval_result.composite_score:.4f}")
    print(f"  Overall Status:      {eval_result.status}")
    print("-" * 70)
    print(f"  Synthesized Diagnosis:\n    {run_result.normalized_rca.raw_summary.strip()}")
    print("=" * 70 + "\n")

    return 0 if eval_result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
