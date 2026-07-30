from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

from benchmark.router_benchmark import PROJECT_ROOT, RouterBenchmarkExecutionError, RouterEvaluation, run_benchmark


def discover_scenarios(root: Path) -> list[Path]:
    return sorted(path for path in root.iterdir() if path.is_dir() and (path / "ground_truth.yaml").exists())


def run_suite(scenarios_root: Path) -> list[RouterEvaluation]:
    evaluations = []
    for scenario_dir in discover_scenarios(scenarios_root):
        evaluations.append(run_benchmark(scenario_dir))
    return evaluations


def print_summary(evaluations: list[RouterEvaluation]) -> None:
    print("Scenario | Expected Recommended | Actual Recommended | Actual Optional | Result")
    print("--- | --- | --- | --- | ---")
    for evaluation in evaluations:
        expected = _expected_recommended(evaluation.scenario_id)
        print(
            " | ".join(
                [
                    evaluation.scenario_id,
                    ", ".join(expected) or "none",
                    ", ".join(evaluation.actual["recommended"]) or "none",
                    ", ".join(evaluation.actual["optional"]) or "none",
                    evaluation.status,
                ]
            )
        )


def print_failure_diagnostics(evaluations: list[RouterEvaluation]) -> None:
    for evaluation in evaluations:
        if evaluation.status == "PASS":
            continue
        print(f"\nScenario: {evaluation.scenario_id}")
        print(f"Expected recommended: {', '.join(_expected_recommended(evaluation.scenario_id)) or 'none'}")
        print(f"Actual recommended: {', '.join(evaluation.actual['recommended']) or 'none'}")
        print(f"Actual optional: {', '.join(evaluation.actual['optional']) or 'none'}")
        if evaluation.execution_error:
            print(f"Execution error: {evaluation.execution_error}")
            continue
        if evaluation.missing_required:
            print(f"Missing required recommended: {', '.join(evaluation.missing_required)}")
        if evaluation.incorrectly_recommended:
            print(f"Forbidden recommended: {', '.join(evaluation.incorrectly_recommended)}")
        if evaluation.missing_detected_profiles:
            print(f"Missing detected profiles: {', '.join(evaluation.missing_detected_profiles)}")
        if evaluation.forbidden_detected_profiles:
            print(f"Forbidden detected profiles: {', '.join(evaluation.forbidden_detected_profiles)}")
        _print_profile(evaluation.profile)
        for entry in [item for bucket in evaluation.actual_details.values() for item in bucket]:
            _print_decision(entry)


def print_optional_diagnostics(evaluations: list[RouterEvaluation]) -> None:
    for evaluation in evaluations:
        if evaluation.unexpected_optional:
            print(f"\nUnexpected optional analyzers for {evaluation.scenario_id}: {', '.join(evaluation.unexpected_optional)}")


def exit_code(evaluations: list[RouterEvaluation]) -> int:
    if any(evaluation.status == "ERROR" for evaluation in evaluations):
        return 2
    if any(evaluation.status == "FAIL" for evaluation in evaluations):
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run all Ops Signals router benchmark scenarios")
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
    except RouterBenchmarkExecutionError as exc:
        print(f"Benchmark configuration error: {exc}")
        raise SystemExit(2) from exc
    print_summary(evaluations)
    print_optional_diagnostics(evaluations)
    print_failure_diagnostics(evaluations)
    raise SystemExit(exit_code(evaluations))


def _expected_recommended(scenario_id: str) -> list[str]:
    ground_truth_path = PROJECT_ROOT / "benchmark" / "scenarios" / scenario_id / "ground_truth.yaml"
    if not ground_truth_path.exists():
        return []
    data = yaml.safe_load(ground_truth_path.read_text(encoding="utf-8")) or {}
    return [str(item) for item in data.get("expected_router", {}).get("required_recommended", [])]


def _print_profile(profile: dict[str, Any]) -> None:
    print("Detected profiles:", ", ".join(profile.get("detected_profiles", [])) or "none")
    for key in ["shift_index", "trend_strength", "seasonality_strength", "spikiness"]:
        if key in profile:
            print(f"{key}: {float(profile[key]):.4f}")


def _print_decision(entry: dict[str, Any]) -> None:
    evidence = entry.get("feature_evidence") or {}
    print(f"{entry['analyzer']}:")
    print(f"  supported_profiles: {', '.join(evidence.get('supported_profiles', [])) or 'none'}")
    print(f"  behavioral_supported_profiles: {', '.join(evidence.get('behavioral_supported_profiles', [])) or 'none'}")
    print(f"  matched_profiles: {', '.join(evidence.get('matched_profiles', [])) or 'none'}")
    print(f"  profile_match: {evidence.get('profile_match')}")
    print(f"  eligibility_score: {float(entry.get('eligibility_score') or 0):.4f}")
    print(f"  suitability_score: {float(entry.get('suitability_score') or 0):.4f}")
    print(f"  final_score: {float(entry.get('score') or 0):.4f}")
    print(f"  recommendation: {entry.get('category')}")
    print(f"  matched_scoring_rules: {evidence.get('matched_scoring_rules', [])}")
    print(f"  explanation: {entry.get('explanation')}")


if __name__ == "__main__":
    main()
