"""A case resolved, reopened and resolved again: the second Save Resolution must go through.

Each resolve records a learning outcome, and only one is kept per case and finding. The resolution
endpoint used to refuse the second one ("learning outcome already exists") and roll the whole save
back, so a reopened case could never be closed again.
"""

from __future__ import annotations

from backend.app.models.db import get_session_local
from backend.app.models.entities import AnalyzerLearningOutcomeEntity, OperationalCaseEntity
from sqlalchemy import select
from tests.api_backend.test_cases import _create_finding


def _open_case(client) -> int:
    return client.post(f"/api/cases/findings/{_create_finding()}/create").json()["case_id"]


def _save(client, case_id: int, outcome_status: str, corrective_action: str, learning: str | None = None):
    body = {"outcome_status": outcome_status, "outcome_summary": "Errors back to normal", "corrective_action": corrective_action}
    if learning:
        body["learning_outcome_status"] = learning
    return client.patch(f"/api/cases/{case_id}/resolution", json=body)


def _outcomes(case_id: int) -> list[AnalyzerLearningOutcomeEntity]:
    with get_session_local()() as db:
        rows = db.execute(select(AnalyzerLearningOutcomeEntity).where(AnalyzerLearningOutcomeEntity.case_id == case_id)).scalars().all()
        for row in rows:
            db.expunge(row)
        return rows


def _stored(case_id: int) -> OperationalCaseEntity:
    with get_session_local()() as db:
        case = db.get(OperationalCaseEntity, case_id)
        db.expunge(case)
        return case


def test_a_reopened_case_can_be_resolved_again(client) -> None:
    case_id = _open_case(client)
    assert _save(client, case_id, "resolved", "Restarted pods", "confirmed").status_code == 200
    assert _save(client, case_id, "in_progress", "Restarted pods").status_code == 200

    again = _save(client, case_id, "resolved", "Rolled back deploy v2.4.1", "confirmed")

    assert again.status_code == 200, again.text
    assert again.json()["outcome_status"] == "resolved"
    assert _stored(case_id).corrective_action == "Rolled back deploy v2.4.1"


def test_resolving_again_replaces_the_learning_outcome_instead_of_adding_one(client) -> None:
    case_id = _open_case(client)
    _save(client, case_id, "resolved", "Restarted pods", "confirmed")
    _save(client, case_id, "in_progress", "Restarted pods")

    _save(client, case_id, "resolved", "Not a real issue after all", "rejected")

    outcomes = _outcomes(case_id)
    assert len(outcomes) == 1
    assert outcomes[0].outcome_status == "rejected"


def test_editing_a_resolved_case_keeps_it_resolved(client) -> None:
    # The form asks for the learning outcome again whenever Resolved is picked, so editing the
    # text of an already resolved case sends one too.
    case_id = _open_case(client)
    _save(client, case_id, "resolved", "Restarted pods", "confirmed")

    edited = _save(client, case_id, "resolved", "Restarted pods, then rolled back v2.4.1", "confirmed")

    assert edited.status_code == 200, edited.text
    assert _stored(case_id).corrective_action == "Restarted pods, then rolled back v2.4.1"
    assert len(_outcomes(case_id)) == 1


def test_resolved_at_is_the_latest_resolve_not_the_first(client) -> None:
    case_id = _open_case(client)
    _save(client, case_id, "resolved", "Restarted pods", "confirmed")
    first = _stored(case_id).resolved_at

    reopened = _save(client, case_id, "in_progress", "Restarted pods")
    assert reopened.json()["resolved_at"] is None
    _save(client, case_id, "resolved", "Rolled back deploy v2.4.1", "confirmed")

    assert first is not None
    assert _stored(case_id).resolved_at >= first
    assert _stored(case_id).resolved_at != first
