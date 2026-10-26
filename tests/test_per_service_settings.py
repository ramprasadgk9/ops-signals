from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.app.api.ingestion import PreviewPipelineStore
from intelligence.analyzer_selection import RegistryAnalyzerSelection
from intelligence.config import load_config
from intelligence.normalize.normalizer import normalize_timeseries
from intelligence.pipeline import SignalPipeline

PROJECT_ROOT = Path(__file__).resolve().parents[1]

PAYMENTS_TREND = """
overrides:
  payments_memory:
    scope: {service: payments-api}
    reason: Memory grows slowly before an outage here.
    analyzers:
      trend:
        finding_rules: {min_slope_percent: 3}
"""


@pytest.fixture()
def overrides_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "analyzer_overrides.d"
    directory.mkdir()
    monkeypatch.setattr(RegistryAnalyzerSelection, "overrides_dir", directory)
    return directory


def _config():
    # The root config runs every analyzer, so what runs doesn't depend on the router's picks.
    config = load_config(PROJECT_ROOT / "config.yaml")
    config.embeddings.enabled = False
    return config


def _pipeline() -> SignalPipeline:
    return SignalPipeline(_config(), store=PreviewPipelineStore())


def _climbing_memory(*services: str) -> pd.DataFrame:
    """A steady 6% climb over a day for each service: under the default 10% trend threshold."""
    timestamps = pd.date_range("2026-10-01", periods=288, freq="5min", tz="UTC")
    rng = np.random.default_rng(1)
    rows = [
        {"timestamp": timestamp, "metric_name": "memory_usage", "value": value, "service": service}
        for service in services
        for timestamp, value in zip(timestamps, np.linspace(100, 106, 288) + rng.normal(0, 0.3, 288))
    ]
    return pd.DataFrame(rows)


def _trend_services(result) -> list[str]:
    return sorted(signal.service for signal in result.signals if signal.analyzer_id == "trend")


def test_without_overrides_a_run_is_one_group_with_the_default_settings(overrides_dir: Path) -> None:
    pipeline = _pipeline()
    normalized = normalize_timeseries(_climbing_memory("payments-api", "checkout-api"), pipeline.config.input)

    (settings,) = pipeline._settings_by_series(normalized)

    assert settings.selection is pipeline
    assert settings.mask is None
    assert settings.resolution.applied == []


def test_an_override_changes_the_setting_for_its_service_only(overrides_dir: Path) -> None:
    (overrides_dir / "payments-team.yml").write_text(PAYMENTS_TREND)

    result = _pipeline().run_dataframe(_climbing_memory("payments-api", "checkout-api"))

    # Same 6% climb on both: only payments-api, tuned to 3%, reports it.
    assert _trend_services(result) == ["payments-api"]
    trend = next(item for item in result.analyzer_executions if "trend" in (item.get("pipeline_analyzer_ids") or []))
    assert trend["settings_overrides"] == [
        {
            "series": [{"service": "payments-api", "metric": "memory_usage"}],
            "applied": ["payments_memory"],
            "params": {"trend": {"finding_rules": {"min_slope_percent": 3}}},
            "disabled": [],
            "overrides": [{"id": "payments_memory", "file": "payments-team.yml", "reason": "Memory grows slowly before an outage here."}],
            # In words, with the default at the time of the run, for the finding's details.
            "settings": [
                {
                    "analyzer_id": "trend",
                    "analyzer": "Trend Analysis",
                    "path": "finding_rules.min_slope_percent",
                    "label": "Smallest steady climb or drop that counts, as % of the metric's usual level",
                    "value": 3,
                    "default": 10,
                }
            ],
        }
    ]


def test_a_run_no_override_touches_records_nothing_new(overrides_dir: Path) -> None:
    (overrides_dir / "payments-team.yml").write_text(PAYMENTS_TREND)

    result = _pipeline().run_dataframe(_climbing_memory("checkout-api"))

    assert _trend_services(result) == []
    assert all("settings_overrides" not in item for item in result.analyzer_executions)


def test_a_metric_scope_applies_to_that_metric_on_every_service(overrides_dir: Path) -> None:
    (overrides_dir / "platform.yml").write_text(PAYMENTS_TREND.replace("service: payments-api", "metric: memory_usage"))

    result = _pipeline().run_dataframe(_climbing_memory("payments-api", "checkout-api"))

    assert _trend_services(result) == ["checkout-api", "payments-api"]


def test_disabling_an_analyzer_for_one_service_keeps_it_for_the_others(overrides_dir: Path) -> None:
    (overrides_dir / "payments-team.yml").write_text(
        PAYMENTS_TREND.replace("    analyzers:\n      trend:\n        finding_rules: {min_slope_percent: 3}\n", "    selection: {disabled: [trend]}\n")
    )
    pipeline = _pipeline()
    normalized = normalize_timeseries(_climbing_memory("payments-api", "checkout-api"), pipeline.config.input)

    groups = {
        tuple(service for service, _ in settings.series): {analyzer.analyzer_id for analyzer in analyzers}
        for settings, analyzers in pipeline._build_series_analyzers(normalized, [], None)
    }

    assert "trend" not in groups[("payments-api",)]
    assert "trend" in groups[("checkout-api",)]


def test_max_analyzers_and_settings_apply_to_a_copy_of_the_run_config(overrides_dir: Path) -> None:
    (overrides_dir / "payments-team.yml").write_text(PAYMENTS_TREND.replace("    analyzers:", "    selection: {max_analyzers: 1}\n    analyzers:"))
    pipeline = _pipeline()
    normalized = normalize_timeseries(_climbing_memory("payments-api"), pipeline.config.input)

    (settings,) = pipeline._settings_by_series(normalized)

    assert settings.selection.config.analysis.recommendation_execution.max_analyzers == 1
    assert settings.selection.config.analysis.analyzers["trend"].params["finding_rules"] == {"min_slope_percent": 3}
    assert pipeline.config.analysis.recommendation_execution.max_analyzers == 3
    assert "finding_rules" not in pipeline.config.analysis.analyzers["trend"].params


def test_a_broken_overrides_file_never_stops_analysis(overrides_dir: Path) -> None:
    (overrides_dir / "payments-team.yml").write_text(PAYMENTS_TREND.replace("min_slope_percent: 3", "min_slope_percent: 500"))

    result = _pipeline().run_dataframe(_climbing_memory("payments-api"))

    # The file is skipped, so payments-api runs on the default 10% and the 6% climb stays quiet.
    assert _trend_services(result) == []
    assert result.analyzer_executions


def test_the_autonomous_executor_applies_overrides_the_same_way(overrides_dir: Path) -> None:
    from backend.app.autonomous.metric_executor import MetricAnalysisExecutor

    (overrides_dir / "payments-team.yml").write_text(PAYMENTS_TREND)
    executor = MetricAnalysisExecutor(_config(), store=PreviewPipelineStore())
    normalized = normalize_timeseries(_climbing_memory("payments-api"), executor.config.input)

    ((settings, analyzers),) = executor._build_series_analyzers(normalized, [], None)

    assert settings.resolution.applied == ["payments_memory"]
    assert next(analyzer for analyzer in analyzers if analyzer.analyzer_id == "trend").min_slope_percent == 3
