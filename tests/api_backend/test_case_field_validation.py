"""QA-06: any string was stored as a case status ("banana", "zzz") and a root cause confidence of
7 or -1 was accepted."""

from __future__ import annotations

import pytest

from backend.app.api.mcp import list_tools
from backend.app.models.api_schema import INVESTIGATION_STATUSES, OUTCOME_STATUSES, ROOT_CAUSE_STATUSES
from tests.api_backend.test_cases import _create_finding


def _case(client) -> int:
    return client.post(f"/api/cases/findings/{_create_finding()}/create").json()["case_id"]


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("investigation", {"investigation_status": "banana"}),
        ("rca", {"root_cause_status": "zzz"}),
        ("rca", {"root_cause_status": "identified", "root_cause_confidence": 7}),
        ("rca", {"root_cause_status": "identified", "root_cause_confidence": -1}),
        ("resolution", {"outcome_status": "done-ish"}),
    ],
)
def test_invalid_values_are_rejected_and_nothing_is_stored(client, path: str, payload: dict) -> None:
    case_id = _case(client)
    before = client.get(f"/api/cases/{case_id}").json()

    response = client.patch(f"/api/cases/{case_id}/{path}", json=payload)

    assert response.status_code == 422
    assert client.get(f"/api/cases/{case_id}").json() == before


def test_every_value_the_web_ui_and_plugin_send_is_accepted(client) -> None:
    case_id = _case(client)
    for status in INVESTIGATION_STATUSES:
        assert client.patch(f"/api/cases/{case_id}/investigation", json={"investigation_status": status}).status_code == 200
    for status in ROOT_CAUSE_STATUSES:
        assert client.patch(f"/api/cases/{case_id}/rca", json={"root_cause_status": status, "root_cause_confidence": 0.85}).status_code == 200
    for status in OUTCOME_STATUSES:
        body = {"outcome_status": status, "learning_outcome_status": "confirmed"}
        assert client.patch(f"/api/cases/{case_id}/resolution", json=body).status_code in (200, 409), status


def test_confidence_bounds_are_inclusive(client) -> None:
    case_id = _case(client)
    for confidence in (0, 1):
        response = client.patch(f"/api/cases/{case_id}/rca", json={"root_cause_status": "identified", "root_cause_confidence": confidence})
        assert response.status_code == 200


def test_mcp_tools_advertise_the_allowed_values() -> None:
    schemas = {tool["name"]: tool["inputSchema"]["properties"]["payload"]["properties"] for tool in list_tools() if tool["name"].startswith("update_")}

    assert schemas["update_investigation"]["investigation_status"]["enum"] == list(INVESTIGATION_STATUSES)
    assert schemas["update_rca"]["root_cause_status"]["enum"] == list(ROOT_CAUSE_STATUSES)
    assert (schemas["update_rca"]["root_cause_confidence"]["minimum"], schemas["update_rca"]["root_cause_confidence"]["maximum"]) == (0, 1)
    assert schemas["update_resolution"]["outcome_status"]["enum"] == list(OUTCOME_STATUSES)
