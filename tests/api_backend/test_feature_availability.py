"""Which features the connected sources turn on (GET /api/ingestion/status `features`).

The UI groups, explains and gates features from this one list, so a wrong answer either hides
something that works or offers something that can't run. These pin the answer per setup."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.api import ingestion_status
from backend.app.capabilities.availability import FEATURES, evaluate
from backend.app.integrations.grafana.client import GrafanaError
from backend.app.main import create_app
from backend.app.otlp import metrics as otlp_metrics

STATUS = "/api/ingestion/status"
NEEDS_PROMETHEUS = {"autonomous_analysis", "pod_drilldown", "alert_enrichment", "metric_usage"}


def _states(connected: set[str]) -> dict[str, str]:
    return {feature.id: feature.state for feature in evaluate(connected)}


def _by_id(connected: set[str]):
    return {feature.id: feature for feature in evaluate(connected)}


def test_every_feature_is_listed_once_with_a_label() -> None:
    ids = [feature.id for feature in FEATURES]
    assert len(ids) == len(set(ids))
    assert all(feature.label for feature in FEATURES)
    assert [feature.id for feature in evaluate(set())] == ids


def test_otlp_only_keeps_the_core_on_and_the_prometheus_features_off() -> None:
    states = _states({"otlp"})

    for feature_id in ("findings", "cases", "memory", "notifications", "assistant", "behavior_rules"):
        assert states[feature_id] == "on", feature_id
    for feature_id in NEEDS_PROMETHEUS:
        assert states[feature_id] == "off", feature_id


def test_off_features_name_the_sources_they_are_missing() -> None:
    features = _by_id({"otlp"})

    assert features["autonomous_analysis"].missing == ["prometheus"]
    assert features["alert_enrichment"].missing == ["alertmanager", "prometheus"]
    assert features["metric_usage"].missing == ["prometheus"]
    assert features["findings"].missing == []


def test_prometheus_turns_on_its_features_but_alert_enrichment_also_needs_alertmanager() -> None:
    states = _states({"prometheus"})

    assert states["autonomous_analysis"] == "on"
    assert states["pod_drilldown"] == "on"
    assert states["alert_enrichment"] == "off"
    assert _by_id({"prometheus"})["alert_enrichment"].missing == ["alertmanager"]
    assert _states({"prometheus", "alertmanager"})["alert_enrichment"] == "on"


def test_metric_usage_runs_on_prometheus_rules_alone_and_grafana_completes_it() -> None:
    # The check reads Prometheus alert and recording rules without Grafana; dashboards need Grafana.
    without_grafana = _by_id({"prometheus"})["metric_usage"]
    assert without_grafana.state == "partly"
    assert without_grafana.missing == ["grafana"]
    assert without_grafana.detail

    assert _states({"prometheus", "grafana"})["metric_usage"] == "on"
    # Grafana alone has nothing to compare dashboards against.
    assert _states({"grafana"})["metric_usage"] == "off"


def test_deploy_correlation_waits_for_the_first_deploy_event() -> None:
    assert _states(set())["deploy_correlation"] == "off"
    assert _by_id(set())["deploy_correlation"].missing == ["events"]
    assert _states({"events"})["deploy_correlation"] == "on"


def test_latency_percentiles_are_partly_available_when_otlp_is_the_only_metrics_source() -> None:
    otlp_only = _by_id({"otlp"})["latency_percentiles"]
    assert otlp_only.state == "partly"
    assert "histogram" in (otlp_only.detail or "").lower()

    assert _states({"otlp", "prometheus"})["latency_percentiles"] == "on"
    # CSV uploads can carry percentiles, so nothing connected is not a reason to call it partial.
    assert _states(set())["latency_percentiles"] == "on"


def test_everything_connected_turns_everything_on() -> None:
    states = _states({"otlp", "prometheus", "alertmanager", "grafana", "events"})
    assert set(states.values()) == {"on"}


# --- the endpoint ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(otlp_metrics, "_last_received_at", None)
    monkeypatch.setattr(ingestion_status, "_grafana_check", None)
    for name in (
        "OPS_SIGNALS_PROMETHEUS_URL",
        "OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED",
        "OPS_SIGNALS_API_TOKEN",
        "OPS_SIGNALS_GRAFANA_URL",
        "OPS_SIGNALS_GRAFANA_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


def test_status_lists_grafana_and_the_features(monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
        body = client.get(STATUS).json()

    assert body["sources"]["grafana"] == {"configured": False, "url": None, "reachable": None}
    features = {feature["id"]: feature for feature in body["features"]}
    assert features["findings"]["state"] == "on"
    assert features["autonomous_analysis"] == {
        "id": "autonomous_analysis",
        "label": "Autonomous analysis",
        "state": "off",
        "missing": ["prometheus"],
        "detail": None,
        "needs": ["prometheus"],
        "better_with": [],
    }


def test_configured_grafana_and_prometheus_turn_metric_usage_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_SIGNALS_PROMETHEUS_URL", "http://prometheus:9090")
    monkeypatch.setenv("OPS_SIGNALS_GRAFANA_URL", "http://admin:secret@grafana:3000/")
    monkeypatch.setattr(ingestion_status, "_prometheus_reachable", lambda config: True)
    monkeypatch.setattr(ingestion_status.GrafanaClient, "check", lambda self: "11.2.0")
    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
        body = client.get(STATUS).json()

    assert body["sources"]["grafana"] == {"configured": True, "url": "http://grafana:3000", "reachable": True}
    features = {feature["id"]: feature["state"] for feature in body["features"]}
    assert features["metric_usage"] == "on"
    assert features["autonomous_analysis"] == "on"


def test_unreachable_grafana_is_reported_not_raised_and_still_counts_as_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    # Unreachable is a problem to fix on the Integrations tile, not a reason to call the feature
    # unavailable: the menu shouldn't reshuffle every time Grafana blips.
    monkeypatch.setenv("OPS_SIGNALS_PROMETHEUS_URL", "http://prometheus:9090")
    monkeypatch.setenv("OPS_SIGNALS_GRAFANA_URL", "http://grafana:3000")
    monkeypatch.setattr(ingestion_status, "_prometheus_reachable", lambda config: True)

    def refuse(self) -> str:
        raise GrafanaError("connection refused")

    monkeypatch.setattr(ingestion_status.GrafanaClient, "check", refuse)
    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
        response = client.get(STATUS)

    assert response.status_code == 200
    body = response.json()
    assert body["sources"]["grafana"]["reachable"] is False
    assert {feature["id"]: feature["state"] for feature in body["features"]}["metric_usage"] == "on"


def test_grafana_check_is_cached_between_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_SIGNALS_GRAFANA_URL", "http://grafana:3000")
    calls: list[int] = []

    def check(self) -> str:
        calls.append(1)
        return "11.2.0"

    monkeypatch.setattr(ingestion_status.GrafanaClient, "check", check)
    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
        client.get(STATUS)
        client.get(STATUS)

    assert len(calls) == 1
