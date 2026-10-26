from __future__ import annotations

from pathlib import Path

from backend.app.services.timeseries_routing_service import build_csv_routing_config
from intelligence.analyzer_selection import RegistryAnalyzerSelection
from intelligence.config import load_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _Selection(RegistryAnalyzerSelection):
    def __init__(self, config) -> None:
        self.config = config


def _built(config) -> dict:
    # No routing: every enabled analyzer whose library is installed.
    return {analyzer.analyzer_id: analyzer for analyzer in _Selection(config)._build_analyzers(None)}


def test_analyzers_are_built_with_the_shipped_settings() -> None:
    """builtin.yml defaults with config/analyzers.yaml on top, as a Prometheus run builds them."""
    analyzers = _built(load_config(PROJECT_ROOT / "config" / "providers" / "prometheus.yaml"))

    assert analyzers["trend"].min_slope_percent == 10
    assert analyzers["trend"].model == "OLS"
    assert analyzers["baseline_shift"].threshold_percent == 25
    assert analyzers["baseline_shift"].change_threshold == 1.5
    assert analyzers["baseline_shift"].min_segment_size == 5
    pyod = analyzers["pyod_outlier"].config
    assert (pyod.contamination, pyod.min_samples) == (0.01, 50)
    assert (pyod.finding_min_range_excess, pyod.finding_min_sustained_points) == (0.56, 8)


def test_a_partial_custom_param_keeps_the_rest_of_its_block() -> None:
    """Analyzer Labs' "run with custom params" can send just the key it changes."""
    config = build_csv_routing_config(provider="prometheus", analyzer_overrides={"pyod_outlier": {"finding_rule": {"min_sustained_points": 12}}})

    params = config.analysis.analyzers["pyod_outlier"].params
    assert params["finding_rule"] == {"min_range_excess": 0.56, "min_sustained_points": 12, "window": "15m", "compare_daily_peaks": False}
    assert params["implementation"]["contamination"] == 0.01
    assert _built(config)["pyod_outlier"].config.finding_min_sustained_points == 12
