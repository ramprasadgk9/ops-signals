from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.autonomous.repository import AutonomousPolicyRepository
from backend.app.autonomous.scheduler import _run_due_policies_once
from backend.app.main import create_app
from backend.app.models.db import get_session_local

POLICY_BODY = {
    "name": "Production coverage",
    "datasource": "prometheus",
    "backend": "grafana-stack",
    "scope": {"all_services": True, "all_namespaces": True},
    "monitoring_selection": {"categories": ["performance", "capacity"]},
    "execution": {"interval": "1m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
}


def test_create_scheduled_policy_is_enabled_with_a_next_run_at() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        response = client.post("/api/autonomous/policies", json={**POLICY_BODY, "schedule_minutes": 30})
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["schedule_minutes"] == 30
    assert payload["next_run_at"] is not None


def test_create_unscheduled_policy_is_saved_but_not_enabled() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        response = client.post("/api/autonomous/policies", json=POLICY_BODY)
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is False
    assert payload["schedule_minutes"] is None
    assert payload["next_run_at"] is None


def test_list_policies_returns_the_created_policy() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        created = client.post("/api/autonomous/policies", json={**POLICY_BODY, "schedule_minutes": 15}).json()
        listed = client.get("/api/autonomous/policies").json()
    assert [policy["id"] for policy in listed] == [created["id"]]


def test_update_policy_config_changes_the_schedule() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        created = client.post("/api/autonomous/policies", json={**POLICY_BODY, "schedule_minutes": 30}).json()
        updated = client.patch(f"/api/autonomous/policies/{created['id']}", json={**POLICY_BODY, "schedule_minutes": 5}).json()
    assert updated["schedule_minutes"] == 5
    assert updated["enabled"] is True


def test_disabling_a_policy_clears_next_run_at_and_keeps_its_schedule_minutes() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        created = client.post("/api/autonomous/policies", json={**POLICY_BODY, "schedule_minutes": 30}).json()

        disabled = client.patch(f"/api/autonomous/policies/{created['id']}/status", json={"enabled": False}).json()
        assert disabled["enabled"] is False
        assert disabled["next_run_at"] is None
        assert disabled["schedule_minutes"] == 30  # "Remove" pauses, it doesn't discard the config

        re_enabled = client.patch(f"/api/autonomous/policies/{created['id']}/status", json={"enabled": True}).json()
        assert re_enabled["enabled"] is True
        assert re_enabled["next_run_at"] is not None


def test_delete_policy_removes_it_from_the_list() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        created = client.post("/api/autonomous/policies", json=POLICY_BODY).json()
        delete_response = client.delete(f"/api/autonomous/policies/{created['id']}")
        listed = client.get("/api/autonomous/policies").json()
    assert delete_response.status_code == 200
    assert delete_response.json() == {"deleted": True, "id": created["id"]}
    assert listed == []


def test_missing_policy_returns_404_on_update_and_status() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        assert client.patch("/api/autonomous/policies/does-not-exist", json=POLICY_BODY).status_code == 404
        assert client.patch("/api/autonomous/policies/does-not-exist/status", json={"enabled": False}).status_code == 404
        assert client.delete("/api/autonomous/policies/does-not-exist").status_code == 404


def test_scheduler_runs_a_due_policy_and_advances_its_next_run_at() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        created = client.post("/api/autonomous/policies", json={**POLICY_BODY, "schedule_minutes": 10}).json()

    session_local = get_session_local()
    with session_local() as db:
        repo = AutonomousPolicyRepository(db)
        # Force it due right now instead of waiting on the real schedule.
        policy = repo.get(created["id"])
        policy.next_run_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    fake_result = type("FakeResult", (), {"status": "completed"})()
    with (
        patch("backend.app.api.autonomous.preview_autonomous_plan", return_value=object()),
        patch("backend.app.autonomous.scheduler.execute_autonomous_plan_once", return_value=fake_result) as mock_execute,
        patch("backend.app.autonomous.scheduler.PrometheusQueryService"),
    ):
        _run_due_policies_once()

    assert mock_execute.call_args.kwargs["policy_id"] == created["id"]
    assert mock_execute.call_args.kwargs["trigger"] == "scheduled"

    with session_local() as db:
        policy = AutonomousPolicyRepository(db).get(created["id"])
        assert policy.last_run_status == "completed"
        assert policy.consecutive_failures == 0
        # SQLite (used here) doesn't round-trip tzinfo the way Postgres' TIMESTAMPTZ does;
        # the repository always writes timezone-aware values, this just normalizes the read-back.
        next_run_at = policy.next_run_at.replace(tzinfo=timezone.utc) if policy.next_run_at.tzinfo is None else policy.next_run_at
        assert next_run_at > datetime.now(timezone.utc)


def test_scheduler_counts_consecutive_failures_and_does_not_stop_on_one_bad_policy() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        created = client.post("/api/autonomous/policies", json={**POLICY_BODY, "schedule_minutes": 10}).json()

    session_local = get_session_local()
    with session_local() as db:
        policy = AutonomousPolicyRepository(db).get(created["id"])
        policy.next_run_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    with (
        patch("backend.app.api.autonomous.preview_autonomous_plan", side_effect=RuntimeError("synthetic prometheus outage")),
        patch("backend.app.autonomous.scheduler.PrometheusQueryService"),
    ):
        _run_due_policies_once()  # must not raise, even though the only due policy fails

    with session_local() as db:
        policy = AutonomousPolicyRepository(db).get(created["id"])
        assert policy.last_run_status == "failed"
        assert policy.consecutive_failures == 1


def test_disabled_policy_is_never_picked_up_as_due() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        created = client.post("/api/autonomous/policies", json=POLICY_BODY).json()  # unscheduled -> disabled

    session_local = get_session_local()
    with session_local() as db:
        repo = AutonomousPolicyRepository(db)
        due = repo.list_due(now=datetime.now(timezone.utc) + timedelta(days=1))
        assert created["id"] not in [policy.id for policy in due]
