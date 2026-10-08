from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.config import PrometheusConnectionConfig
from backend.app.metric_usage.sources import (
    MetricUsage,
    dashboard_usages,
    datasource_scopes,
    folder_excluded,
    grafana_alert_rule_usages,
    prometheus_rule_usages,
)

FIXTURES = Path(__file__).parent / "fixtures" / "grafana_metric_usage"


def _dashboard(name: str) -> dict:
    return json.loads((FIXTURES / "dashboards" / f"{name}.json").read_text())


def _by_metric(usages: list[MetricUsage]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for usage in usages:
        found.setdefault(usage.metric, set()).add(usage.location)
    return found


def test_dashboard_reads_top_level_panels_and_panels_inside_collapsed_rows() -> None:
    scan = dashboard_usages(_dashboard("production_api_health"))
    assert _by_metric(scan.usages) == {
        "request_latency_p95": {"Production / API Health / Latency p95 by service"},
        "error_rate": {"Production / API Health / Error rate"},
        "prometheus_http_request_duration_seconds_bucket": {"Production / API Health / HTTP API p95 duration"},
        "prometheus_tsdb_head_samples_appended_total": {"Production / API Health / Samples appended per series"},
        "prometheus_tsdb_head_series": {"Production / API Health / Samples appended per series"},
    }
    assert scan.unresolved == []
    usage = scan.usages[0]
    assert (usage.kind, usage.folder, usage.dashboard_uid) == ("dashboard", "Production", "cov-test-api-health")


def test_dashboard_expands_metric_variable_and_skips_non_prometheus_and_text_panels() -> None:
    scan = dashboard_usages(_dashboard("team_lab_signals"))
    assert _by_metric(scan.usages) == {
        "ops_signal_lab_value": {"Team-Lab / Lab Signals / Lab value by profile"},
        "cpu_usage": {"Team-Lab / Lab Signals / Picked metric (dashboard variable)"},
        "request_latency_p95": {"Team-Lab / Lab Signals / Picked metric (dashboard variable)"},
    }


def _single_panel_dashboard(panel: dict, templating: list[dict] | None = None) -> dict:
    return {
        "meta": {"folderTitle": "General"},
        "dashboard": {"uid": "d1", "title": "D", "templating": {"list": templating or []}, "panels": [panel]},
    }


def test_hidden_queries_and_loki_queries_are_not_usage() -> None:
    panel = {
        "title": "P",
        "datasource": {"type": "prometheus", "uid": "prom"},
        "targets": [
            {"refId": "A", "expr": "only_hidden_metric", "hide": True},
            {"refId": "B", "expr": 'sum(rate({app="x"}[5m]))', "datasource": {"type": "loki", "uid": "logs"}},
            {"refId": "C", "expr": "shown_metric"},
        ],
    }
    assert _by_metric(dashboard_usages(_single_panel_dashboard(panel)).usages) == {"shown_metric": {"General / D / P"}}


def test_mixed_and_default_datasources_use_the_target_or_assume_prometheus() -> None:
    panel = {
        "title": "Mixed",
        "datasource": {"type": "datasource", "uid": "-- Mixed --"},
        "targets": [
            {"refId": "A", "expr": "from_target_ds", "datasource": {"type": "prometheus", "uid": "prom"}},
            {"refId": "B", "expr": "from_default_ds"},
        ],
    }
    assert set(_by_metric(dashboard_usages(_single_panel_dashboard(panel)).usages)) == {"from_target_ds", "from_default_ds"}

    loki_by_uid = dashboard_usages(_single_panel_dashboard({"title": "L", "datasource": {"uid": "logs"}, "targets": [{"expr": "x"}]}), datasource_types={"logs": "loki"})
    assert loki_by_uid.usages == []


def test_query_variable_without_saved_options_is_reported_unresolved() -> None:
    panel = {"title": "P", "datasource": {"type": "prometheus"}, "targets": [{"expr": "rate($picked[5m])"}]}
    templating = [{"name": "picked", "type": "query", "query": "label_values(__name__)", "options": []}]
    scan = dashboard_usages(_single_panel_dashboard(panel, templating))
    assert scan.usages == []
    assert [(item.location, item.variables) for item in scan.unresolved] == [("General / D / P", frozenset({"picked"}))]


def test_all_option_expands_to_every_option() -> None:
    panel = {"title": "P", "datasource": {"type": "prometheus"}, "targets": [{"expr": "$m"}]}
    templating = [
        {
            "name": "m",
            "type": "query",
            "includeAll": True,
            "current": {"text": "All", "value": "$__all"},
            "options": [{"value": "$__all"}, {"value": "a_metric"}, {"value": "b_metric"}],
        }
    ]
    assert set(_by_metric(dashboard_usages(_single_panel_dashboard(panel, templating)).usages)) == {"a_metric", "b_metric"}


def test_library_panel_queries_come_from_the_library_model() -> None:
    panel = {"title": "Shared", "libraryPanel": {"uid": "lib1", "name": "Shared"}}
    library = {"lib1": {"title": "Shared", "datasource": {"type": "prometheus"}, "targets": [{"expr": "library_metric"}]}}
    assert set(_by_metric(dashboard_usages(_single_panel_dashboard(panel), library_panels=library).usages)) == {"library_metric"}


def test_grafana_alert_rules_read_prometheus_queries_and_skip_expressions() -> None:
    rules = json.loads((FIXTURES / "alert_rules.json").read_text())
    scan = grafana_alert_rule_usages(rules, folder_titles={"cov-test-production": "Production"})
    assert _by_metric(scan.usages) == {
        "error_rate": {"Production / Checkout error rate high"},
        "up": {"Production / Mock metrics target down"},
    }
    assert {usage.kind for usage in scan.usages} == {"alert_rule"}


def test_prometheus_rules_split_alerts_from_recording_rules() -> None:
    payload = {
        "status": "success",
        "data": {
            "groups": [
                {
                    "name": "api",
                    "file": "/etc/prometheus/rules/api.yml",
                    "rules": [
                        {"type": "recording", "name": "job:http_requests:rate5m", "query": "sum by (job) (rate(http_requests_total[5m]))"},
                        {"type": "alerting", "name": "HighErrorRate", "query": "job:http_requests:rate5m > 100"},
                    ],
                }
            ]
        },
    }
    scan = prometheus_rule_usages(payload)
    assert _by_metric(scan.usages) == {
        "http_requests_total": {"api / job:http_requests:rate5m"},
        "job:http_requests:rate5m": {"api / HighErrorRate"},
    }
    assert {usage.metric: usage.kind for usage in scan.usages} == {"http_requests_total": "recording_rule", "job:http_requests:rate5m": "alert_rule"}
    assert scan.recording_rules == {"job:http_requests:rate5m": frozenset({"http_requests_total"})}


@pytest.mark.parametrize(
    ("folder", "patterns", "excluded"),
    [
        ("Scratch", ["Scratch"], True),
        ("scratch", ["Scratch"], True),
        ("Test (old)", ["Test*"], True),
        ("Production", ["Test*", "Scratch"], False),
        (None, ["General"], False),
    ],
)
def test_folder_exclusion_matches_names_and_wildcards(folder: str | None, patterns: list[str], excluded: bool) -> None:
    assert folder_excluded(folder, patterns) is excluded


MIMIR_A = PrometheusConnectionConfig(id="team-a", name="Mimir team-a", base_url="http://localhost:9009/prometheus")
MIMIR_B = PrometheusConnectionConfig(id="team-b", name="Mimir team-b", base_url="http://localhost:9009/prometheus", grafana_datasources=["Mimir B"])
GRAFANA_DATASOURCES = [
    # Same URL as both tenants: Grafana keeps the X-Scope-OrgID value secret, so either could be meant.
    {"uid": "mimir-a", "name": "Mimir A", "type": "prometheus", "url": "http://127.0.0.1:9009/prometheus/"},
    # Named in team-b's grafana_datasources; the URL Grafana uses inside Docker matches nothing.
    {"uid": "mimir-b", "name": "Mimir B", "type": "prometheus", "url": "http://mimir:9009/prometheus"},
    {"uid": "old", "name": "Old Prometheus", "type": "prometheus", "url": "http://old-prom:9090", "isDefault": True},
    {"uid": "logs", "name": "Loki", "type": "loki", "url": "http://loki:3100"},
]


def test_grafana_datasources_map_to_connections_by_name_or_url() -> None:
    index = datasource_scopes(GRAFANA_DATASOURCES, [MIMIR_A, MIMIR_B])
    assert index.scopes["mimir-a"] == index.scopes["Mimir A"] == {"team-a", "team-b"}
    assert index.scopes["mimir-b"] == {"team-b"}
    # Several connections and no match: Ops Signals can't see what it reads.
    assert index.scopes["old"] == frozenset()
    assert index.scopes[""] == frozenset()  # the default datasource, for panels that name none
    assert index.names["old"] == "Old Prometheus"
    assert index.types["logs"] == "loki"
    assert "logs" not in index.scopes


def test_with_one_connection_any_prometheus_datasource_is_assumed_to_be_it() -> None:
    # Grafana in Docker reaches Prometheus as prometheus:9090, Ops Signals as localhost:9090.
    single = PrometheusConnectionConfig(base_url="http://localhost:9090")
    index = datasource_scopes([{"uid": "prom", "name": "Prometheus", "type": "prometheus", "url": "http://prometheus:9090", "isDefault": True}], [single])
    assert index.scopes["prom"] is None
    assert index.scopes[""] is None


def test_dashboard_queries_carry_the_connections_their_datasource_reads() -> None:
    index = datasource_scopes(GRAFANA_DATASOURCES, [MIMIR_A, MIMIR_B])
    payload = {
        "meta": {"folderTitle": "Team B"},
        "dashboard": {"uid": "d1", "title": "Billing", "panels": [
            {"title": "Named", "datasource": {"type": "prometheus", "uid": "mimir-b"}, "targets": [{"expr": "billing_errors"}]},
            {"title": "Default", "targets": [{"expr": "default_metric"}]},
            {"title": "Variable", "datasource": {"type": "prometheus", "uid": "${ds}"}, "targets": [{"expr": "variable_metric"}]},
            {"title": "Mixed", "datasource": {"uid": "-- Mixed --"}, "targets": [{"expr": "shared_metric", "datasource": {"uid": "mimir-a"}}]},
        ]},
    }
    scan = dashboard_usages(payload, datasource_types=index.types, datasource_scopes=index.scopes)
    connections = {usage.metric: usage.connections for usage in scan.usages}
    assert connections == {"billing_errors": {"team-b"}, "variable_metric": None, "shared_metric": {"team-a", "team-b"}}
    # The default datasource is one Ops Signals doesn't query: left out, and said so.
    assert scan.skipped_datasources == {""}


def test_grafana_alert_rules_carry_their_datasource_connections() -> None:
    index = datasource_scopes(GRAFANA_DATASOURCES, [MIMIR_A, MIMIR_B])
    rules = [
        {"uid": "r1", "title": "Billing errors", "folderUID": "f", "data": [{"datasourceUid": "mimir-b", "model": {"expr": "billing_errors"}}]},
        {"uid": "r2", "title": "Old", "folderUID": "f", "data": [{"datasourceUid": "old", "model": {"expr": "legacy_metric"}}]},
    ]
    scan = grafana_alert_rule_usages(rules, folder_titles={"f": "Team B"}, datasource_types=index.types, datasource_scopes=index.scopes)
    assert [(usage.metric, usage.connections) for usage in scan.usages] == [("billing_errors", {"team-b"})]
    assert scan.skipped_datasources == {"old"}


def test_prometheus_rules_belong_to_the_connection_they_came_from() -> None:
    payload = {"data": {"groups": [{"name": "api", "rules": [{"type": "alerting", "name": "High", "query": "rate(errors_total[5m]) > 1"}]}]}}
    scan = prometheus_rule_usages(payload, connection_id="team-b")
    assert [(usage.metric, usage.connections) for usage in scan.usages] == [("errors_total", {"team-b"})]
