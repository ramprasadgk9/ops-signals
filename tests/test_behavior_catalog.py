from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.behavior_definitions import router as definitions_router
from backend.app.api.behavior_lab import _draft_to_definition, _known_analyzer_ids
from backend.app.behavior_intelligence.catalog import CatalogError, load_catalog
from backend.app.behavior_intelligence.fact_extractor import input_facts
from backend.app.behavior_intelligence.finding_builder import build_evaluation
from backend.app.behavior_intelligence.loader import load_definitions
from backend.app.behavior_intelligence.schemas import BehaviorDefinitionDraftIn
from backend.app.behavior_intelligence.validator import BehaviorDefinitionValidator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG = PROJECT_ROOT / "config" / "behavior_patterns_catalog.yml"
DEFINITIONS = load_definitions(PROJECT_ROOT / "config" / "behavior_definitions.d")
ENTRIES = load_catalog(CATALOG, DEFINITIONS)
TEMPLATES = [entry for entry in ENTRIES if entry["rule"] is None]


def test_every_shipped_rule_has_an_entry() -> None:
    assert {entry["rule"] for entry in ENTRIES if entry["rule"]} == {definition.id for definition in DEFINITIONS}


@pytest.mark.parametrize("entry", [entry for entry in ENTRIES if entry["proof"] == "tested"], ids=lambda entry: entry["key"])
def test_tested_here_is_true(entry: dict) -> None:
    """A rule may say "Tested here" only for benchmark scenarios that require it to match."""
    for scenario in entry["scenarios"]:
        truth = yaml.safe_load((PROJECT_ROOT / "benchmark" / "scenarios" / scenario / "ground_truth.yaml").read_text())
        assert entry["rule"] in truth["expected_behavior_findings"]["required_matched"], scenario


@pytest.mark.parametrize("entry", TEMPLATES, ids=lambda entry: entry["key"])
def test_a_template_draft_is_a_valid_definition(entry: dict) -> None:
    definition = _draft_to_definition(BehaviorDefinitionDraftIn(**entry["draft"]))
    assert BehaviorDefinitionValidator.validate(definition, _known_analyzer_ids()) == []
    assert BehaviorDefinitionValidator.warnings(definition) == []


def _signal(metric: str, shape: str) -> dict:
    base = {"metric_name": metric, "start_time": "2026-01-01T00:00:00+00:00", "end_time": "2026-01-01T02:00:00+00:00", "importance_score": 0.8}
    if shape == "unusual":
        return {**base, "analyzer_id": "pyod_outlier", "signal_type": "anomaly", "evidence": {}}
    return {**base, "analyzer_id": "ruptures", "signal_type": "ruptures", "evidence": {"percent_change": 40.0 if shape == "rising" else -40.0}}


def _matches(entry: dict, signals: list[dict]) -> bool:
    definition = _draft_to_definition(BehaviorDefinitionDraftIn(**entry["draft"]))
    facts = {}
    for item in definition.inputs:
        found = input_facts(item.metric_names, item.analyzers, signals)
        if found is None:
            return False
        facts[item.alias] = found
    return build_evaluation(definition, facts, facts, "svc", "run").matched


@pytest.mark.parametrize("entry", TEMPLATES, ids=lambda entry: entry["key"])
def test_a_template_matches_when_every_signal_shows_its_shape(entry: dict) -> None:
    signals = [_signal(signal["metric_hint"], signal["shape"]) for signal in entry["signals"]]
    assert _matches(entry, signals)
    # Every signal is needed: one missing and the pattern does not match.
    assert not _matches(entry, signals[1:])


def test_rising_is_not_falling() -> None:
    cache = next(entry for entry in TEMPLATES if entry["key"] == "cache_stopped_helping")
    signals = [_signal(signal["metric_hint"], "rising") for signal in cache["signals"]]
    assert not _matches(cache, signals)


def _catalog_file(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "catalog.yml"
    path.write_text(text)
    return path


def test_an_unknown_rule_is_refused(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="no pack defines"):
        load_catalog(_catalog_file(tmp_path, "patterns:\n  - rule: not_a_rule\n"), DEFINITIONS)


def test_a_shape_the_engine_cannot_check_is_refused(tmp_path: Path) -> None:
    text = """patterns:
  - key: deploy
    name: Bad deploy
    meaning: x
    signals:
      - {alias: errors, label: Errors jump, shape: rising, metric_hint: error_rate}
      - {alias: version, label: New version, shape: event, metric_hint: deploys}
"""
    with pytest.raises(CatalogError, match="shape 'event'"):
        load_catalog(_catalog_file(tmp_path, text), DEFINITIONS)


def test_the_endpoint_serves_the_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(PROJECT_ROOT)
    app = FastAPI()
    app.include_router(definitions_router)
    with TestClient(app) as client:
        body = client.get("/api/behavior-definitions/catalog").json()
    server_slow = next(entry for entry in body if entry["key"] == "server_slow")
    assert server_slow["proof"] == "tested"
    assert server_slow["name"] == "Possible server performance degradation"
    consumer = next(entry for entry in body if entry["key"] == "consumer_falling_behind")
    assert consumer["proof"] == "common"
    assert consumer["signals"][0]["keywords"] == ["consumer", "lag", "backlog"]
    assert consumer["draft"]["conditions"]["all"][0] == {"fact": "lag.change.upward", "operator": "equals", "value": True}
