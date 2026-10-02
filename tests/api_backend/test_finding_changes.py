"""Deploys linked to findings at read time (backend/app/services/finding_changes.py).

Every case where data is missing must still return the finding, with a status saying why."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.config import AlertEnrichmentConfig, get_alert_enrichment_config, parse_service_aliases
from backend.app.models.db import get_session_local
from backend.app.models.entities import (
    AutonomousMetricJobEntity,
    ChangeEventEntity,
    FindingEntity,
    SignalEntity,
)

CHANGE = datetime(2026, 10, 1, 14, 10, tzinfo=timezone.utc)
DEPLOY = CHANGE - timedelta(minutes=4)


def _breakdown(first_seen: dict[str, datetime] | None = None, *, new_parts: int = 2, gone_parts: int = 0) -> dict:
    breakdown = {
        "status": "ok",
        "label": "pod",
        "mode": "share",
        "window_before": [(CHANGE - timedelta(hours=20)).isoformat(), CHANGE.isoformat()],
        "window_after": [CHANGE.isoformat(), (CHANGE + timedelta(hours=4)).isoformat()],
        "parts_total": 6,
        "parts_changed": 2,
        "new_parts": new_parts,
        "gone_parts": gone_parts,
        "top": [],
    }
    if first_seen is not None:
        breakdown["new_parts_first_seen"] = {name: ts.isoformat() for name, ts in first_seen.items()}
    return breakdown


NEW_PODS = {"cart-8c2-q1": CHANGE - timedelta(minutes=1), "cart-8c2-w7": CHANGE}


def _add_finding(db, finding_id: int, *, service: str | None = "cart", breakdown: dict | None = None,
                 signal_ids: list[str] | None = None, run_id: str = "run-1") -> None:
    db.add(
        FindingEntity(
            id=finding_id,
            analysis_run_id=run_id,
            service=service,
            metric_name="http_errors_total",
            title="http_errors_total moved to a new baseline.",
            summary="up",
            category="behavior_change",
            health_status="critical",
            importance_score=0.85,
            investigation_priority=1,
            signal_ids=signal_ids or [],
            comparison_json={"breakdown": breakdown} if breakdown else {},
            created_at=datetime.now(timezone.utc),
        )
    )


def _add_event(db, *, service: str = "cart", event_type: str = "deploy", at: datetime = DEPLOY,
               version: str | None = "v1.4.2", env: str | None = None) -> None:
    db.add(ChangeEventEntity(service=service, event_type=event_type, timestamp=at, version=version, env=env,
                             received_at=datetime.now(timezone.utc)))


def _add_signal(db, signal_id: str, signal_type: str, *, start: datetime, end: datetime, evidence: dict | None = None) -> None:
    db.add(SignalEntity(signal_id=signal_id, signal_type=signal_type, analyzer_id=signal_type, metric_name="http_errors_total",
                        service="cart", severity="high", start_time=start, end_time=end, evidence_json=evidence or {},
                        importance_score=0.9, analysis_run_id="run-1"))


@pytest.fixture()
def seed(client: TestClient):
    def _seed(build) -> None:
        with get_session_local()() as db:
            build(db)
            db.commit()
    return _seed


def _changes(client: TestClient, finding_id: int) -> dict:
    response = client.get(f"/api/findings/{finding_id}")
    assert response.status_code == 200
    return response.json()["changes"]


def test_new_pods_started_by_the_deploy_are_linked_to_it(client, seed) -> None:
    seed(lambda db: (_add_finding(db, 1, breakdown=_breakdown(NEW_PODS)), _add_event(db)))

    changes = _changes(client, 1)

    assert changes["status"] == "matched"
    [match] = changes["matches"]
    assert match["version"] == "v1.4.2"
    assert match["minutes_before_anchor"] == 4.0
    pods = changes["pods"]
    assert pods["status"] == "linked"
    assert pods["method"] == "pod_start_time"
    assert sorted(pods["parts"]) == ["cart-8c2-q1", "cart-8c2-w7"]
    assert pods["old_parts_running"] == 4


def test_list_and_search_carry_changes_too(client, seed) -> None:
    seed(lambda db: (_add_finding(db, 1, breakdown=_breakdown(NEW_PODS)), _add_event(db)))

    [listed] = client.get("/api/findings").json()
    [searched] = client.get("/api/findings/search", params={"window": "24h"}).json()

    assert listed["changes"]["pods"]["status"] == "linked"
    assert searched["changes"]["status"] == "matched"


def test_pods_that_started_long_after_the_deploy_are_not_linked(client, seed) -> None:
    # The change (and the pods) came 25 min after the deploy: still in the 30 min window, so the
    # deploy is listed, but past the 15 min rollout window, so the pods aren't claimed by it.
    late = {"cart-8c2-q1": DEPLOY + timedelta(minutes=25)}
    seed(lambda db: (_add_finding(db, 1, breakdown={**_breakdown(late), "window_after": [(DEPLOY + timedelta(minutes=25)).isoformat()]}),
                     _add_event(db)))

    pods = _changes(client, 1)["pods"]

    assert pods == {"status": "not_linked", "reason": "started_outside_rollout", "label": "pod", "rollout_minutes": 15}


def test_finding_stored_before_start_times_existed_still_shows_the_deploy(client, seed) -> None:
    seed(lambda db: (_add_finding(db, 1, breakdown=_breakdown(first_seen=None)), _add_event(db)))

    changes = _changes(client, 1)

    assert changes["status"] == "matched"
    assert changes["pods"] == {"status": "not_linked", "reason": "no_start_times", "label": "pod"}


def test_without_a_breakdown_the_change_time_comes_from_the_signals(client, seed) -> None:
    def build(db) -> None:
        _add_signal(db, "s-ruptures", "ruptures", start=CHANGE - timedelta(hours=20), end=CHANGE + timedelta(hours=4),
                    evidence={"change_point_time": CHANGE.isoformat()})
        _add_finding(db, 1, signal_ids=["s-ruptures"])
        _add_event(db)
    seed(build)

    changes = _changes(client, 1)

    assert changes["status"] == "matched"
    assert changes["anchor"].startswith("2026-10-01T14:10")
    assert changes["pods"] == {"status": "not_linked", "reason": "no_breakdown"}


def test_a_signal_whose_rule_did_not_match_does_not_set_the_change_time(client, seed) -> None:
    def build(db) -> None:
        _add_signal(db, "s-pyod", "anomaly", start=DEPLOY - timedelta(hours=3), end=DEPLOY - timedelta(hours=2),
                    evidence={"finding_rule_matched": False})
        _add_finding(db, 1, signal_ids=["s-pyod"])
        _add_event(db)
    seed(build)

    assert _changes(client, 1) == {"status": "unavailable", "reason": "no_change_time", "service": "cart"}


def test_a_config_change_is_shown_but_does_not_claim_the_new_pods(client, seed) -> None:
    seed(lambda db: (_add_finding(db, 1, breakdown=_breakdown(NEW_PODS)), _add_event(db, event_type="config", version=None)))

    changes = _changes(client, 1)

    assert changes["status"] == "matched"
    assert changes["matches"][0]["event_type"] == "config"
    assert changes["pods"] == {"status": "not_linked", "reason": "no_deploy", "label": "pod"}


def test_deploy_far_from_the_change_is_none_in_window(client, seed) -> None:
    seed(lambda db: (_add_finding(db, 1, breakdown=_breakdown(NEW_PODS)), _add_event(db, at=CHANGE - timedelta(hours=5))))

    changes = _changes(client, 1)

    assert changes["status"] == "none_in_window"
    assert changes["matches"] == []
    assert changes["window_before_minutes"] == 30


def test_service_without_any_events_says_so(client, seed) -> None:
    seed(lambda db: (_add_finding(db, 1, breakdown=_breakdown(NEW_PODS)), _add_event(db, service="payments")))

    assert _changes(client, 1) == {"status": "no_events_for_service", "service": "cart"}


def test_finding_without_service_is_unavailable(client, seed) -> None:
    seed(lambda db: (_add_finding(db, 1, service=None, breakdown=_breakdown(NEW_PODS)), _add_event(db)))

    assert _changes(client, 1) == {"status": "unavailable", "reason": "no_service"}


def test_alias_joins_a_ci_name_to_the_metrics_service(client, seed) -> None:
    client.app.dependency_overrides[get_alert_enrichment_config] = lambda: AlertEnrichmentConfig(
        service_aliases=[["cart-service", "cart"]]
    )
    seed(lambda db: (_add_finding(db, 1, service="cart-service", breakdown=_breakdown(NEW_PODS)), _add_event(db, service="cart")))
    try:
        changes = _changes(client, 1)
    finally:
        client.app.dependency_overrides.clear()

    assert changes["status"] == "matched"
    assert changes["pods"]["status"] == "linked"


def test_deploy_to_another_environment_is_not_matched(client, seed) -> None:
    def build(db) -> None:
        now = datetime.now(timezone.utc)
        db.add(AutonomousMetricJobEntity(id="job-1", policy_run_id="prun-1", status="completed", datasource="prometheus",
                                         environment="prod", metric_name="http_errors_total", analysis_window="24h",
                                         analysis_run_id="run-1", created_at=now, updated_at=now))
        _add_finding(db, 1, breakdown=_breakdown(NEW_PODS))
        _add_event(db, env="staging")
    seed(build)

    assert _changes(client, 1)["status"] == "none_in_window"


def test_a_failed_lookup_still_returns_the_finding(client, seed, monkeypatch) -> None:
    def broken(*args, **kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr("backend.app.services.finding_changes.correlate_changes", broken)
    seed(lambda db: (_add_finding(db, 1, breakdown=_breakdown(NEW_PODS)), _add_event(db)))

    response = client.get("/api/findings/1")

    assert response.status_code == 200
    assert response.json()["title"] == "http_errors_total moved to a new baseline."
    assert response.json()["changes"] == {"status": "unavailable", "reason": "error"}


def test_alerts_use_the_same_aliases(client, seed) -> None:
    from backend.app.alerts.correlation import correlate_changes

    seed(lambda db: _add_event(db, service="cart"))
    with get_session_local()() as db:
        plain = correlate_changes(db, "cart-service", CHANGE, before=timedelta(minutes=30), after=timedelta(minutes=5))
        aliased = correlate_changes(db, "cart-service", CHANGE, before=timedelta(minutes=30), after=timedelta(minutes=5),
                                    aliases=[["cart-service", "cart"]])

    assert plain.matches == []
    assert [match.version for match in aliased.matches] == ["v1.4.2"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, []),
        ("cart,cart-service", [["cart", "cart-service"]]),
        (" cart , cart-service ; checkout,checkout-api ;lonely", [["cart", "cart-service"], ["checkout", "checkout-api"]]),
    ],
)
def test_parse_service_aliases(raw, expected) -> None:
    assert parse_service_aliases(raw) == expected


def test_signals_for_several_runs_in_one_request(client, seed) -> None:
    def build(db) -> None:
        for run in ("run-a", "run-b", "run-c"):
            db.add(SignalEntity(signal_id=f"s-{run}", signal_type="ruptures", metric_name="m", service="cart",
                                importance_score=0.9, analysis_run_id=run))
    seed(build)

    both = client.get("/api/signals", params=[("analysis_run_id", "run-a"), ("analysis_run_id", "run-c")]).json()
    one = client.get("/api/signals", params={"analysis_run_id": "run-b"}).json()

    assert sorted(signal["id"] for signal in both) == ["s-run-a", "s-run-c"]
    assert [signal["id"] for signal in one] == ["s-run-b"]
