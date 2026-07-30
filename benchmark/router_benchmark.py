from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from backend.app.services.timeseries_routing_service import TimeSeriesRoutingService, build_csv_routing_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MINIMUM_ROUTER_POINTS = 30
RECOMMENDED = "RECOMMENDED"
OPTIONAL = "OPTIONAL"
NOT_RECOMMENDED = "NOT_RECOMMENDED"
REJECTED = "REJECTED"


class RouterBenchmarkExecutionError(RuntimeError):
    """Raised when router benchmark execution cannot produce routing decisions."""


@dataclass(slots=True)
class RouterEvaluation:
    scenario_id: str
    status: str
    checks: dict[str, bool]
    missing_required: list[str]
    incorrectly_recommended: list[str]
    missing_detected_profiles: list[str]
    forbidden_detected_profiles: list[str]
    unexpected_optional: list[str]
    required_ineligible: list[dict[str, Any]]
    actual: dict[str, list[str]]
    actual_details: dict[str, list[dict[str, Any]]]
    profile: dict[str, Any]
    execution_error: str | None = None
    documented_gap: str | None = None

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


def load_scenario_dataframe(scenario_dir: Path) -> pd.DataFrame:
    dataset_path = scenario_dir / "dataset.csv"
    if not dataset_path.exists():
        raise RouterBenchmarkExecutionError(f"Scenario dataset is missing: {dataset_path}")

    dataframe = pd.read_csv(dataset_path)
    if dataframe.empty:
        raise RouterBenchmarkExecutionError(f"Scenario dataset is empty: {dataset_path}")
    if len(dataframe) < MINIMUM_ROUTER_POINTS:
        raise RouterBenchmarkExecutionError(
            f"Scenario dataset has {len(dataframe)} point(s); router benchmark requires at least {MINIMUM_ROUTER_POINTS}"
        )
    return dataframe


def run_router(scenario_dir: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    dataframe = load_scenario_dataframe(scenario_dir)
    config = build_csv_routing_config(
        provider="prometheus",
        service="benchmark-cpu",
        metric_name="cpu.usage_user",
        interval="5m",
        analyzer_id="all",
        preview=True,
    )
    try:
        result = TimeSeriesRoutingService().route_dataframe(dataframe, config.input)
    except ValueError as exc:
        raise RouterBenchmarkExecutionError(str(exc)) from exc
    return normalize_router_decisions(result.analyzer_routing), result.profile


def normalize_router_decisions(decisions) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {
        "recommended": [],
        "optional": [],
        "not_recommended": [],
    }
    for decision in decisions:
        analyzer_id = _decision_value(decision, "analyzer", "analyzer_id")
        recommendation = str(_decision_value(decision, "recommendation") or "")
        entry = {
            "analyzer": analyzer_id,
            "display_name": _decision_value(decision, "display_name"),
            "category": recommendation,
            "score": _decision_value(decision, "final_score"),
            "eligible": bool(_decision_value(decision, "eligible")),
            "eligibility_score": _decision_value(decision, "eligibility_score"),
            "suitability_score": _decision_value(decision, "suitability_score"),
            "reason": _first_reason(decision),
            "reasons": list(_decision_value(decision, "reasons") or []),
            "warnings": list(_decision_value(decision, "warnings") or []),
            "explanation": _decision_value(decision, "explanation"),
            "routing_reason": _decision_value(decision, "routing_reason"),
            "feature_evidence": _decision_value(decision, "parameters_tested") or {},
        }
        bucket = _bucket_for_recommendation(recommendation)
        buckets[bucket].append(entry)
    return buckets


def evaluate_router_output(scenario_id: str, expected_router: dict[str, Any], actual_details: dict[str, list[dict[str, Any]]], profile: dict[str, Any]) -> RouterEvaluation:
    recommended = _names(actual_details["recommended"])
    optional = _names(actual_details["optional"])
    not_recommended = _names(actual_details["not_recommended"])

    required_original = [str(item) for item in expected_router.get("required_recommended", [])]
    forbidden_original = [str(item) for item in expected_router.get("forbidden_recommended", [])]
    allowed_optional = {_normalize_name(str(item)) for item in expected_router.get("allowed_optional", [])}
    required = {_normalize_name(item): item for item in required_original}
    forbidden = {_normalize_name(item): item for item in forbidden_original}

    missing_required = [original for normalized, original in required.items() if normalized not in recommended]
    incorrectly_recommended = [original for normalized, original in forbidden.items() if normalized in recommended]
    unexpected_optional = sorted(item for item in optional if item not in allowed_optional)
    required_detected = [str(item) for item in expected_router.get("required_detected_profiles", [])]
    forbidden_detected = [str(item) for item in expected_router.get("forbidden_detected_profiles", [])]
    detected = {_normalize_name(str(item)) for item in profile.get("detected_profiles", [])}
    missing_detected_profiles = [item for item in required_detected if _normalize_name(item) not in detected]
    forbidden_detected_profiles = [item for item in forbidden_detected if _normalize_name(item) in detected]
    required_ineligible = _required_ineligible(required, actual_details)

    checks = {
        "required_recommended_present": not missing_required,
        "forbidden_recommended_absent": not incorrectly_recommended,
        "required_analyzers_eligible": not required_ineligible,
        "required_detected_profiles_present": not missing_detected_profiles,
        "forbidden_detected_profiles_absent": not forbidden_detected_profiles,
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    return RouterEvaluation(
        scenario_id=scenario_id,
        status=status,
        checks=checks,
        missing_required=missing_required,
        incorrectly_recommended=incorrectly_recommended,
        missing_detected_profiles=missing_detected_profiles,
        forbidden_detected_profiles=forbidden_detected_profiles,
        unexpected_optional=unexpected_optional,
        required_ineligible=required_ineligible,
        actual={
            "recommended": _original_names(actual_details["recommended"]),
            "optional": _original_names(actual_details["optional"]),
            "not_recommended": _original_names(actual_details["not_recommended"]),
        },
        actual_details=actual_details,
        profile=profile,
    )


def run_benchmark(scenario_dir: Path) -> RouterEvaluation:
    scenario_dir = scenario_dir.resolve()
    ground_truth_path = scenario_dir / "ground_truth.yaml"
    if not ground_truth_path.exists():
        raise RouterBenchmarkExecutionError(f"Ground truth file is missing: {ground_truth_path}")

    ground_truth = _load_yaml(ground_truth_path)
    expected_router = ground_truth.get("expected_router")
    if not isinstance(expected_router, dict):
        raise RouterBenchmarkExecutionError(f"Ground truth file has no expected_router mapping: {ground_truth_path}")

    scenario_id = str(ground_truth.get("scenario", {}).get("id") or ground_truth.get("scenario_id") or scenario_dir.name)
    documented_gap = _documented_gap(ground_truth)
    try:
        actual_details, profile = run_router(scenario_dir)
        evaluation = evaluate_router_output(scenario_id, expected_router, actual_details, profile)
        if documented_gap:
            evaluation.status = "GAP"
            evaluation.documented_gap = documented_gap
    except RouterBenchmarkExecutionError as exc:
        evaluation = RouterEvaluation(
            scenario_id=scenario_id,
            status="GAP" if documented_gap else "ERROR",
            checks={
                "required_recommended_present": bool(documented_gap),
                "forbidden_recommended_absent": bool(documented_gap),
            },
            missing_required=[],
            incorrectly_recommended=[],
            missing_detected_profiles=[],
            forbidden_detected_profiles=[],
            unexpected_optional=[],
            required_ineligible=[],
            actual={"recommended": [], "optional": [], "not_recommended": []},
            actual_details={"recommended": [], "optional": [], "not_recommended": []},
            profile={},
            execution_error=str(exc),
            documented_gap=documented_gap,
        )

    write_report(evaluation)
    return evaluation


def write_report(evaluation: RouterEvaluation) -> None:
    reports_dir = PROJECT_ROOT / "benchmark" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / f"{evaluation.scenario_id}_router.json"
    markdown_path = reports_dir / f"{evaluation.scenario_id}_router.md"

    payload = asdict(evaluation)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")

    lines = [
        f"# Router Benchmark Report: {evaluation.scenario_id}",
        "",
        f"- Status: `{evaluation.status}`",
        f"- Recommended: `{evaluation.actual['recommended']}`",
        f"- Optional: `{evaluation.actual['optional']}`",
        f"- Not recommended: `{evaluation.actual['not_recommended']}`",
        "",
        "## Checks",
        "",
    ]
    for name, passed in evaluation.checks.items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} `{name}`")
    if evaluation.missing_required:
        lines.extend(["", f"Missing required recommendations: `{evaluation.missing_required}`"])
    if evaluation.incorrectly_recommended:
        lines.extend(["", f"Incorrectly recommended analyzers: `{evaluation.incorrectly_recommended}`"])
    if evaluation.missing_detected_profiles:
        lines.extend(["", f"Missing detected profiles: `{evaluation.missing_detected_profiles}`"])
    if evaluation.forbidden_detected_profiles:
        lines.extend(["", f"Forbidden detected profiles: `{evaluation.forbidden_detected_profiles}`"])
    if evaluation.unexpected_optional:
        lines.extend(["", f"Unexpected optional analyzers: `{evaluation.unexpected_optional}`"])
    if evaluation.required_ineligible:
        lines.extend(["", f"Required analyzers marked ineligible: `{evaluation.required_ineligible}`"])
    if evaluation.execution_error:
        lines.extend(["", f"Execution error: `{evaluation.execution_error}`"])
    if evaluation.documented_gap:
        lines.extend(["", f"Documented gap: `{evaluation.documented_gap}`"])
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Ops Signals router benchmarks")
    parser.add_argument("--scenario", required=True, help="Path to benchmark scenario directory")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    evaluation = run_benchmark(Path(args.scenario))
    print(json.dumps(asdict(evaluation), indent=2, sort_keys=True, default=_json_default))
    if evaluation.status != "PASS":
        raise SystemExit(1)


def _bucket_for_recommendation(recommendation: str) -> str:
    normalized = recommendation.strip().upper()
    if normalized == RECOMMENDED:
        return "recommended"
    if normalized == OPTIONAL:
        return "optional"
    return "not_recommended"


def _first_reason(decision) -> str:
    routing_reason = _decision_value(decision, "routing_reason")
    if routing_reason:
        return str(routing_reason)
    reasons = _decision_value(decision, "reasons") or []
    if reasons:
        return str(reasons[0])
    warnings = _decision_value(decision, "warnings") or []
    if warnings:
        return str(warnings[0])
    return str(_decision_value(decision, "explanation") or "")


def _decision_value(decision, *names: str) -> Any:
    for name in names:
        if isinstance(decision, dict) and name in decision:
            return decision[name]
        if hasattr(decision, name):
            return getattr(decision, name)
    return None


def _normalize_name(value: str) -> str:
    return value.strip().lower()


def _names(entries: list[dict[str, Any]]) -> set[str]:
    return {_normalize_name(str(entry["analyzer"])) for entry in entries}


def _original_names(entries: list[dict[str, Any]]) -> list[str]:
    return [str(entry["analyzer"]) for entry in entries]


def _required_ineligible(required: dict[str, str], actual_details: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    all_entries = [entry for entries in actual_details.values() for entry in entries]
    ineligible = []
    for entry in all_entries:
        normalized = _normalize_name(str(entry["analyzer"]))
        if normalized in required and not bool(entry["eligible"]):
            ineligible.append(
                {
                    "analyzer": entry["analyzer"],
                    "category": entry["category"],
                    "reason": entry["reason"],
                }
            )
    return ineligible


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise RouterBenchmarkExecutionError(f"YAML file must contain a mapping: {path}")
    return data


def _documented_gap(ground_truth: dict[str, Any]) -> str | None:
    validation = ground_truth.get("validation") or {}
    router_validation = validation.get("router") if isinstance(validation, dict) else {}
    if isinstance(router_validation, dict) and router_validation.get("expected_status") == "GAP":
        return str(router_validation.get("gap_reason") or "Scenario documents a router capability gap.")
    return None


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


if __name__ == "__main__":
    main()
