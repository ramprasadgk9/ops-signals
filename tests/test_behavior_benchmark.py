from __future__ import annotations

from pathlib import Path

import pytest

from benchmark.behavior_benchmark import BehaviorBenchmarkExecutionError, evaluate_behavior_output, run_benchmark
from benchmark.run_behavior_scenarios import discover_scenarios, exit_code, run_suite

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_ROOT = PROJECT_ROOT / "benchmark" / "scenarios"


class _FakeFinding:
    def __init__(self, definition_id: str) -> None:
        self.definition_id = definition_id
        self.title = "fake"
        self.severity = "medium"
        self.confidence = 1.0


def test_evaluate_behavior_output_passes_when_required_definition_matched() -> None:
    result = evaluate_behavior_output(
        "scenario",
        {"required_matched": ["server_slow"], "forbidden_matched": ["cpu_throttling"]},
        [_FakeFinding("server_slow")],
    )

    assert result.status == "PASS"
    assert result.missing_required == []
    assert result.incorrectly_matched == []


def test_evaluate_behavior_output_fails_when_required_definition_is_missing() -> None:
    result = evaluate_behavior_output("scenario", {"required_matched": ["server_slow"]}, [])

    assert result.status == "FAIL"
    assert result.missing_required == ["server_slow"]


def test_evaluate_behavior_output_fails_when_a_forbidden_definition_matched() -> None:
    result = evaluate_behavior_output(
        "scenario",
        {"required_matched": [], "forbidden_matched": ["cpu_throttling"]},
        [_FakeFinding("cpu_throttling")],
    )

    assert result.status == "FAIL"
    assert result.incorrectly_matched == ["cpu_throttling"]


def test_server_slow_scenario_matches_its_correlated_cpu_and_memory_behavior() -> None:
    evaluation = run_benchmark(SCENARIOS_ROOT / "behavior_server_slow_v1")

    assert evaluation.status == "PASS"
    assert evaluation.matched_definition_ids == ["server_slow"]


def test_latency_error_cascade_scenario_matches_its_correlated_behavior() -> None:
    evaluation = run_benchmark(SCENARIOS_ROOT / "behavior_latency_error_cascade_v1")

    assert evaluation.status == "PASS"
    assert evaluation.matched_definition_ids == ["latency_error_cascade"]


def test_run_benchmark_reports_missing_dataset_as_execution_error(tmp_path: Path) -> None:
    scenario_dir = tmp_path / "scenario"
    scenario_dir.mkdir()
    (scenario_dir / "ground_truth.yaml").write_text(
        "scenario:\n  id: missing_dataset\nexpected_behavior_findings:\n  required_matched: []\n",
        encoding="utf-8",
    )

    result = run_benchmark(scenario_dir, reports_dir=tmp_path / "reports")

    assert result.status == "ERROR"
    assert "dataset is missing" in str(result.execution_error)


def test_discover_scenarios_only_finds_behavior_scenarios_not_router_scenarios() -> None:
    discovered = {path.name for path in discover_scenarios(SCENARIOS_ROOT)}

    assert discovered == {
        "behavior_server_slow_v1",
        "behavior_server_slow_memory_step_v1",
        "behavior_latency_error_cascade_v1",
    }


def test_suite_runner_passes_for_all_behavior_scenarios() -> None:
    evaluations = run_suite(SCENARIOS_ROOT)

    assert exit_code(evaluations) == 0
    assert all(evaluation.status == "PASS" for evaluation in evaluations)


def test_default_mode_runs_only_the_router_selected_analyzers_on_each_metric(tmp_path: Path) -> None:
    evaluation = run_benchmark(SCENARIOS_ROOT / "behavior_server_slow_v1", mode="default", reports_dir=tmp_path)

    assert evaluation.mode == "default"
    assert set(evaluation.analyzers_by_metric) == {"cpu_usage", "memory_usage"}
    # anomaly_zscore has no router entry, so default mode must never run it.
    assert all("anomaly_zscore" not in analyzers for analyzers in evaluation.analyzers_by_metric.values())
    assert (tmp_path / "behavior_server_slow_v1_behavior_default.json").exists()


@pytest.mark.parametrize(
    "scenario",
    ["behavior_server_slow_v1", "behavior_server_slow_memory_step_v1", "behavior_latency_error_cascade_v1"],
)
def test_default_mode_matches_the_expected_behavior(scenario: str, tmp_path: Path) -> None:
    evaluation = run_benchmark(SCENARIOS_ROOT / scenario, mode="default", reports_dir=tmp_path)

    assert evaluation.status == "PASS"


def test_default_mode_matches_a_memory_level_change_through_ruptures(tmp_path: Path) -> None:
    # Memory steps to a new level: the router picks ruptures for it but never runs baseline_shift,
    # so server_slow's memory.ruptures.signed_change_percent condition is what matches.
    evaluation = run_benchmark(SCENARIOS_ROOT / "behavior_server_slow_memory_step_v1", mode="default", reports_dir=tmp_path)

    assert "ruptures" in evaluation.analyzers_by_metric["memory_usage"]
    assert "baseline_shift" not in evaluation.analyzers_by_metric["memory_usage"]
    assert evaluation.matched_definition_ids == ["server_slow"]
