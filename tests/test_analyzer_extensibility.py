"""An analyzer added through the Add Analyzer wizard (a config/analyzer_registry.d/ registration)
must run on autonomous runs as well as CSV runs, show up in recommendations, and be able to opt
into flat/gappy series and always-run selection."""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
import yaml

from backend.app.api.admin_analyzers import AnalyzerConfigIn, ScoringRuleIn
from backend.app.api.analyzer_labs import _config_to_registration_dict
from backend.app.autonomous.metric_executor import MetricAnalysisExecutor
from backend.app.metric_analyzer_recommendations.service import MetricAnalyzerRecommendationService
from experiments.analyzer_router import analyzer_registry as router_registry_module
from experiments.analyzer_router.router import UniversalTimeSeriesRouter
from intelligence import analyzer_selection
from intelligence.analyzer_registry import load_registrations
from intelligence.config import load_config
from intelligence.pipeline import SignalPipeline

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILTIN_IDS = {"baseline_shift", "ruptures", "anomaly_zscore", "pyod_outlier", "trend", "stumpy", "prophet"}
# A real, committed adapter whose constructor takes **config - stands in for a wizard-added analyzer.
CUSTOM_ID = "statsforecast_forecast"
CUSTOM_CLASS_PATH = "backend.app.analyzers.custom.statsforecast_forecast.StatsforecastForecastAnalyzer"


class NullStore:
    engine = None


def _config():
    return load_config(PROJECT_ROOT / "config.yaml")


def _registry_dir_with_custom(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, always_run: bool = False) -> Path:
    registry_dir = tmp_path / "config" / "analyzer_registry.d"
    registry_dir.mkdir(parents=True)
    shutil.copy(PROJECT_ROOT / "config" / "analyzer_registry.d" / "builtin.yml", registry_dir / "builtin.yml")
    entry = {"display_name": "Custom Probe", "class_path": CUSTOM_CLASS_PATH}
    if always_run:
        entry["always_run"] = True
    (registry_dir / f"custom_{CUSTOM_ID}.yml").write_text(yaml.safe_dump({"analyzers": {CUSTOM_ID: entry}}))
    monkeypatch.setattr(analyzer_selection, "_REPO_ROOT", tmp_path)
    return registry_dir


def test_autonomous_executor_builds_the_same_analyzers_as_the_pipeline_including_custom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _registry_dir_with_custom(tmp_path, monkeypatch)
    config = _config()
    config.analysis.selection_mode = "all"

    executor_ids = {a.analyzer_id for a in MetricAnalysisExecutor(config, store=NullStore())._build_analyzers([])}
    pipeline_ids = {a.analyzer_id for a in SignalPipeline(config=config, store=NullStore())._build_analyzers([])}

    assert executor_ids == pipeline_ids
    assert BUILTIN_IDS | {CUSTOM_ID} <= executor_ids


def test_autonomous_executor_honors_config_disable_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _registry_dir_with_custom(tmp_path, monkeypatch)
    config = _config()
    config.analysis.selection_mode = "all"
    config.analysis.analyzers["trend"].enabled = False

    executor_ids = {a.analyzer_id for a in MetricAnalysisExecutor(config, store=NullStore())._build_analyzers([])}

    assert "trend" not in executor_ids
    assert CUSTOM_ID in executor_ids


def _threshold_config(max_analyzers: int):
    config = _config()
    config.analysis.selection_mode = "recommended_threshold"
    config.analysis.recommendation_execution.min_score = 0.8
    config.analysis.recommendation_execution.max_analyzers = max_analyzers
    config.analysis.recommendation_execution.include_optional = False
    return config


def test_always_run_analyzer_is_selected_outside_the_max_analyzers_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _registry_dir_with_custom(tmp_path, monkeypatch, always_run=True)
    routing = [
        {"analyzer_id": "ruptures", "recommendation": "RECOMMENDED", "final_score": 1.0},
        {"analyzer_id": "stumpy", "recommendation": "RECOMMENDED", "final_score": 0.9},
        {"analyzer_id": CUSTOM_ID, "recommendation": "NOT_RECOMMENDED", "final_score": 0.1},
    ]

    for runner in (MetricAnalysisExecutor(_threshold_config(1), store=NullStore()), SignalPipeline(config=_threshold_config(1), store=NullStore())):
        assert runner._allowed_pipeline_analyzers(routing) == {"ruptures", CUSTOM_ID}


def test_always_run_analyzer_still_respects_a_router_rejection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _registry_dir_with_custom(tmp_path, monkeypatch, always_run=True)
    routing = [
        {"analyzer_id": "ruptures", "recommendation": "RECOMMENDED", "final_score": 1.0},
        {"analyzer_id": CUSTOM_ID, "recommendation": "REJECTED", "final_score": 0.0},
    ]

    allowed = SignalPipeline(config=_threshold_config(3), store=NullStore())._allowed_pipeline_analyzers(routing)

    assert allowed == {"ruptures"}


def test_analyzers_without_always_run_keep_the_existing_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _registry_dir_with_custom(tmp_path, monkeypatch, always_run=False)
    routing = [
        {"analyzer_id": "ruptures", "recommendation": "RECOMMENDED", "final_score": 1.0},
        {"analyzer_id": "stumpy", "recommendation": "RECOMMENDED", "final_score": 0.9},
    ]

    allowed = SignalPipeline(config=_threshold_config(1), store=NullStore())._allowed_pipeline_analyzers(routing)

    assert allowed == {"ruptures"}


def _flat_series(points: int = 60) -> pd.DataFrame:
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    return pd.DataFrame(
        {"timestamp": [start + timedelta(minutes=i) for i in range(points)], "value": [1523.0] * points}
    )


def test_flat_series_is_rejected_unless_the_analyzer_accepts_flat_or_gappy_series(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text(
        yaml.safe_dump(
            {
                "analyzers": {
                    "shape_detector": {
                        "eligibility_rules": {"min_samples": 30},
                        "scoring_rules": {"base": 0.5, "rules": []},
                    },
                    "health_check": {
                        "eligibility_rules": {"min_samples": 30, "accepts_flat_or_gappy_series": True},
                        "scoring_rules": {
                            "base": 0.3,
                            "rules": [{"metric": "constant_value_percentage", "gte": 95.0, "add": 0.6}],
                        },
                    },
                }
            }
        )
    )
    router = UniversalTimeSeriesRouter(registry_path=registry_path)
    _, profile, _ = router.profile_dataframe(_flat_series(), "timestamp", "value")

    decisions = {d.analyzer: d for d in router.recommend_analyzers_for_profile(profile)}

    assert decisions["shape_detector"].recommendation == "REJECTED"
    assert decisions["health_check"].eligible
    assert decisions["health_check"].recommendation == "RECOMMENDED"


def test_recommendation_service_sees_wizard_registered_analyzers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom_dir = tmp_path / "analyzer_registry.d"
    custom_dir.mkdir()
    (custom_dir / "custom_wizard_probe.yml").write_text(
        yaml.safe_dump(
            {
                "analyzers": {
                    "wizard_probe": {
                        "display_name": "Wizard Probe",
                        "class_path": CUSTOM_CLASS_PATH,
                        "router": {
                            "supported_profiles": ["seasonal"],
                            "scoring_rules": {"base": 0.4, "rules": [{"metric": "seasonality_strength", "gte": 0.4, "add": 0.2}]},
                        },
                    }
                }
            }
        )
    )
    monkeypatch.setattr(router_registry_module, "DEFAULT_CUSTOM_REGISTRY_DIR", custom_dir)

    router_ids = {c.analyzer for c in MetricAnalyzerRecommendationService().router.registry.analyzers()}

    assert "wizard_probe" in router_ids
    assert {"ruptures", "stumpy", "prophet", "trend_regression"} <= router_ids


def test_wizard_options_round_trip_into_a_loadable_registration(tmp_path: Path) -> None:
    config = AnalyzerConfigIn(
        analyzer_id="data_health_probe",
        display_name="Data Health Probe",
        template_type="Custom",
        library="pandas",
        supported_profiles=["mixed"],
        accepts_flat_or_gappy_series=True,
        always_run=True,
        scoring_rules=[ScoringRuleIn(metric="constant_value_percentage", operator="gte", threshold=95.0, add=0.5)],
        selected_explanation="selected",
        excluded_explanation="excluded",
    )
    (tmp_path / "custom_data_health_probe.yml").write_text(
        yaml.safe_dump({"analyzers": {config.analyzer_id: _config_to_registration_dict(config)}})
    )

    [registration] = load_registrations(tmp_path)

    assert registration.always_run is True
    assert registration.router.eligibility_rules["accepts_flat_or_gappy_series"] is True
    assert registration.router.scoring_rules["rules"][0]["metric"] == "constant_value_percentage"
