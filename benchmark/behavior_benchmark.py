"""Behavior Intelligence benchmark: validates that correlated signals across MULTIPLE metrics
produce the right cross-metric behavior finding, not just that one analyzer fires on one metric.
Every scenario in router_benchmark.py is single-metric; this is the multi-metric counterpart."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from backend.app.behavior_intelligence.service import BehaviorIntelligenceService
from backend.app.models.db import get_engine, get_session_local, init_engine
from backend.app.models.entities import Base
from backend.app.services.timeseries_routing_service import build_csv_routing_config
from benchmark.router_benchmark import DEFAULT_ANALYZER_REGISTRY_DIR, PROJECT_ROOT
from backend.app.services.timeseries_routing_service import TimeSeriesRoutingService
from intelligence.analyzer_registry import AnalyzerRegistrationError, instantiate, load_registrations
from intelligence.analyzer_selection import RegistryAnalyzerSelection
from intelligence.analyzers.base import Analyzer
from intelligence.config import AppConfig
from intelligence.normalize.normalizer import normalize_timeseries

DEFAULT_BEHAVIOR_DEFINITIONS_DIR = PROJECT_ROOT / "config" / "behavior_definitions.d"

# "all" runs every registered analyzer on every metric. "default" runs only what the router
# selects for each metric under the provider config's selection mode (recommended_threshold),
# routing each metric on its own the way a scheduled run does - the mode real users get.
MODES = ("all", "default")


class BehaviorBenchmarkExecutionError(RuntimeError):
    """Raised when behavior benchmark execution cannot produce an evaluation."""


@dataclass(slots=True)
class BehaviorEvaluation:
    scenario_id: str
    status: str
    checks: dict[str, bool]
    matched_definition_ids: list[str]
    missing_required: list[str]
    incorrectly_matched: list[str]
    matched_findings: list[dict[str, Any]] = field(default_factory=list)
    execution_error: str | None = None
    mode: str = "all"
    analyzers_by_metric: dict[str, list[str]] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


def load_scenario_dataframe(scenario_dir: Path) -> pd.DataFrame:
    dataset_path = scenario_dir / "dataset.csv"
    if not dataset_path.exists():
        raise BehaviorBenchmarkExecutionError(f"Scenario dataset is missing: {dataset_path}")
    dataframe = pd.read_csv(dataset_path)
    if dataframe.empty:
        raise BehaviorBenchmarkExecutionError(f"Scenario dataset is empty: {dataset_path}")
    return dataframe


class _RouterSelection(RegistryAnalyzerSelection):
    def __init__(self, config: AppConfig) -> None:
        self.config = config


def _all_analyzers() -> list[Analyzer]:
    analyzers = []
    for registration in load_registrations(DEFAULT_ANALYZER_REGISTRY_DIR):
        try:
            analyzers.append(instantiate(registration))
        except AnalyzerRegistrationError:
            continue
    return analyzers


def _router_selected_analyzers(metric_frame: pd.DataFrame, config: AppConfig) -> list[Analyzer]:
    try:
        routing = TimeSeriesRoutingService().route_normalized(metric_frame).analyzer_routing
    except ValueError as exc:
        raise BehaviorBenchmarkExecutionError(str(exc)) from exc
    return _RouterSelection(config)._build_analyzers(routing)


def run_behavior_evaluation(
    scenario_dir: Path,
    *,
    mode: str = "all",
    service_name: str = "benchmark-behavior",
    analysis_run_id: str = "behavior-benchmark-run",
) -> tuple[list, dict[str, list[str]]]:
    """Normalizes the scenario's (possibly multi-metric) CSV, runs the real analyzers against each
    metric (every one in "all" mode, the router's picks in "default" mode), and hands all resulting
    signals to the real BehaviorIntelligenceService - the same shared evaluate() production code
    uses, not a mock. Returns the findings and which analyzers ran on each metric."""
    if mode not in MODES:
        raise BehaviorBenchmarkExecutionError(f"Unknown mode {mode!r}; expected one of {MODES}")
    dataframe = load_scenario_dataframe(scenario_dir)
    config = build_csv_routing_config(
        provider="prometheus",
        service=service_name,
        metric_name="unspecified",
        interval="5m",
        analyzer_id="all",
        preview=True,
    )
    try:
        normalized = normalize_timeseries(dataframe, config.input)
    except ValueError as exc:
        raise BehaviorBenchmarkExecutionError(str(exc)) from exc
    if normalized.empty:
        raise BehaviorBenchmarkExecutionError(f"Normalization produced no rows for {scenario_dir}")
    normalized = normalized.copy()
    normalized["service"] = service_name

    all_signals = []
    analyzers_by_metric: dict[str, list[str]] = {}
    for metric_name, metric_frame in normalized.groupby("metric_name"):
        metric_frame = metric_frame.reset_index(drop=True)
        analyzers = _all_analyzers() if mode == "all" else _router_selected_analyzers(metric_frame, config)
        analyzers_by_metric[str(metric_name)] = sorted(analyzer.analyzer_id for analyzer in analyzers)
        for analyzer in analyzers:
            try:
                signals = analyzer.analyze(metric_frame)
            except Exception:
                continue
            for signal in signals:
                signal.service = service_name
                signal.analysis_run_id = analysis_run_id
            all_signals.extend(signals)

    signal_dicts = [asdict(signal) for signal in all_signals]

    init_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=get_engine())
    db = get_session_local()()
    try:
        behavior_service = BehaviorIntelligenceService(DEFAULT_BEHAVIOR_DEFINITIONS_DIR)
        return behavior_service.evaluate(signal_dicts, db), analyzers_by_metric
    finally:
        db.close()


def evaluate_behavior_output(scenario_id: str, expected_behavior: dict[str, Any], findings: list) -> BehaviorEvaluation:
    matched = {str(finding.definition_id) for finding in findings}
    required = [str(item) for item in expected_behavior.get("required_matched", [])]
    forbidden = [str(item) for item in expected_behavior.get("forbidden_matched", [])]

    missing_required = [item for item in required if item not in matched]
    incorrectly_matched = [item for item in forbidden if item in matched]

    checks = {
        "required_behaviors_matched": not missing_required,
        "forbidden_behaviors_absent": not incorrectly_matched,
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    return BehaviorEvaluation(
        scenario_id=scenario_id,
        status=status,
        checks=checks,
        matched_definition_ids=sorted(matched),
        missing_required=missing_required,
        incorrectly_matched=incorrectly_matched,
        matched_findings=[
            {"definition_id": finding.definition_id, "title": finding.title, "severity": finding.severity, "confidence": finding.confidence}
            for finding in findings
        ],
    )


def run_benchmark(scenario_dir: Path, *, mode: str = "all", reports_dir: Path | None = None) -> BehaviorEvaluation:
    scenario_dir = scenario_dir.resolve()
    ground_truth_path = scenario_dir / "ground_truth.yaml"
    if not ground_truth_path.exists():
        raise BehaviorBenchmarkExecutionError(f"Ground truth file is missing: {ground_truth_path}")

    ground_truth = yaml.safe_load(ground_truth_path.read_text(encoding="utf-8")) or {}
    expected_behavior = ground_truth.get("expected_behavior_findings")
    if not isinstance(expected_behavior, dict):
        raise BehaviorBenchmarkExecutionError(f"Ground truth file has no expected_behavior_findings mapping: {ground_truth_path}")

    scenario_id = str(ground_truth.get("scenario", {}).get("id") or scenario_dir.name)
    try:
        findings, analyzers_by_metric = run_behavior_evaluation(scenario_dir, mode=mode)
        evaluation = evaluate_behavior_output(scenario_id, expected_behavior, findings)
        evaluation.analyzers_by_metric = analyzers_by_metric
    except BehaviorBenchmarkExecutionError as exc:
        evaluation = BehaviorEvaluation(
            scenario_id=scenario_id,
            status="ERROR",
            checks={},
            matched_definition_ids=[],
            missing_required=[],
            incorrectly_matched=[],
            execution_error=str(exc),
        )
    evaluation.mode = mode

    write_report(evaluation, reports_dir=reports_dir)
    return evaluation


def write_report(evaluation: BehaviorEvaluation, *, reports_dir: Path | None = None) -> None:
    reports_dir = reports_dir or (PROJECT_ROOT / "benchmark" / "reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    suffix = "_behavior" if evaluation.mode == "all" else f"_behavior_{evaluation.mode}"
    json_path = reports_dir / f"{evaluation.scenario_id}{suffix}.json"
    markdown_path = reports_dir / f"{evaluation.scenario_id}{suffix}.md"

    payload = asdict(evaluation)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")

    lines = [
        f"# Behavior Benchmark Report: {evaluation.scenario_id}",
        "",
        f"- Status: `{evaluation.status}`",
        f"- Mode: `{evaluation.mode}`",
        f"- Matched definitions: `{evaluation.matched_definition_ids}`",
        "",
        "## Checks",
        "",
    ]
    for name, passed in evaluation.checks.items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} `{name}`")
    if evaluation.missing_required:
        lines.extend(["", f"Missing required behaviors: `{evaluation.missing_required}`"])
    if evaluation.incorrectly_matched:
        lines.extend(["", f"Incorrectly matched (forbidden) behaviors: `{evaluation.incorrectly_matched}`"])
    if evaluation.execution_error:
        lines.extend(["", f"Execution error: `{evaluation.execution_error}`"])
    if evaluation.analyzers_by_metric:
        lines.extend(["", "## Analyzers run", ""])
        lines.extend(f"- `{metric}`: `{analyzers}`" for metric, analyzers in evaluation.analyzers_by_metric.items())
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Ops Signals Behavior Intelligence benchmarks")
    parser.add_argument("--scenario", required=True, help="Path to benchmark scenario directory")
    parser.add_argument("--mode", choices=MODES, default="all", help="Which analyzers run: every one, or the router's default picks.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    evaluation = run_benchmark(Path(args.scenario), mode=args.mode)
    print(json.dumps(asdict(evaluation), indent=2, sort_keys=True, default=_json_default))
    if evaluation.status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
