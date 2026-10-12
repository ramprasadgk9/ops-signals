"""Behavior rule inputs match a metric under other names (OTel names sent over OTLP), so a rule
written for memory_usage also fires on container.memory.usage. Rules without aliases behave as
before."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from backend.app.behavior_intelligence.fact_extractor import input_facts
from backend.app.behavior_intelligence.finding_builder import build_evaluation
from backend.app.behavior_intelligence.loader import load_definitions
from backend.app.behavior_intelligence.models import BehaviorInput
from backend.app.behavior_intelligence.validator import BehaviorDefinitionValidator

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


def test_an_input_without_aliases_matches_only_its_metric_name() -> None:
    item = BehaviorInput(alias="memory", metric_name="memory_usage", analyzers=["trend"])

    assert item.metric_names == ["memory_usage"]
    assert input_facts(item.metric_names, item.analyzers, [_signal("container.memory.usage", "trend", "trend")]) is None
    assert input_facts(item.metric_names, item.analyzers, [_signal("memory_usage", "trend", "trend")]) is not None


def test_an_alias_matches_when_the_metric_arrives_under_another_name() -> None:
    item = BehaviorInput(alias="memory", metric_name="memory_usage", analyzers=["baseline_shift"], aliases=["container.memory.usage"])
    facts = input_facts(item.metric_names, item.analyzers, [_signal("container.memory.usage", "baseline_shift", "baseline_shift", percent_change=30.0)])

    assert facts is not None
    assert facts["baseline_shift"]["signed_change_percent"] == 30.0


def test_the_canonical_name_wins_when_both_are_present() -> None:
    item = BehaviorInput(alias="memory", metric_name="memory_usage", aliases=["container.memory.usage"])
    facts = input_facts(
        item.metric_names,
        item.analyzers,
        [
            _signal("container.memory.usage", "baseline_shift", "baseline_shift", percent_change=-10.0),
            _signal("memory_usage", "baseline_shift", "baseline_shift", percent_change=50.0),
        ],
    )

    assert facts["baseline_shift"]["signed_change_percent"] == 50.0


def test_the_input_analyzers_still_filter_aliased_signals() -> None:
    item = BehaviorInput(alias="memory", metric_name="memory_usage", analyzers=["trend"], aliases=["container.memory.usage"])
    assert input_facts(item.metric_names, item.analyzers, [_signal("container.memory.usage", "pyod_outlier", "anomaly")]) is None


def test_shipped_rules_load_with_otel_aliases_for_memory_and_cpu() -> None:
    memory = next(item for item in DEFINITIONS["memory_pressure_with_errors"].inputs if item.alias == "memory")
    assert "container.memory.usage" in memory.aliases
    for definition in DEFINITIONS.values():
        for item in definition.inputs:
            if item.metric_name == "cpu_usage":
                assert "container.cpu.usage" in item.aliases, definition.id
    for definition in DEFINITIONS.values():
        assert BehaviorDefinitionValidator.validate(definition) == [], definition.id


def test_shipped_aliases_cover_the_collector_docker_receiver_but_not_its_running_counters() -> None:
    # Names a real OTel Collector (docker_stats receiver) sent on 2026-10-11.
    memory = next(item for item in DEFINITIONS["memory_pressure_with_errors"].inputs if item.alias == "memory")
    cpu = next(item for item in DEFINITIONS["server_slow"].inputs if item.alias == "cpu")
    assert "container.memory.usage.total" in memory.aliases
    assert "container.cpu.utilization" in cpu.aliases
    # A cumulative counter only rises, so it would always look like an upward trend.
    assert "container.cpu.usage.total" not in cpu.aliases


def test_a_rule_fires_on_otel_names() -> None:
    definition = DEFINITIONS["server_slow"]
    signals = [
        _signal("container.cpu.usage", "pyod_outlier", "anomaly"),
        _signal("container.memory.usage", "baseline_shift", "baseline_shift", percent_change=40.0),
    ]
    facts = {item.alias: input_facts(item.metric_names, item.analyzers, signals) for item in definition.inputs}

    assert all(value is not None for value in facts.values())
    assert build_evaluation(definition, facts, facts, "svc", "run").matched


def test_blank_aliases_are_rejected() -> None:
    definition = replace(DEFINITIONS["server_slow"], inputs=[BehaviorInput(alias="cpu", metric_name="cpu_usage", aliases=[" "])])
    assert any("aliases" in error for error in BehaviorDefinitionValidator.validate(definition))
