from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.app.memory.document_builder import CaseDocumentBuilder
from backend.app.memory.schemas import SimilarCaseMatch
from backend.app.models.db import get_session_local
from backend.app.api import memory as memory_module
from backend.app.models.entities import CaseTicketEventEntity, CaseTicketLinkEntity, FindingEntity, OperationalCaseEntity
from tests.api_backend.test_cases_ai_drafts import _FakeSimilarityService, _ScriptedClient, _assistant_with, _seed_case, client_factory  # noqa: F401

# Publish Knowledge: the case timeline (no AI), saving the write-up, and "Draft write-up".


def _update_case(case_id: int, **fields) -> None:
    with get_session_local()() as db:
        case = db.get(OperationalCaseEntity, case_id)
        for name, value in fields.items():
            setattr(case, name, value)
        db.commit()


def _add_comment(case_id: int, event_id: str, when: datetime, summary: str, *, promoted: bool = False) -> None:
    with get_session_local()() as db:
        db.add(
            CaseTicketEventEntity(
                case_id=case_id,
                provider="jira",
                remote_event_id=event_id,
                event_type="comment_added",
                occurred_at=when,
                created_at=when,
                author="Sam",
                summary=summary,
                payload={"promoted_at": when.isoformat()} if promoted else None,
            )
        )
        db.commit()


def _seed_resolved(case_id: int) -> None:
    _seed_case(case_id, case_id, notes=[{"timestamp": "2026-10-20T14:50:00", "note": "Rolled back to v2.2, CPU normal."}])
    _update_case(
        case_id,
        created_at=datetime(2026, 10, 20, 14, 20),
        resolved_at=datetime(2026, 10, 20, 15, 10, tzinfo=timezone.utc),
        resolved_by="priya",
        outcome_status="resolved",
        root_cause_summary="A retry loop in v2.3 may not release connections.",
        corrective_action="Rolled back to v2.2.",
    )
    with get_session_local()() as db:
        db.get(FindingEntity, case_id).created_at = datetime(2026, 10, 20, 14, 12)
        db.commit()


def _similar_118() -> _FakeSimilarityService:
    return _FakeSimilarityService(
        [
            SimilarCaseMatch(
                case_id=118,
                similarity_score=0.8,
                title="Pool exhaustion after deploy",
                service="checkout-api",
                metric_name="cpu_usage",
                category="behavior_change",
                case_status="resolved",
                investigation_status="completed",
                rca_verified=True,
                root_cause_summary="Connection pool exhaustion after the v2.0 deploy.",
                corrective_action="Rolled back.",
                outcome_status="resolved",
                outcome_summary="Rolled back.",
            )
        ]
    )


# --- Timeline ---------------------------------------------------------------------------------


def test_timeline_lists_what_happened_in_order(client_factory) -> None:
    app = client_factory(assistant=None)

    with TestClient(app) as client:
        _seed_resolved(601)
        with get_session_local()() as db:
            db.add(CaseTicketLinkEntity(case_id=601, provider="jira", remote_id="10412", display_key="OPS-412", ticket_url="https://example.com/OPS-412", created_at=datetime(2026, 10, 20, 14, 22)))
            db.commit()
        _add_comment(601, "c1", datetime(2026, 10, 20, 14, 35, tzinfo=timezone.utc), "v2.3 added a retry loop.")
        _add_comment(601, "c2", datetime(2026, 10, 20, 14, 40, tzinfo=timezone.utc), "Already a note.", promoted=True)
        body = client.get("/api/cases/601/timeline").json()

    kinds = [event["kind"] for event in body["events"]]
    assert kinds == ["finding", "opened", "ticket", "ticket_comment", "note", "resolved"]
    assert body["time_to_fix_minutes"] == 58
    assert body["events"][3] == {"time": "2026-10-20T14:35:00Z", "kind": "ticket_comment", "text": "v2.3 added a retry loop.", "who": "Sam"}
    assert body["events"][-1]["text"] == "Resolved"
    assert body["events"][-1]["who"] == "priya"
    assert "Already a note." not in json.dumps(body["events"])


def test_timeline_starts_at_the_deploy_and_the_change(client_factory, monkeypatch) -> None:
    from backend.app.services import case_timeline

    def matched(_db, findings, _config):
        return {
            findings[0].id: {
                "status": "matched",
                "anchor": "2026-10-20T14:12:00+00:00",
                "matches": [{"event_type": "deploy", "version": "v2.3", "timestamp": "2026-10-20T14:05:00+00:00"}],
            }
        }

    monkeypatch.setattr(case_timeline, "finding_changes", matched)
    app = client_factory(assistant=None)

    with TestClient(app) as client:
        _seed_resolved(602)
        body = client.get("/api/cases/602/timeline").json()

    assert [event["kind"] for event in body["events"]][:2] == ["deploy", "finding"]
    assert body["events"][0]["text"] == "Deploy v2.3 on checkout-api"
    assert body["events"][1]["time"] == "2026-10-20T14:12:00Z"
    assert body["time_to_fix_minutes"] == 58


def test_timeline_404s_for_a_missing_case(client_factory) -> None:
    with TestClient(client_factory(assistant=None)) as client:
        assert client.get("/api/cases/9999/timeline").status_code == 404


# --- Saving -----------------------------------------------------------------------------------


def test_saving_the_writeup_puts_it_in_memory_text_and_marks_an_indexed_case_stale(client_factory) -> None:
    app = client_factory(assistant=None)
    # No indexer: the case is marked stale instead of re-indexed on the spot.
    app.dependency_overrides[memory_module.get_memory_indexer] = lambda: None

    with TestClient(app) as client:
        _seed_resolved(603)
        _update_case(603, memory_status="indexed")
        saved = client.patch("/api/cases/603/writeup", json={"writeup": "  Summary: rolled back.  "}).json()
        timeline = client.get("/api/cases/603/timeline").json()
        cleared = client.patch("/api/cases/603/writeup", json={"writeup": "   "}).json()

    assert saved["writeup"] == "Summary: rolled back."
    assert saved["memory_status"] == "stale"
    assert "Write-up:\nSummary: rolled back." in timeline["memory_text"]
    assert cleared["writeup"] is None


def test_a_case_without_a_writeup_builds_the_same_memory_text() -> None:
    case = OperationalCaseEntity(case_title="t", finding_snapshot={"service": "s"}, investigation_notes=[], root_cause_status="unknown", outcome_status="pending")
    assert "Write-up" not in CaseDocumentBuilder.build(case)


# --- Draft write-up ---------------------------------------------------------------------------


def test_writeup_suggest_needs_a_saved_root_cause_or_resolution(client_factory) -> None:
    fake = _ScriptedClient(response_text="{}")
    app = client_factory(assistant=_assistant_with(fake))

    with TestClient(app) as client:
        _seed_case(604, 604, notes=[{"timestamp": "t", "note": "Looking."}])
        body = client.post("/api/cases/604/writeup/suggest").json()

    assert body["reason_code"] == "not_enough"
    assert fake.calls == []


def test_writeup_suggest_says_ai_off(client_factory) -> None:
    with TestClient(client_factory(assistant=None)) as client:
        _seed_resolved(605)
        assert client.post("/api/cases/605/writeup/suggest").json()["reason_code"] == "ai_off"


def test_writeup_suggest_writes_labelled_paragraphs_from_the_saved_case(client_factory) -> None:
    reply = {
        "summary": "Requests slowed after v2.3; rolling back to v2.2 fixed it in 50 minutes.",
        "likely_cause": "A retry loop in v2.3 may not release connections, from the saved root cause.",
        "seen_before": "Case #118 looks the same and was also rolled back.",
        "still_open": "Fix the retry loop before redeploying.",
    }
    fake = _ScriptedClient(response_text=json.dumps(reply))
    app = client_factory(assistant=_assistant_with(fake), similarity_service=_similar_118())

    with TestClient(app) as client:
        _seed_resolved(606)
        body = client.post("/api/cases/606/writeup/suggest").json()
        case_after = client.get("/api/cases/606").json()

    assert body["available"] is True
    assert body["draft"] == (
        "Summary: Requests slowed after v2.3; rolling back to v2.2 fixed it in 50 minutes.\n\n"
        "Likely cause: A retry loop in v2.3 may not release connections, from the saved root cause.\n\n"
        "Seen before: Case #118 looks the same and was also rolled back.\n\n"
        "Still open: Fix the retry loop before redeploying."
    )
    assert [source["kind"] for source in body["sources"]] == ["root_cause", "corrective_action", "timeline", "similar_case"]
    sent = fake.calls[0].messages[1].content
    assert "Time to fix: 58 minutes from the first finding" in sent
    assert "Similar past case #118" in sent
    assert case_after["writeup"] is None


def test_writeup_suggest_drops_what_the_case_does_not_support(client_factory) -> None:
    reply = {
        "summary": "Rolled back to v2.2. The retry loop was removed.",
        "likely_cause": None,
        "seen_before": "Case #118 looks the same.",
        "still_open": None,
    }
    app = client_factory(assistant=_assistant_with(_ScriptedClient(response_text=json.dumps(reply))), similarity_service=None)

    with TestClient(app) as client:
        _seed_resolved(607)
        body = client.post("/api/cases/607/writeup/suggest").json()

    # "removed" isn't in the case, and with no similar cases there is no "Seen before".
    assert body["draft"] == "Summary: Rolled back to v2.2."
