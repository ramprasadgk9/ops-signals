"""Who did what, when a request came through the Grafana plugin's proxy (backend/app/identity.py).

Grafana's proxy adds X-Grafana-Context (checked against Grafana 13.1: it overwrites any copy the
browser sent). Requests without it - the web UI, scripts, the plugin in "Browser, directly" mode -
record no name, and never keep someone else's."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.app.identity import Actor, actor_from_context
from backend.app.models.db import get_session_local
from backend.app.models.entities import FindingEntity


def _context(login: str = "priya", role: str = "Editor", **extra) -> dict[str, str]:
    body = {"UserID": 7, "Login": login, "Name": "", "Email": f"{login}@example.com", "OrgRole": role, "IsAnonymous": False} | extra
    return {"X-Grafana-Context": json.dumps(body)}


ANONYMOUS = {"X-Grafana-Context": json.dumps({"UserID": 0, "Login": "", "Email": "", "OrgRole": "Viewer", "IsAnonymous": True})}

POLICY_BODY = {
    "name": "Production coverage",
    "datasource": "prometheus",
    "backend": "grafana-stack",
    "scope": {"all_services": True, "all_namespaces": True},
    "monitoring_selection": {"categories": ["performance"]},
    "execution": {"interval": "1m", "analysis_window": "24h", "max_metrics_per_run": 50, "max_parallel_jobs": 4},
    "schedule_minutes": 30,
}


def _seed_finding(finding_id: int = 1) -> None:
    now = datetime.now(timezone.utc)
    with get_session_local()() as db:
        db.add(FindingEntity(id=finding_id, analysis_run_id="run-1", service="cart", metric_name="cpu_usage", title="CPU jumped",
                             summary="s", category="behavior_change", health_status="significant", importance_score=0.7,
                             investigation_priority=2, signal_ids=[], comparison_json={}, created_at=now))
        db.commit()


def test_reads_the_grafana_user_and_role() -> None:
    assert actor_from_context(_context()["X-Grafana-Context"]) == Actor(name="priya", role="Editor")
    assert actor_from_context(ANONYMOUS["X-Grafana-Context"]) == Actor(name=None, role="Viewer")
    # Login first; the email only when there's nothing else.
    assert actor_from_context(json.dumps({"Login": "", "Name": "", "Email": "sam@example.com", "OrgRole": "Admin"})).name == "sam@example.com"


def test_ignores_a_missing_or_broken_header_and_unknown_roles() -> None:
    assert actor_from_context(None) is None
    assert actor_from_context("not json") is None
    assert actor_from_context("[1, 2]") is None
    assert actor_from_context(json.dumps({"Login": "x", "OrgRole": "Owner"})).role is None
    assert len(actor_from_context(json.dumps({"Login": "x" * 500, "OrgRole": "Viewer"})).name) == 128


def test_an_answer_records_who_gave_it_and_an_answer_from_elsewhere_clears_the_name(client: TestClient) -> None:
    _seed_finding()

    trust = client.post("/api/findings/1/feedback", json={"verdict": "expected_change"}, headers=_context()).json()["trust"]
    assert (trust["your_answer"], trust["answered_by"]) == ("expected_change", "priya")
    assert trust["answered_at"] is not None

    listed = {item["id"]: item["trust"] for item in client.get("/api/findings").json()}
    assert listed[1]["answered_by"] == "priya"

    # Changed from the web UI (no Grafana): the answer is no longer priya's, so her name goes.
    trust = client.post("/api/findings/1/feedback", json={"verdict": "real_problem"}).json()["trust"]
    assert (trust["your_answer"], trust["answered_by"]) == ("real_problem", None)


def test_a_case_records_who_opened_it(client: TestClient) -> None:
    _seed_finding()

    created = client.post("/api/cases/findings/1/create", headers=_context("admin", "Admin")).json()
    case = client.get(f"/api/cases/{created['case_id']}").json()
    assert case["created_by"] == "admin"

    # Opening it again returns the same case and keeps its creator.
    again = client.post("/api/cases/findings/1/create", headers=_context("sam")).json()
    assert again["case_id"] == created["case_id"]
    assert client.get(f"/api/cases/{created['case_id']}").json()["created_by"] == "admin"


def test_a_case_opened_without_grafana_or_anonymously_has_no_name(client: TestClient) -> None:
    _seed_finding(1)
    _seed_finding(2)
    first = client.post("/api/cases/findings/1/create").json()
    second = client.post("/api/cases/findings/2/create", headers=ANONYMOUS).json()
    assert client.get(f"/api/cases/{first['case_id']}").json()["created_by"] is None
    assert client.get(f"/api/cases/{second['case_id']}").json()["created_by"] is None


def test_a_schedule_records_its_owner_and_last_editor(client: TestClient) -> None:
    created = client.post("/api/autonomous/policies", json=POLICY_BODY, headers=_context("sam")).json()
    assert (created["created_by"], created["edited_by"]) == ("sam", "sam")
    assert created["edited_at"] is not None

    edited = client.patch(f"/api/autonomous/policies/{created['id']}", json={**POLICY_BODY, "schedule_minutes": 60}, headers=_context("priya")).json()
    assert (edited["created_by"], edited["edited_by"]) == ("sam", "priya")

    paused = client.patch(f"/api/autonomous/policies/{created['id']}/status", json={"enabled": False}, headers=_context("admin", "Admin")).json()
    assert (paused["created_by"], paused["edited_by"]) == ("sam", "admin")


def test_the_setup_check_says_who_the_backend_sees(client: TestClient) -> None:
    through_grafana = client.get("/api/setup/check", headers=_context("admin", "Admin")).json()
    assert through_grafana["you"] == {"name": "admin", "role": "Admin", "via": "grafana"}
    backend = next(check for check in through_grafana["checks"] if check["id"] == "backend")
    assert backend["detail"].startswith("Reached through Grafana") and backend["detail"].endswith("you are admin (Admin)")

    anonymous = client.get("/api/setup/check", headers=ANONYMOUS).json()
    assert anonymous["you"] == {"name": None, "role": "Viewer", "via": "grafana"}

    direct = client.get("/api/setup/check").json()
    assert direct["you"] is None
