"""What each Grafana role may change, for requests through the plugin's Grafana proxy (backend/app/roles.py).

Reading stays open to every role; a change needs an Editor unless it is read-like (asking, previews);
set-up and labs need an Admin. Requests that don't come through Grafana are not limited here."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.app.api.cases import create_case_from_finding
from backend.app.identity import actor_name
from backend.app.models.db import get_session_local
from backend.app.roles import refusal, required_role
from tests.api_backend.test_cases import _create_finding


def _as(role: str, login: str = "sam") -> dict[str, str]:
    return {"X-Grafana-Context": json.dumps({"UserID": 3, "Login": login, "Email": f"{login}@example.com", "OrgRole": role, "IsAnonymous": False})}


ANONYMOUS_VIEWER = {"X-Grafana-Context": json.dumps({"UserID": 0, "Login": "", "OrgRole": "Viewer", "IsAnonymous": True})}


@pytest.mark.parametrize(
    ("method", "path", "needed"),
    [
        ("GET", "/api/findings", None),
        ("GET", "/api/autonomous/policies", None),
        ("POST", "/api/autonomous/preview", None),
        ("POST", "/api/assistant/chat", None),
        ("PATCH", "/api/assistant/feedback/12", None),
        ("POST", "/api/prometheus/test-connection", None),
        ("POST", "/api/cases/4/rca/suggest", None),
        ("POST", "/api/cases/4/writeup/suggest", None),
        ("POST", "/api/cases/4/fix-came-back/why", None),
        ("POST", "/api/findings/4/fix-came-back/why", None),
        ("PATCH", "/api/cases/4/writeup", "Editor"),
        ("POST", "/api/findings/9/feedback", "Editor"),
        ("POST", "/api/cases/findings/9/create", "Editor"),
        ("PATCH", "/api/cases/4/resolution", "Editor"),
        ("POST", "/api/cases/4/ticket/create", "Editor"),
        ("POST", "/api/analysis/prometheus", "Editor"),
        ("POST", "/api/autonomous/run-once", "Editor"),
        ("DELETE", "/api/autonomous/policies/abc", "Editor"),
        ("POST", "/api/some/new/endpoint", "Editor"),
        ("POST", "/api/testing/reset-operational-data", "Admin"),
        ("POST", "/api/admin/analyzers", "Admin"),
        ("POST", "/api/integrations/alertmanager/test", "Admin"),
        ("POST", "/api/case-imports", "Admin"),
    ],
)
def test_each_request_needs_the_role_the_table_says(method: str, path: str, needed: str | None) -> None:
    assert required_role(method, path) == needed


def test_refusals_say_why_and_who_to_ask() -> None:
    assert refusal("/api/findings/9/feedback", "Editor").startswith('Editors answer "Was this real?"')
    assert refusal("/api/autonomous/policies/abc", "Editor") == "Editors can change schedules. Ask your Grafana admin for the Editor role."
    assert refusal("/api/testing/reset-operational-data", "Admin") == "Only Grafana admins can do this."


def test_a_viewer_can_read_and_ask_but_not_change(client: TestClient) -> None:
    finding_id = _create_finding()

    assert client.get("/api/findings", headers=_as("Viewer")).status_code == 200
    refused = client.post(f"/api/findings/{finding_id}/feedback", json={"verdict": "real_problem"}, headers=_as("Viewer"))
    assert refused.status_code == 403
    assert "Ask your Grafana admin for the Editor role" in refused.json()["detail"]
    assert client.post(f"/api/cases/findings/{finding_id}/create", headers=ANONYMOUS_VIEWER).status_code == 403

    assert client.post(f"/api/findings/{finding_id}/feedback", json={"verdict": "real_problem"}, headers=_as("Editor")).status_code == 200


def test_an_editor_is_kept_out_of_admin_actions(client: TestClient) -> None:
    refused = client.post("/api/admin/analyzers/validate", json={}, headers=_as("Editor"))
    assert refused.status_code == 403
    assert refused.json()["detail"] == "Only Grafana admins can do this."
    assert client.post("/api/admin/analyzers/validate", json={}, headers=_as("Admin")).status_code != 403


def test_requests_not_through_grafana_are_not_limited_by_role(client: TestClient) -> None:
    finding_id = _create_finding()
    assert client.post(f"/api/findings/{finding_id}/feedback", json={"verdict": "real_problem"}).status_code == 200


def test_closing_a_case_records_who_and_reopening_clears_it(client: TestClient) -> None:
    case_id = client.post(f"/api/cases/findings/{_create_finding()}/create", headers=_as("Editor", "priya")).json()["case_id"]
    closing = {"outcome_status": "resolved", "outcome_summary": "Rolled back", "corrective_action": "Rollback", "learning_outcome_status": "confirmed"}

    resolved = client.patch(f"/api/cases/{case_id}/resolution", json=closing, headers=_as("Editor", "priya")).json()
    assert resolved["resolved_by"] == "priya"

    reopened = client.patch(f"/api/cases/{case_id}/resolution", json={"outcome_status": "in_progress", "outcome_summary": "", "corrective_action": ""}, headers=_as("Editor", "sam")).json()
    assert reopened["resolved_by"] is None


def test_the_mcp_server_can_still_call_case_functions_directly(client: TestClient) -> None:
    # mcp_server.py calls the endpoint function itself (with the memory arguments), so `actor` keeps
    # its Depends(...) default.
    finding_id = _create_finding()
    with get_session_local()() as db:
        created = create_case_from_finding(finding_id, db, indexer=None, config=None)
    assert created.case_id
    assert actor_name(object()) is None
