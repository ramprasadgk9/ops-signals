from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.behavior_intelligence.fact_extractor import extract_facts
from backend.app.behavior_intelligence.finding_builder import build_evaluation
from backend.app.behavior_intelligence.loader import load_definitions

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFINITIONS = {definition.id: definition for definition in load_definitions(PROJECT_ROOT / "config" / "behavior_definitions.d")}


def _signal(metric: str, analyzer: str, signal_type: str, **evidence) -> dict:
    return {
        "metric_name": metric,
        "analyzer_id": analyzer,
        "signal_type": signal_type,
        "start_time": "2026-01-01T00:00:00+00:00",
        "end_time": "2026-01-01T02:00:00+00:00",
        "importance_score": 0.8,
        "evidence": evidence,
    }


def test_baseline_shift_change_percent_reads_the_evidence_key_the_analyzer_writes() -> None:
    # BaselineShiftAnalyzer reports evidence["percent_change"]; the fact used to read
    # "change_percent" and so was always 0.
    facts = extract_facts([_signal("memory_usage", "baseline_shift", "baseline_shift", percent_change=-40.0)])

    assert facts["memory_usage"]["baseline_shift"]["change_percent"] == 40.0
    assert facts["memory_usage"]["baseline_shift"]["signed_change_percent"] == -40.0


def test_signed_change_percent_keeps_the_direction_of_the_largest_change() -> None:
    facts = extract_facts(
        [
            _signal("memory_usage", "ruptures", "ruptures", percent_change=30.0),
            _signal("memory_usage", "ruptures", "ruptures", percent_change=-55.0),
        ]
    )

    assert facts["memory_usage"]["ruptures"]["change_percent"] == 55.0
    assert facts["memory_usage"]["ruptures"]["signed_change_percent"] == -55.0


def test_no_level_change_signal_means_a_zero_change() -> None:
    facts = extract_facts([_signal("memory_usage", "trend", "trend", slope=0.1, slope_percent=12.0)])

    assert facts["memory_usage"]["baseline_shift"]["signed_change_percent"] == 0.0
    assert facts["memory_usage"]["ruptures"]["signed_change_percent"] == 0.0


def _server_slow_matches(memory_signal: dict) -> bool:
    definition = DEFINITIONS["server_slow"]
    cpu = extract_facts([_signal("cpu_usage", "pyod_outlier", "anomaly")])["cpu_usage"]
    memory = extract_facts([memory_signal])["memory_usage"]
    facts = {"cpu": cpu, "memory": memory}
    return build_evaluation(definition, facts, facts, "svc", "run").matched


@pytest.mark.parametrize("analyzer", ["baseline_shift", "ruptures"])
def test_memory_moving_up_to_a_new_level_triggers_server_slow(analyzer: str) -> None:
    assert _server_slow_matches(_signal("memory_usage", analyzer, analyzer, percent_change=80.0))


@pytest.mark.parametrize("analyzer", ["baseline_shift", "ruptures"])
def test_memory_dropping_to_a_new_level_does_not_trigger_server_slow(analyzer: str) -> None:
    # Memory freed is not degradation - level changes only count upward.
    assert not _server_slow_matches(_signal("memory_usage", analyzer, analyzer, percent_change=-80.0))


def test_small_memory_rise_seen_only_by_ruptures_does_not_trigger_server_slow() -> None:
    # ruptures has no size gate of its own; the rule's 25 matches baseline_shift's minimum.
    assert not _server_slow_matches(_signal("memory_usage", "ruptures", "ruptures", percent_change=10.0))
