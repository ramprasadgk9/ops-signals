from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.app.ai.exceptions import AIError
from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.interfaces import LLMRequest, LLMResponse
from backend.app.api import assistant as assistant_module
from backend.app.assistant.service import AssistantServices, OperationalIntelligenceAssistant
from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import FindingEntity, OperationalCaseEntity
from backend.app.roles import required_role
from backend.app.services import shift_handoff


class _ScriptedClient:
    def __init__(self, *, response_text: str = "", raise_error: bool = False) -> None:
        self.response_text = response_text
        self.raise_error = raise_error
        self.calls: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        if self.raise_error:
            raise AIError("boom")
        return LLMResponse(content=self.response_text)


def _assistant_with(client: _ScriptedClient) -> OperationalIntelligenceAssistant:
    return OperationalIntelligenceAssistant(
        AssistantServices(embedder=None, case_similarity=None, docs_store=None, ai_services=OptionalAIServices(client=client, structured=None))
    )


def _finding(finding_id: int, service: str, severity: str, created_at: datetime, *, problem_id: int | None = None, metric: str = "error_rate") -> FindingEntity:
    return FindingEntity(
        id=finding_id,
        problem_id=problem_id,
        analysis_run_id="run-handoff",
        service=service,
        metric_name=metric,
        title=f"{service} {metric} went up",
        summary="summary",
        category="anomaly",
        health_status=severity,
        importance_score=0.9,
        investigation_priority=1,
        signal_ids=[],
        comparison_json={},
        created_at=created_at,
    )


def _case(case_id: int, finding_id: int | None, status: str, created_at: datetime, *, outcome: str = "pending", resolved_at: datetime | None = None, source: str = "detected") -> OperationalCaseEntity:
    return OperationalCaseEntity(
        id=case_id,
        finding_id=finding_id,
        analysis_run_id="run-handoff",
        case_title=f"Case {case_id}",
        case_status=status,
        finding_snapshot={},
        investigation_status="in_progress",
        investigation_notes=[],
        root_cause_status="unknown",
        root_cause_verified=False,
        outcome_status=outcome,
        memory_status="not_indexed",
        created_at=created_at,
        updated_at=resolved_at or created_at,
        resolved_at=resolved_at,
        source=source,
        source_id="INC-1" if source != "detected" else None,
    )


@pytest.fixture
def seeded(monkeypatch):
    """A shift: payments (critical, after deploy v2.3, open case), checkout (resolved case),
    search (high, no case), two old open cases nothing happened to this shift (one critical) and
    an imported past incident."""
    # Trust and deploys have their own tests; here every finding needs attention and only
    # payments' finding matched a deploy.
    monkeypatch.setattr(shift_handoff, "finding_trust", lambda _db, rows: {row.id: {"tier": "needs_attention"} for row in rows})
    monkeypatch.setattr(
        shift_handoff,
        "finding_changes",
        lambda _db, rows, _config: {
            row.id: {"status": "matched", "matches": [{"version": "v2.3", "timestamp": "2026-10-27T01:00:00+00:00"}]} if row.service == "payments" else {"status": "none_in_window"}
            for row in rows
        },
    )

    def _make(assistant=None):
        app = create_app("sqlite+pysqlite:///:memory:")
        app.dependency_overrides[assistant_module.get_assistant] = lambda: assistant
        client = TestClient(app)
        client.__enter__()
        now = datetime.utcnow()
        with get_session_local()() as db:
            db.add_all(
                [
                    _finding(1, "payments", "critical", now - timedelta(hours=9)),
                    _finding(2, "payments", "critical", now - timedelta(hours=1), problem_id=1),
                    _finding(3, "checkout", "medium", now - timedelta(hours=6)),
                    _finding(4, "search", "high", now - timedelta(hours=3)),
                    _finding(5, "inventory", "low", now - timedelta(days=3)),
                    _finding(6, "billing", "low", now - timedelta(hours=2)),
                    _finding(7, "ledger", "critical", now - timedelta(days=5)),
                    _case(10, 1, "open", now - timedelta(hours=8)),
                    _case(11, 3, "resolved", now - timedelta(hours=5), outcome="resolved", resolved_at=now - timedelta(hours=2)),
                    _case(12, 5, "open", now - timedelta(days=3)),
                    _case(13, None, "open", now - timedelta(hours=1), source="imported"),
                    _case(15, 7, "open", now - timedelta(days=5)),
                    # Resolved last week: not this shift's.
                    _case(14, 6, "resolved", now - timedelta(days=8), outcome="resolved", resolved_at=now - timedelta(days=7)),
                ]
            )
            db.commit()
        return client

    yield _make


def test_handoff_counts_the_shift_and_ranks_what_to_watch(seeded) -> None:
    body = seeded().get("/api/overview/handoff", params={"hours": 12}).json()

    # Payments seen twice is one new problem; inventory is from three days ago.
    assert body["new_findings"] == 4
    # Imported past incidents are not this shift's cases.
    assert body["cases_opened"] == 2
    assert body["cases_resolved"] == 1
    assert body["cases_still_open"] == 3

    watch = body["watch"]
    # This shift's problems first: the stale critical case comes after the fresh high finding.
    assert [(item["kind"], item["case_id"] or item["finding_id"]) for item in watch] == [("case", 10), ("finding", 4), ("case", 15)]
    assert watch[0]["deploy_version"] == "v2.3"
    assert watch[0]["reason"] == "open 8 hours, started after deploy v2.3, high importance"
    assert watch[1]["reason"] == "no case yet, seen 3 hours ago, high importance"
    assert watch[2]["reason"] == "open 5 days, high importance"
    assert body["summary"] == (
        "Last 12 hours: 4 new findings, 2 cases opened, 1 resolved. 3 cases still open. "
        "Watch first: case #10 (payments error_rate), open 8 hours, started after deploy v2.3, high importance."
    )


def test_handoff_window_is_bounded() -> None:
    client = TestClient(create_app("sqlite+pysqlite:///:memory:"))
    assert client.get("/api/overview/handoff", params={"hours": 0}).status_code == 422
    assert client.get("/api/overview/handoff", params={"hours": 73}).status_code == 422


def test_empty_shift_says_nothing_needs_watching() -> None:
    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
        body = client.get("/api/overview/handoff").json()
    assert body["watch"] == []
    assert body["summary"] == "Last 12 hours: 0 new findings, 0 cases opened, 0 resolved. 0 cases still open. Nothing open needs watching."


def test_note_without_ai_says_so(seeded) -> None:
    body = seeded().post("/api/overview/handoff/note").json()
    assert body == {"available": False, "note": None, "reason": "AI assistance is not configured", "reason_code": "ai_off"}


def test_note_is_written_from_the_facts_only(seeded) -> None:
    client = _ScriptedClient(
        response_text=(
            "Last 12 hours brought 4 new findings and 1 resolved case. "
            "Watch case #10 on payments first: still open 8 hours after deploy v2.3. "
            "It was likely caused by a bad config in v2.4."
        )
    )
    body = seeded(_assistant_with(client)).post("/api/overview/handoff/note", params={"hours": 12}).json()

    assert body["available"] is True
    # The last sentence names a version that isn't in the facts, so it is dropped.
    assert body["note"] == "Last 12 hours brought 4 new findings and 1 resolved case. Watch case #10 on payments first: still open 8 hours after deploy v2.3."
    facts = client.calls[0].messages[1].content
    assert "Item 1: case #10 (payments error_rate)" in facts
    assert "Cases still open: 3." in facts


def test_note_failure_keeps_the_plain_summary(seeded) -> None:
    body = seeded(_assistant_with(_ScriptedClient(raise_error=True))).post("/api/overview/handoff/note").json()
    assert body["available"] is False
    assert body["reason_code"] == "failed"


def test_viewers_may_ask_for_the_note() -> None:
    assert required_role("POST", "/api/overview/handoff/note") is None
    assert required_role("GET", "/api/overview/handoff") is None
