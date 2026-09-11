from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from benchmark.behavior_benchmark import BehaviorBenchmarkExecutionError, BehaviorEvaluation, run_benchmark
from benchmark.router_benchmark import PROJECT_ROOT


def discover_scenarios(root: Path) -> list[Path]:
    return sorted(path for path in root.iterdir() if path.is_dir() and _is_behavior_scenario(path))


def _is_behavior_scenario(scenario_dir: Path) -> bool:
    ground_truth_path = scenario_dir / "ground_truth.yaml"
    if not ground_truth_path.exists():
        return False
    ground_truth = yaml.safe_load(ground_truth_path.read_text(encoding="utf-8")) or {}
    return isinstance(ground_truth, dict) and "expected_behavior_findings" in ground_truth


def run_suite(scenarios_root: Path) -> list[BehaviorEvaluation]:
    return [run_benchmark(scenario_dir) for scenario_dir in discover_scenarios(scenarios_root)]


def print_summary(evaluations: list[BehaviorEvaluation]) -> None:
    print("Scenario | Required Matched | Actual Matched | Result")
    print("--- | --- | --- | ---")
    for evaluation in evaluations:
        print(
            " | ".join(
                [
                    evaluation.scenario_id,
                    ", ".join(sorted(set(evaluation.matched_definition_ids) | set(evaluation.missing_required))) or "none",
                    ", ".join(evaluation.matched_definition_ids) or "none",
                    evaluation.status,
                ]
            )
        )


def print_failure_diagnostics(evaluations: list[BehaviorEvaluation]) -> None:
    for evaluation in evaluations:
        if evaluation.status == "PASS":
            continue
        print(f"\nScenario: {evaluation.scenario_id}")
        if evaluation.execution_error:
            print(f"Execution error: {evaluation.execution_error}")
            continue
        if evaluation.missing_required:
            print(f"Missing required behaviors: {', '.join(evaluation.missing_required)}")
        if evaluation.incorrectly_matched:
            print(f"Incorrectly matched (forbidden) behaviors: {', '.join(evaluation.incorrectly_matched)}")
        print(f"Actually matched: {', '.join(evaluation.matched_definition_ids) or 'none'}")


def exit_code(evaluations: list[BehaviorEvaluation]) -> int:
    if any(evaluation.status == "ERROR" for evaluation in evaluations):
        return 2
    if any(evaluation.status == "FAIL" for evaluation in evaluations):
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run all Ops Signals Behavior Intelligence benchmark scenarios")
    parser.add_argument(
        "--scenarios-root",
        default=str(PROJECT_ROOT / "benchmark" / "scenarios"),
        help="Directory containing scenario subdirectories.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    scenarios_root = Path(args.scenarios_root)
    if not scenarios_root.exists():
        raise SystemExit(2)
    try:
        evaluations = run_suite(scenarios_root)
    except BehaviorBenchmarkExecutionError as exc:
        print(f"Benchmark configuration error: {exc}")
        raise SystemExit(2) from exc
    print_summary(evaluations)
    print_failure_diagnostics(evaluations)
    raise SystemExit(exit_code(evaluations))


if __name__ == "__main__":
    main()
