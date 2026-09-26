from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from backend.app.services.timeseries_routing_service import TimeSeriesRoutingService, build_csv_routing_config
from intelligence.analyzer_registry import AnalyzerRegistrationError, instantiate, load_registrations
from intelligence.finding_aggregator import FindingAggregator

# health_status values a finding can carry (see FindingAggregator._health_status) that should be
# treated as an actionable, user-facing alert rather than background noise.
ACTIONABLE_HEALTH_STATUSES = {"critical", "significant"}


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MINIMUM_ROUTER_POINTS = 30
RECOMMENDED = "RECOMMENDED"
OPTIONAL = "OPTIONAL"
NOT_RECOMMENDED = "NOT_RECOMMENDED"
REJECTED = "REJECTED"

# Router-facing analyzer ids that resolve to a differently-named pipeline analyzer at runtime -
# mirrors intelligence.pipeline.SignalPipeline._router_to_pipeline_analyzers. Router ids not
# listed here are assumed to equal their pipeline analyzer_id directly.
ROUTER_TO_PIPELINE_ANALYZER_ID = {"trend_regression": "trend"}

DEFAULT_ANALYZER_REGISTRY_DIR = PROJECT_ROOT / "config" / "analyzer_registry.d"


class RouterBenchmarkExecutionError(RuntimeError):
    """Raised when router benchmark execution cannot produce routing decisions."""


@dataclass(slots=True)
class DetectionEvaluation:
    """Result of actually running the recommended analyzer and checking what it found against
    a scenario's expected_event, when the scenario's ground truth declares one."""

    analyzer_id: str
    checks: dict[str, bool]
    details: dict[str, Any] = field(default_factory=dict)
    execution_error: str | None = None

    @property
    def passed(self) -> bool:
        return all(self.checks.values())


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
    detection_checks: dict[str, bool] = field(default_factory=dict)
    detection_details: dict[str, Any] = field(default_factory=dict)

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


def run_router(scenario_dir: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any], pd.DataFrame]:
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
    return normalize_router_decisions(result.analyzer_routing), result.profile, result.normalized


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

    # Opt-in: recall (does the required analyzer show up) is always checked above, but precision
    # (does anything UNEXPECTED also show up with real confidence) is only checked when a scenario
    # explicitly asks for it - retrofitting this onto every existing scenario at once risks baking
    # in today's untuned router noise as permanent ground truth. New/tightened scenarios can opt in.
    if bool(expected_router.get("strict_precision")):
        permitted = set(required) | allowed_optional
        unexpected_optional = sorted(item for item in (recommended | optional) if item not in permitted)
        checks["no_unexpected_recommendations"] = not unexpected_optional
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


def evaluate_detection_accuracy(
    ground_truth: dict[str, Any],
    dataframe: pd.DataFrame,
    required_recommended: list[str],
) -> DetectionEvaluation | None:
    """Actually run the required analyzer and check what it found against expected_event -
    correct direction, magnitude, and timing - not just "was the right analyzer recommended".

    Returns None (not a failure) when the scenario has no expected_event to check, or when the
    required analyzer has no real runnable implementation yet (e.g. kats/darts/river/alibi_detect
    are router-only today - see docs/16-analyzer-recommendation.md, "Router-only analyzers").
    """
    expected_event = ground_truth.get("expected_event")
    if not expected_event or not required_recommended:
        return None

    analyzer_id = required_recommended[0]
    analyzer = _instantiate_analyzer(analyzer_id)
    if analyzer is None:
        return None

    try:
        signals = analyzer.analyze(dataframe)
    except Exception as exc:
        return DetectionEvaluation(analyzer_id=analyzer_id, checks={"analyzer_ran_without_error": False}, execution_error=str(exc))

    checks: dict[str, bool] = {"analyzer_produced_signal": bool(signals)}
    if not signals:
        return DetectionEvaluation(analyzer_id=analyzer_id, checks=checks)

    matched_evidence = next((_extract_shift_evidence(signal) for signal in signals if _extract_shift_evidence(signal)), None)
    if matched_evidence is None:
        checks["event_evidence_recognized"] = False
        return DetectionEvaluation(analyzer_id=analyzer_id, checks=checks)
    checks["event_evidence_recognized"] = True

    percent_change = matched_evidence["percent_change"]
    ordered = dataframe.sort_values("timestamp").reset_index(drop=True)
    ordered["timestamp"] = pd.to_datetime(ordered["timestamp"], utc=True)
    change_point_index = matched_evidence["change_point_index"]
    detected_timestamp = ordered.iloc[change_point_index]["timestamp"] if 0 <= change_point_index < len(ordered) else None

    details: dict[str, Any] = {
        "percent_change": percent_change,
        "detected_timestamp": detected_timestamp.isoformat() if detected_timestamp is not None else None,
    }

    expected_direction = expected_event.get("direction")
    if expected_direction:
        actual_direction = "increase" if percent_change >= 0 else "decrease"
        checks["direction_matches"] = actual_direction == expected_direction
        details["expected_direction"] = expected_direction
        details["actual_direction"] = actual_direction

    minimum_magnitude = expected_event.get("minimum_magnitude")
    if minimum_magnitude is not None:
        checks["magnitude_meets_minimum"] = abs(percent_change) >= float(minimum_magnitude)
        details["minimum_magnitude"] = minimum_magnitude

    expected_timestamp = expected_event.get("timestamp")
    if expected_timestamp and detected_timestamp is not None:
        expected_dt = pd.to_datetime(expected_timestamp, utc=True)
        tolerance_before = expected_event.get("tolerance_before")
        tolerance_after = expected_event.get("tolerance_after")
        lower = expected_dt - (pd.Timedelta(tolerance_before) if tolerance_before else pd.Timedelta(0))
        upper = expected_dt + (pd.Timedelta(tolerance_after) if tolerance_after else pd.Timedelta(0))
        checks["timestamp_within_tolerance"] = lower <= detected_timestamp <= upper
        details["expected_timestamp"] = expected_dt.isoformat()
    elif expected_timestamp and detected_timestamp is None:
        checks["timestamp_within_tolerance"] = False
        details["expected_timestamp"] = str(expected_timestamp)

    return DetectionEvaluation(analyzer_id=analyzer_id, checks=checks, details=details)


def evaluate_false_positive_control(ground_truth: dict[str, Any], normalized: pd.DataFrame, profile: dict[str, Any]) -> DetectionEvaluation | None:
    """Negative-control check for a scenario declaring expects_no_actionable_findings: run every
    real analyzer against the data and check that finding aggregation - the same downstream
    filtering production uses - doesn't turn the result into a user-facing critical/significant
    alert. Individual analyzers (pyod_outlier especially, with a nonzero contamination rate) are
    expected to emit some raw statistical noise on any input; what matters for alert fatigue is
    whether that noise survives into an actionable finding."""
    if not ground_truth.get("expects_no_actionable_findings"):
        return None

    all_signals = []
    signal_counts: dict[str, int] = {}
    errors: dict[str, str] = {}
    for registration in load_registrations(DEFAULT_ANALYZER_REGISTRY_DIR):
        try:
            analyzer = instantiate(registration)
        except AnalyzerRegistrationError:
            continue
        try:
            signals = analyzer.analyze(normalized)
        except Exception as exc:
            errors[registration.analyzer_id] = str(exc)
            continue
        signal_counts[registration.analyzer_id] = len(signals)
        all_signals.extend(signals)

    aggregation = FindingAggregator().aggregate(all_signals, normalized, profile)
    actionable = [finding for finding in aggregation.findings if finding.health_status in ACTIONABLE_HEALTH_STATUSES]

    details: dict[str, Any] = {
        "raw_signal_counts": signal_counts,
        "total_raw_signals": len(all_signals),
        "total_findings": len(aggregation.findings),
        "actionable_findings": [
            {"title": finding.title, "health_status": finding.health_status, "importance_score": finding.importance_score}
            for finding in actionable
        ],
    }
    if errors:
        details["analyzer_errors"] = errors

    return DetectionEvaluation(analyzer_id="all", checks={"no_actionable_findings": not actionable}, details=details)


def _instantiate_analyzer(router_analyzer_id: str):
    pipeline_analyzer_id = ROUTER_TO_PIPELINE_ANALYZER_ID.get(router_analyzer_id, router_analyzer_id)
    registrations = {registration.analyzer_id: registration for registration in load_registrations(DEFAULT_ANALYZER_REGISTRY_DIR)}
    registration = registrations.get(pipeline_analyzer_id)
    if registration is None:
        return None
    try:
        return instantiate(registration)
    except AnalyzerRegistrationError:
        return None


def _extract_shift_evidence(signal) -> dict[str, Any] | None:
    """Ruptures and BaselineShift both report a percent_change and a change_point_index into the
    sorted input series - the two fields expected_event actually needs to be checked."""
    evidence = getattr(signal, "evidence", None) or {}
    if "percent_change" not in evidence or "change_point_index" not in evidence:
        return None
    return {"percent_change": float(evidence["percent_change"]), "change_point_index": int(evidence["change_point_index"])}


def run_benchmark(scenario_dir: Path, *, reports_dir: Path | None = None) -> RouterEvaluation:
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
        actual_details, profile, normalized = run_router(scenario_dir)
        evaluation = evaluate_router_output(scenario_id, expected_router, actual_details, profile)
        if documented_gap:
            evaluation.status = "GAP"
            evaluation.documented_gap = documented_gap
        elif evaluation.status == "PASS":
            required = [str(item) for item in expected_router.get("required_recommended", [])]
            detection = evaluate_detection_accuracy(ground_truth, normalized, required)
            if detection is None:
                detection = evaluate_false_positive_control(ground_truth, normalized, profile)
            if detection is not None:
                evaluation.detection_checks = detection.checks
                evaluation.detection_details = detection.details
                for name, check_passed in detection.checks.items():
                    evaluation.checks[f"detection_{name}"] = check_passed
                if not detection.passed:
                    evaluation.status = "FAIL"
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

    write_report(evaluation, reports_dir=reports_dir)
    return evaluation


def write_report(evaluation: RouterEvaluation, *, reports_dir: Path | None = None) -> None:
    reports_dir = reports_dir or (PROJECT_ROOT / "benchmark" / "reports")
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
    if evaluation.detection_details:
        lines.extend(["", "## Detection Accuracy", "", f"`{evaluation.detection_details}`"])
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
