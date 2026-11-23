"""QA-05: a case resolved through the API must be resolved everywhere, not only on its own page.

The Cases API derived the status for its response and never saved it, so the stored column stayed
"open". Tests checked the response (right) and seeded resolved cases straight into the database
for Overview and memory (also right), so nothing covered "resolve it, then look elsewhere".
"""

from __future__ import annotations

from datetime import datetime

from backend.app.memory.fix_outcomes import _when_fixed
from backend.app.models.db import get_session_local
from backend.app.models.entities import OperationalCaseEntity
from backend.app.services.case_status import backfill_case_statuses
from tests.api_backend.test_cases import _create_finding


def _stored(case_id: int) -> OperationalCaseEntity:
    with get_session_local()() as db:
        case = db.get(OperationalCaseEntity, case_id)
        db.expunge(case)
        return case


def _open_case(client) -> int:
    return client.post(f"/api/cases/findings/{_create_finding()}/create").json()["case_id"]


def _resolve(client, case_id: int) -> None:
    assert client.patch(
        f"/api/cases/{case_id}/resolution",
        json={
            "outcome_status": "resolved",
            "outcome_summary": "Rolled back canary",
            "corrective_action": "Rollback deploy",
            "learning_outcome_status": "confirmed",
        },
    ).status_code == 200
    assert client.patch(
        f"/api/cases/{case_id}/rca",
        json={
            "root_cause_status": "confirmed",
            "root_cause_summary": "Bad canary rollout",
            "root_cause_confidence": 0.9,
            "root_cause_verified": True,
        },
    ).status_code == 200


def test_resolving_a_case_saves_the_status_and_overview_stops_counting_it(client) -> None:
    case_id = _open_case(client)
    assert client.get("/api/overview/summary").json()["open_cases"] == 1

    _resolve(client, case_id)

    assert _stored(case_id).case_status == "resolved"
    assert client.get(f"/api/cases/{case_id}").json()["case_status"] == "resolved"
    assert client.get("/api/overview/summary").json()["open_cases"] == 0


def test_a_fix_resolved_in_the_ui_counts_for_this_fix_worked_before(client) -> None:
    case_id = _open_case(client)
    _resolve(client, case_id)

    assert _when_fixed(_stored(case_id)) is not None


def test_a_case_goes_back_when_its_closing_outcome_is_withdrawn(client) -> None:
    case_id = _open_case(client)
    _resolve(client, case_id)

    withdrawn = client.patch(
        f"/api/cases/{case_id}/resolution",
        json={"outcome_status": "in_progress", "outcome_summary": "Rolled back canary", "corrective_action": "Rollback deploy"},
    )

    # Reopened even with the root cause verified, a fix and an outcome summary: "In progress" is
    # the user saying it isn't done.
    assert withdrawn.json()["case_status"] == "in_progress"
    assert _stored(case_id).case_status == "in_progress"
    assert client.get("/api/overview/summary").json()["open_cases"] == 1


def test_the_original_rule_still_resolves_a_case_whose_outcome_was_never_picked(client) -> None:
    # Cases resolved under the original rule keep their status when the backend restarts.
    case_id = _open_case(client)
    with get_session_local()() as db:
        case = db.get(OperationalCaseEntity, case_id)
        case.outcome_status = "pending"
        case.outcome_summary = "Rolled back canary"
        case.corrective_action = "Rollback deploy"
        case.root_cause_verified = True
        case.root_cause_summary = "Bad canary rollout"
        case.case_status = "resolved"
        db.commit()

    with get_session_local()() as db:
        backfill_case_statuses(db)
        db.commit()

    assert _stored(case_id).case_status == "resolved"


def test_a_closing_outcome_resolves_the_case_even_with_the_root_cause_unconfirmed(client) -> None:
    # Option B (dev case C-38): outcome "resolved" with the RCA not verified. The user said it's
    # done, so it's resolved and leaves Overview's open cases; the UI marks the cause unconfirmed.
    case_id = _open_case(client)
    response = client.patch(
        f"/api/cases/{case_id}/resolution",
        json={"outcome_status": "resolved", "outcome_summary": "queries improved", "corrective_action": "tune the queries", "learning_outcome_status": "confirmed"},
    )

    body = response.json()
    assert body["case_status"] == "resolved"
    assert body["root_cause_verified"] is False
    assert _stored(case_id).case_status == "resolved"
    assert client.get("/api/overview/summary").json()["open_cases"] == 0


def test_a_case_resolved_under_the_original_rule_stays_resolved(client) -> None:
    # Dev case 9: outcome "escalated" (not a closing outcome) but RCA verified with a fix and an
    # outcome summary. Resolved before; must not reopen.
    case_id = _open_case(client)
    client.patch(
        f"/api/cases/{case_id}/resolution",
        json={"outcome_status": "escalated", "outcome_summary": "handed to db team", "corrective_action": "add index"},
    )
    verified = client.patch(
        f"/api/cases/{case_id}/rca",
        json={"root_cause_status": "confirmed", "root_cause_summary": "missing index", "root_cause_confidence": 0.9, "root_cause_verified": True},
    )

    assert verified.json()["case_status"] == "resolved"


def test_a_pending_outcome_does_not_close_the_case(client) -> None:
    case_id = _open_case(client)
    response = client.patch(
        f"/api/cases/{case_id}/resolution",
        json={"outcome_status": "pending", "outcome_summary": "", "corrective_action": "tune the queries"},
    )

    assert response.json()["case_status"] == "open"
    assert client.get("/api/overview/summary").json()["open_cases"] == 1


def test_startup_backfill_corrects_cases_saved_before_the_fix(client) -> None:
    resolved_at = datetime(2026, 9, 30, 12, 0)
    with get_session_local()() as db:
        old = OperationalCaseEntity(
            finding_id=_create_finding(),
            analysis_run_id="run-test-1",
            finding_snapshot={},
            case_title="Resolved before the fix",
            case_status="open",
            root_cause_summary="Bad canary rollout",
            root_cause_verified=True,
            corrective_action="Rollback deploy",
            outcome_status="resolved",
            outcome_summary="Rolled back canary",
            memory_status="indexed",
            resolved_at=resolved_at,
        )
        untouched = OperationalCaseEntity(
            finding_id=_create_finding(analysis_run_id="run-test-2"),
            analysis_run_id="run-test-2",
            finding_snapshot={},
            case_title="Still open",
            case_status="open",
        )
        db.add_all([old, untouched])
        db.commit()
        old_id, untouched_id = old.id, untouched.id

        assert backfill_case_statuses(db) == 1
        assert backfill_case_statuses(db) == 0

    fixed = _stored(old_id)
    assert fixed.case_status == "resolved"
    assert fixed.resolved_at.replace(tzinfo=None) == resolved_at
    assert fixed.memory_status == "stale"
    assert _stored(untouched_id).case_status == "open"


def test_saving_the_case_again_keeps_its_resolved_time(client) -> None:
    # The learning service records when the outcome was resolved; a later save (here an
    # investigation note) must not wipe it.
    case_id = _open_case(client)
    client.patch(
        f"/api/cases/{case_id}/rca",
        json={"root_cause_status": "identified", "root_cause_summary": "db query issues", "root_cause_confidence": 0.6, "root_cause_verified": False},
    )
    client.patch(
        f"/api/cases/{case_id}/resolution",
        json={"outcome_status": "resolved", "outcome_summary": "queries improved", "corrective_action": "tune the queries", "learning_outcome_status": "confirmed"},
    )
    resolved_at = _stored(case_id).resolved_at
    assert resolved_at is not None

    client.patch(f"/api/cases/{case_id}/investigation", json={"investigation_status": "in_progress", "investigation_note": "follow-up"})

    stored = _stored(case_id)
    assert stored.case_status == "resolved"
    assert stored.resolved_at == resolved_at
