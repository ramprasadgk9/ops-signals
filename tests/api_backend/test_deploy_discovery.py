"""Deploys found in Prometheus (backend/app/deploy_discovery/)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.alerts.correlation import correlate_changes
from backend.app.config import DeployDiscoveryConfig, PrometheusConnectionConfig, PrometheusConnections
from backend.app.deploy_discovery import service as discovery
from backend.app.deploy_discovery.detect import (
    BUILD_INFO_SOURCE,
    REPLICASET_SOURCE,
    build_info_deploys,
    build_info_query,
    replicaset_deploys,
    replicaset_query,
)
from backend.app.models.db import get_session_local
from backend.app.models.entities import ChangeEventEntity

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
START = NOW - timedelta(hours=6)
STEP = 60
SERVICE_LABELS = ["service", "job"]
VERSION_LABELS = ["version", "app_version"]
CONNECTION = PrometheusConnectionConfig(id="main", base_url="http://prometheus.test")


def _series(labels: dict[str, str], minutes: list[int] | range) -> dict:
    """A build_info series reported at these minutes after START."""
    return {"metric": labels, "values": [[(START + timedelta(minutes=m)).timestamp(), "1"] for m in minutes]}


def _detect(result: list[dict], cluster_label: str | None = None):
    return build_info_deploys(result, service_labels=SERVICE_LABELS, version_labels=VERSION_LABELS, cluster_label=cluster_label)


def _replicaset(owner: str, replicaset: str, created: datetime, namespace: str = "shop", **extra: str) -> dict:
    return {"metric": {"owner_name": owner, "replicaset": replicaset, "namespace": namespace, **extra}, "value": [NOW.timestamp(), str(created.timestamp())]}


# --- detect.py -------------------------------------------------------------------------------


def test_versions_already_there_when_the_window_starts_are_not_deploys() -> None:
    assert _detect([_series({"job": "checkout", "version": "1.4.1"}, range(0, 360))]) == []


def test_a_new_version_is_a_deploy_at_the_step_it_first_shows_up() -> None:
    [deploy] = _detect([
        _series({"job": "checkout", "version": "1.4.1"}, range(0, 125)),
        _series({"job": "checkout", "version": "1.4.2"}, range(120, 360)),
    ])
    assert deploy.service == "checkout"
    assert deploy.version == "1.4.2"
    assert deploy.timestamp == START + timedelta(minutes=120)
    assert deploy.source == BUILD_INFO_SOURCE
    assert deploy.attributes == {"previous_versions": ["1.4.1"]}
    assert "from 1.4.1 to 1.4.2" in deploy.description


def test_a_restart_or_scrape_gap_on_the_same_version_is_not_a_deploy() -> None:
    assert _detect([_series({"job": "checkout", "version": "1.4.1"}, [*range(0, 100), *range(130, 360)])]) == []


def test_a_single_pod_switching_version_across_a_gap_is_a_deploy() -> None:
    [deploy] = _detect([
        _series({"job": "worker", "version": "2.0"}, range(0, 100)),
        _series({"job": "worker", "version": "2.1"}, range(104, 360)),
    ])
    assert (deploy.version, deploy.timestamp) == ("2.1", START + timedelta(minutes=104))


def test_going_back_to_an_earlier_version_is_a_deploy_too() -> None:
    deploys = _detect([
        _series({"job": "checkout", "version": "1.4.1"}, [*range(0, 60), *range(200, 360)]),
        _series({"job": "checkout", "version": "1.4.2"}, range(58, 202)),
    ])
    assert [(d.version, d.timestamp) for d in deploys] == [
        ("1.4.2", START + timedelta(minutes=58)),
        ("1.4.1", START + timedelta(minutes=200)),
    ]


def test_services_and_clusters_are_tracked_separately_and_series_without_a_version_are_ignored() -> None:
    deploys = _detect([
        _series({"service": "checkout", "job": "kubernetes-pods", "version": "1", "cluster": "eu"}, range(0, 360)),
        _series({"service": "checkout", "job": "kubernetes-pods", "version": "2", "cluster": "us"}, range(0, 50)),
        _series({"service": "checkout", "job": "kubernetes-pods", "version": "3", "cluster": "us"}, range(50, 360)),
        _series({"job": "node", "goversion": "go1.23"}, range(0, 360)),
    ], cluster_label="cluster")
    assert [(d.service, d.cluster, d.version) for d in deploys] == [("checkout", "us", "3")]


def test_queries_group_by_the_configured_labels() -> None:
    assert build_info_query(["service", "job"], ["version"], "cluster") == 'max by (service, job, version, cluster) ({__name__=~".+_build_info"})'
    assert "group_left (owner_name)" in replicaset_query(None)
    assert 'owner_kind="Deployment"' in replicaset_query("cluster") and "replicaset, cluster" in replicaset_query("cluster")


def test_new_replicasets_in_the_window_are_deploys() -> None:
    deploys = replicaset_deploys([
        _replicaset("checkout", "checkout-7d9f8c", NOW - timedelta(minutes=30)),
        _replicaset("checkout", "checkout-55c6b9", NOW - timedelta(days=9)),
        {"metric": {"replicaset": "orphan-1"}, "value": [NOW.timestamp(), str(NOW.timestamp())]},
    ], cluster_label=None, since=START, until=NOW)
    [deploy] = deploys
    assert (deploy.service, deploy.version, deploy.source) == ("checkout", "checkout-7d9f8c", REPLICASET_SOURCE)
    assert deploy.timestamp == NOW - timedelta(minutes=30)
    assert "namespace shop" in deploy.description


# --- service.py ------------------------------------------------------------------------------


class FakePrometheus:
    def __init__(self, build_info: list[dict] | Exception = (), replicasets: list[dict] | Exception = ()) -> None:
        self.build_info = build_info
        self.replicasets = replicasets
        self.queries: list[tuple[str, dict]] = []

    def __call__(self, connection, promql: str, **kwargs) -> list[dict]:
        self.queries.append((promql, kwargs))
        answer = self.build_info if "build_info" in promql else self.replicasets
        if isinstance(answer, Exception):
            raise answer
        return list(answer)


def _run(db, prometheus: FakePrometheus, config: DeployDiscoveryConfig | None = None) -> discovery.DiscoveryStatus:
    with patch.object(discovery, "get_prometheus_connections", return_value=PrometheusConnections(connections=[CONNECTION], default_id="main")):
        return discovery.run_once(db, config or DeployDiscoveryConfig(), now=NOW, query=prometheus)


def _events(db) -> list[ChangeEventEntity]:
    return db.execute(select(ChangeEventEntity).order_by(ChangeEventEntity.timestamp)).scalars().all()


ROLLOUT = [
    _series({"job": "checkout", "version": "1.4.1"}, range(0, 125)),
    _series({"job": "checkout", "version": "1.4.2"}, range(120, 360)),
]


def test_found_deploys_are_stored_once_however_often_it_runs(db_session) -> None:
    prometheus = FakePrometheus(build_info=ROLLOUT)
    status = _run(db_session, prometheus)
    _run(db_session, prometheus)

    [event] = _events(db_session)
    assert (event.service, event.event_type, event.version, event.source) == ("checkout", "deploy", "1.4.2", BUILD_INFO_SOURCE)
    assert status.connections[0].found == 1 and status.connections[0].stored == 1
    build_info_call = prometheus.queries[0][1]
    assert build_info_call["step_seconds"] == 60 and build_info_call["end"] == NOW


def test_one_rollout_seen_by_both_detectors_is_stored_once_with_the_app_version(db_session) -> None:
    rollout_time = START + timedelta(minutes=118)
    _run(db_session, FakePrometheus(build_info=ROLLOUT, replicasets=[_replicaset("checkout", "checkout-7d9f8c", rollout_time)]))
    assert [e.version for e in _events(db_session)] == ["1.4.2"]


def test_a_deploy_ci_already_sent_is_not_stored_again(db_session) -> None:
    db_session.add(ChangeEventEntity(service="checkout", event_type="deploy", version="v1.4.2", source="github-actions",
                                     timestamp=START + timedelta(minutes=117), received_at=NOW))
    db_session.commit()
    _run(db_session, FakePrometheus(build_info=ROLLOUT))
    assert [e.source for e in _events(db_session)] == ["github-actions"]


def test_two_versions_minutes_apart_are_two_deploys(db_session) -> None:
    _run(db_session, FakePrometheus(build_info=[
        _series({"job": "checkout", "version": "1"}, range(0, 100)),
        _series({"job": "checkout", "version": "2"}, range(100, 104)),
        _series({"job": "checkout", "version": "3"}, range(104, 360)),
    ]))
    assert [e.version for e in _events(db_session)] == ["2", "3"]


def test_a_failing_detector_is_reported_and_the_other_still_runs(db_session) -> None:
    status = _run(db_session, FakePrometheus(
        build_info=HTTPException(status_code=504, detail="Prometheus request timed out"),
        replicasets=[_replicaset("checkout", "checkout-7d9f8c", NOW - timedelta(minutes=5))],
    ))
    assert [e.source for e in _events(db_session)] == [REPLICASET_SOURCE]
    assert status.connections[0].errors == ["build_info: Prometheus request timed out"]


def test_replicasets_can_be_turned_off(db_session) -> None:
    prometheus = FakePrometheus(replicasets=[_replicaset("checkout", "checkout-7d9f8c", NOW - timedelta(minutes=5))])
    _run(db_session, prometheus, DeployDiscoveryConfig(kube_replicasets=False))
    assert _events(db_session) == []
    assert len(prometheus.queries) == 1


def test_connections_without_a_url_are_skipped(db_session) -> None:
    prometheus = FakePrometheus(build_info=ROLLOUT)
    empty = PrometheusConnections(connections=[PrometheusConnectionConfig(id="none")], default_id="none")
    with patch.object(discovery, "get_prometheus_connections", return_value=empty):
        status = discovery.run_once(db_session, DeployDiscoveryConfig(), now=NOW, query=prometheus)
    assert status.connections == [] and prometheus.queries == []


def test_run_if_due_waits_for_the_interval(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    # db_session: the session run_if_due opens is the in-memory test database, never the dev one.
    calls: list[int] = []
    monkeypatch.setattr(discovery, "_last_started", None)
    monkeypatch.setattr(discovery, "run_once", lambda db, config: calls.append(1) or discovery.DiscoveryStatus(ran_at=NOW))
    monkeypatch.setattr(discovery.time, "monotonic", lambda: 1000.0)
    discovery.run_if_due()
    discovery.run_if_due()
    assert len(calls) == 1
    monkeypatch.setattr(discovery.time, "monotonic", lambda: 1000.0 + 5 * 60)
    discovery.run_if_due()
    assert len(calls) == 2
    monkeypatch.setenv("OPS_SIGNALS_DEPLOY_DISCOVERY_ENABLED", "false")
    monkeypatch.setattr(discovery.time, "monotonic", lambda: 99999.0)
    discovery.run_if_due()
    assert len(calls) == 2


def test_found_deploys_reach_findings_and_alerts_with_their_source(db_session) -> None:
    _run(db_session, FakePrometheus(build_info=ROLLOUT))
    changes = correlate_changes(db_session, "checkout", START + timedelta(minutes=125), timedelta(minutes=30), timedelta(minutes=5))
    assert [(m.version, m.source) for m in changes.matches] == [("1.4.2", BUILD_INFO_SOURCE)]


# --- POST /api/events and the Setup check ----------------------------------------------------


def _store_found(service: str = "checkout", minutes_ago: int = 3, cluster: str | None = None) -> None:
    now = datetime.now(timezone.utc)
    with get_session_local()() as db:
        db.add(ChangeEventEntity(service=service, event_type="deploy", version="1.4.2", source=BUILD_INFO_SOURCE, cluster=cluster,
                                 description="Found automatically", timestamp=now - timedelta(minutes=minutes_ago), received_at=now))
        db.commit()


def _listed(client: TestClient) -> list[tuple[str | None, str | None]]:
    return sorted((e["source"], e["version"]) for e in client.get("/api/events").json())


def test_a_deploy_from_ci_replaces_the_one_found_for_the_same_service(client: TestClient) -> None:
    _store_found("checkout")
    _store_found("payments")
    _store_found("checkout", minutes_ago=120)

    assert client.post("/api/events", json={"service": "checkout", "type": "deploy", "version": "v1.4.2", "source": "ci"}).status_code == 201

    assert _listed(client) == [("ci", "v1.4.2"), (BUILD_INFO_SOURCE, "1.4.2"), (BUILD_INFO_SOURCE, "1.4.2")]
    assert {e["service"] for e in client.get("/api/events").json() if e["source"] == BUILD_INFO_SOURCE} == {"payments", "checkout"}


def test_ci_events_that_are_not_deploys_or_for_another_cluster_keep_found_deploys(client: TestClient) -> None:
    _store_found("checkout", cluster="eu")
    client.post("/api/events", json={"service": "checkout", "type": "config", "source": "ci"})
    client.post("/api/events", json={"service": "checkout", "type": "deploy", "cluster": "us", "source": "ci"})
    assert sum(1 for e in client.get("/api/events").json() if e["source"] == BUILD_INFO_SOURCE) == 1


def test_ci_cannot_send_the_source_reserved_for_found_deploys(client: TestClient) -> None:
    response = client.post("/api/events", json={"service": "checkout", "type": "deploy", "source": "ops-signals:build_info"})
    assert response.status_code == 422


def _events_check(client: TestClient) -> dict:
    return next(check for check in client.get("/api/setup/check").json()["checks"] if check["id"] == "events")


def test_setup_check_counts_deploys_found_automatically(client: TestClient) -> None:
    check = _events_check(client)
    assert check["status"] == "off" and "build_info" in check["detail"]

    _store_found("checkout")
    check = _events_check(client)
    assert check["status"] == "ok"
    assert check["detail"].startswith("1 found automatically in the last 7 days in Prometheus")

    client.post("/api/events", json={"service": "payments", "type": "deploy", "source": "ci"})
    assert _events_check(client)["detail"].startswith("Receiving from CI · last just now · 1 found automatically")


def test_setup_check_says_when_the_last_look_failed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    failed = discovery.DiscoveryStatus(ran_at=NOW, connections=[discovery.ConnectionResult("main", errors=["build_info: Prometheus request timed out"])])
    monkeypatch.setattr(discovery, "LAST_RUN", failed)
    check = _events_check(client)
    assert check["status"] == "warn" and check["cause"] == "main: build_info: Prometheus request timed out"

    client.post("/api/events", json={"service": "payments", "type": "deploy", "source": "ci"})
    check = _events_check(client)
    assert check["status"] == "warn" and "failed on the last try" in check["detail"]
