from __future__ import annotations

from pathlib import Path
import importlib.util

from backend.app.api.ingestion import PreviewPipelineStore
from backend.app.services.timeseries_routing_service import TimeSeriesRoutingService, build_csv_routing_config
from benchmark.router_benchmark import (
    evaluate_router_output,
    run_benchmark,
)
from benchmark.run_router_scenarios import exit_code, run_suite
from intelligence.pipeline import SignalPipeline


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCENARIO_DIR = PROJECT_ROOT / "benchmark" / "scenarios" / "cpu_baseline_shift_v1"


def test_router_benchmark_passes_cpu_baseline_shift_scenario() -> None:
    result = run_benchmark(SCENARIO_DIR)

    assert result.status in {"PASS", "FAIL"}
    assert set(result.actual) == {"recommended", "optional", "not_recommended"}
    assert result.execution_error is None


def test_optional_router_analyzers_do_not_fail_evaluation() -> None:
    expected = {
        "required_recommended": ["Ruptures"],
        "allowed_optional": ["Prophet", "River"],
        "forbidden_recommended": ["STUMPY"],
    }
    actual = {
        "recommended": [{"analyzer": " ruptures ", "eligible": True}],
        "optional": [{"analyzer": "prophet", "eligible": True}, {"analyzer": "river", "eligible": True}],
        "not_recommended": [{"analyzer": "stumpy", "eligible": True}],
    }

    result = evaluate_router_output("cpu_baseline_shift_v1", expected, actual, profile={})

    assert result.status == "PASS"
    assert result.missing_required == []
    assert result.incorrectly_recommended == []
    assert result.unexpected_optional == []


def test_forbidden_recommended_router_analyzer_fails_evaluation() -> None:
    expected = {
        "required_recommended": ["ruptures"],
        "forbidden_recommended": ["stumpy"],
    }
    actual = {
        "recommended": [{"analyzer": "ruptures", "eligible": True}, {"analyzer": "STUMPY", "eligible": True}],
        "optional": [],
        "not_recommended": [],
    }

    result = evaluate_router_output("cpu_baseline_shift_v1", expected, actual, profile={})

    assert result.status == "FAIL"
    assert result.incorrectly_recommended == ["stumpy"]


def test_run_benchmark_reports_missing_dataset_as_execution_error(tmp_path: Path) -> None:
    scenario_dir = tmp_path / "scenario"
    scenario_dir.mkdir()
    (scenario_dir / "ground_truth.yaml").write_text(
        """
scenario:
  id: missing_dataset
expected_router:
  required_recommended:
    - ruptures
""".strip(),
        encoding="utf-8",
    )

    result = run_benchmark(scenario_dir)

    assert result.status == "ERROR"
    assert "dataset is missing" in str(result.execution_error)


def test_phase_one_generated_profiles_are_behaviorally_distinct() -> None:
    expectations = {
        "cpu_pure_seasonality_v1": ({"seasonal", "repeating_pattern"}, {"baseline_shift", "regime_change", "trend", "spike", "mixed"}),
        "cpu_linear_trend_v1": ({"trend"}, {"baseline_shift", "regime_change", "seasonal", "repeating_pattern", "spike", "mixed"}),
        "cpu_isolated_spikes_v1": ({"spike", "anomaly", "outlier"}, {"baseline_shift", "regime_change", "seasonal", "trend"}),
        "cpu_seasonal_forecast_v1": ({"seasonal", "repeating_pattern", "trend"}, {"baseline_shift", "regime_change", "spike"}),
        "cpu_complex_forecast_v1": ({"seasonal", "repeating_pattern", "trend"}, {"baseline_shift", "regime_change", "spike"}),
        "cpu_mixed_behavior_v1": ({"seasonal", "repeating_pattern", "trend", "baseline_shift", "regime_change", "mixed"}, {"spike"}),
    }
    service = TimeSeriesRoutingService()
    config = build_csv_routing_config(
        provider="prometheus",
        service="benchmark-cpu",
        metric_name="cpu.usage_user",
        interval="5m",
        analyzer_id="all",
        preview=True,
    )

    for scenario_id, (required, forbidden) in expectations.items():
        module = _load_generator(scenario_id)
        result = service.route_dataframe(module.generate(), config.input)
        detected = set(result.profile["detected_profiles"])
        assert required.issubset(detected)
        assert detected.isdisjoint(forbidden)


def test_benchmark_uses_same_shared_routing_path_as_csv_validation_pipeline() -> None:
    module = _load_generator("cpu_pure_seasonality_v1")
    dataframe = module.generate()
    config = build_csv_routing_config(
        provider="prometheus",
        service="benchmark-cpu",
        metric_name="cpu.usage_user",
        interval="5m",
        analyzer_id="all",
        preview=True,
    )

    direct = TimeSeriesRoutingService().route_dataframe(dataframe, config.input)
    store = PreviewPipelineStore()
    pipeline = SignalPipeline(config, store=store).run_dataframe(
        dataframe,
        run_metadata={"file_name": "dataset.csv", "validation_preview": True},
    )

    direct_scores = {item["analyzer_id"]: (item["recommendation"], item["final_score"], item["routing_reason"]) for item in direct.analyzer_routing}
    pipeline_scores = {item["analyzer_id"]: (item["recommendation"], item["final_score"], item["routing_reason"]) for item in pipeline.analyzer_routing}

    assert direct.profile["detected_profiles"] == store.learning_snapshots[0]["snapshot"]["series_profile_json"]["detected_profiles"]
    assert direct_scores == pipeline_scores


def test_csv_routing_config_applies_analyzer_overrides_for_preview_runs() -> None:
    config = build_csv_routing_config(
        provider="generic",
        service="pyod-lab",
        metric_name="synthetic_pyod_value",
        interval="5m",
        analyzer_id="pyod_outlier",
        preview=True,
        analyzer_overrides={
            "pyod_outlier": {
                "implementation": {
                    "library": "pyod",
                    "detector": "KNN",
                    "detector_type": "knn",
                    "contamination": 0.0278,
                    "min_samples": 75,
                    "grouping_gap": "10m",
                },
                "finding_rules": {"min_outlier_points": 8, "min_confidence": 0.75, "window": "15m"},
            }
        },
    )

    params = config.analysis.analyzers["pyod_outlier"].params
    assert params["implementation"]["contamination"] == 0.0278
    assert params["implementation"]["min_samples"] == 75
    assert params["implementation"]["grouping_gap"] == "10m"
    assert params["finding_rules"] == {"min_outlier_points": 8, "min_confidence": 0.75, "window": "15m"}
    assert config.analysis.selected_analyzers == ["pyod_outlier"]


def test_baseline_shift_params_prefer_finding_rules_schema() -> None:
    params = SignalPipeline._baseline_shift_params(
        {
            "finding_rules": {"min_change_percent": 40, "min_effect_size": 2.5},
            "statistical_gate": {"min_effect_size": 1.5},
            "operational_significance": {"min_change_percent": 25},
            "ruptures": {"min_size": 7, "jump": 3},
        }
    )

    assert params["threshold_percent"] == 40
    assert params["change_threshold"] == 2.5
    assert params["min_segment_size"] == 7
    assert params["ruptures_jump"] == 3


def test_router_suite_runner_returns_success_for_phase_one_scenarios() -> None:
    scenarios_root = PROJECT_ROOT / "benchmark" / "scenarios"
    evaluations = [
        run_benchmark(scenarios_root / scenario)
        for scenario in [
            "cpu_pure_baseline_shift_v1",
            "cpu_pure_baseline_shift_shifted_dates_v1",
            "cpu_pure_seasonality_v1",
            "cpu_linear_trend_v1",
            "cpu_isolated_spikes_v1",
            "cpu_seasonal_forecast_v1",
            "cpu_complex_forecast_v1",
            "cpu_mixed_behavior_v1",
        ]
    ]

    assert exit_code(evaluations) == 0
    assert all(evaluation.status == "PASS" for evaluation in evaluations)


def test_suite_runner_discovers_scenario_directories() -> None:
    evaluations = run_suite(PROJECT_ROOT / "benchmark" / "scenarios")

    assert {evaluation.scenario_id for evaluation in evaluations} >= {
        "cpu_pure_baseline_shift_v1",
        "cpu_pure_baseline_shift_shifted_dates_v1",
        "cpu_pure_seasonality_v1",
        "cpu_linear_trend_v1",
        "cpu_isolated_spikes_v1",
        "cpu_seasonal_forecast_v1",
        "cpu_complex_forecast_v1",
        "cpu_mixed_behavior_v1",
        "cpu_distribution_drift_v1",
        "cpu_online_anomaly_stream_v1",
    }


def test_context_dependent_advanced_scenarios_are_documented_gaps() -> None:
    scenarios_root = PROJECT_ROOT / "benchmark" / "scenarios"

    drift = run_benchmark(scenarios_root / "cpu_distribution_drift_v1")
    river = run_benchmark(scenarios_root / "cpu_online_anomaly_stream_v1")

    assert drift.status == "GAP"
    assert "distribution_drift" in str(drift.documented_gap)
    assert river.status == "GAP"
    assert "execution_mode=streaming" in str(river.documented_gap)
    assert exit_code([drift, river]) == 0


def _load_generator(scenario_id: str):
    path = PROJECT_ROOT / "benchmark" / "scenarios" / scenario_id / "generate_dataset.py"
    spec = importlib.util.spec_from_file_location(f"{scenario_id}_generator", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
