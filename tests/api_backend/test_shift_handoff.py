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
from backend.app.models.entities import BehaviorFindingEntity, FindingEntity, OperationalCaseEntity
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


def _pattern(pattern_id: int, service: str, severity: str, seen_at: datetime) -> BehaviorFindingEntity:
    return BehaviorFindingEntity(
        id=pattern_id,
        behavior_id="queue-backlog",
        definition_id="queue_backlog",
        definition_version=1,
        title=f"{service} queue backing up",
        summary="summary",
        category="saturation",
        severity=severity,
        service=service,
        input_metrics_json={"queue_depth": {}, "consumer_lag": {}},
        facts_json={},
        evidence_json=[],
        matched_conditions_json=[],
        confidence=0.9,
        correlation_json={},
        created_at=seen_at,
        last_seen_at=seen_at,
    )


@pytest.fixture
def seeded(monkeypatch):
    """A shift: payments (critical, after deploy v2.3, open case), checkout (resolved case),
    search (high, no case), an orders combined pattern (high, no case), two old open cases nothing
    happened to this shift (one critical) and an imported past incident."""
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
                    _pattern(20, "orders", "high", now - timedelta(hours=4)),
                    # Last seen two days ago: not this shift's.
                    _pattern(21, "ledger", "critical", now - timedelta(days=2)),
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
    assert body["older_open_cases"] == 2

    watch = body["watch"]
    assert [(item["kind"], item["case_id"] or item["pattern_id"] or item["finding_id"]) for item in watch] == [("case", 10), ("pattern", 20), ("finding", 4)]
    assert watch[0]["deploy_version"] == "v2.3"
    assert watch[0]["reason"] == "open 8 hours, started after deploy v2.3, high importance"
    # Same level: a combined pattern (several metrics agreeing) before a single finding.
    assert watch[1]["reason"] == "combined pattern, no case yet, seen 4 hours ago, high importance"
    assert watch[1]["metric_name"] == "2 metrics"
    assert watch[2]["reason"] == "no case yet, seen 3 hours ago, high importance"
    assert body["summary"] == (
        "Last 12 hours: 4 new findings, 2 cases opened, 1 resolved. 3 cases still open. "
        "Watch first: case #10 (payments error_rate), open 8 hours, started after deploy v2.3, high importance."
    )


def test_longer_list_puts_cases_nobody_touched_last(seeded) -> None:
    watch = seeded().get("/api/overview/handoff", params={"hours": 12, "limit": 10}).json()["watch"]

    # The stale critical case comes after this shift's high items, then the stale low one.
    assert [(item["kind"], item["case_id"] or item["pattern_id"] or item["finding_id"], item["live"]) for item in watch] == [
        ("case", 10, True),
        ("pattern", 20, True),
        ("finding", 4, True),
        ("case", 15, False),
        ("case", 12, False),
    ]
    assert watch[3]["reason"] == "open 5 days, high importance"


def test_handoff_window_is_bounded() -> None:
    client = TestClient(create_app("sqlite+pysqlite:///:memory:"))
    assert client.get("/api/overview/handoff", params={"hours": 0}).status_code == 422
    assert client.get("/api/overview/handoff", params={"hours": 73}).status_code == 422
    assert client.get("/api/overview/handoff", params={"limit": 21}).status_code == 422


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
            "We've seen a high volume of error reports on the checkout side. "
            "Watch case #10 on payments first: still open 8 hours after deploy v2.3. "
            "Case #10 was likely caused by a bad config in v2.4. "
            "Many teams are also seeing orders back up."
        )
    )
    body = seeded(_assistant_with(client)).post("/api/overview/handoff/note", params={"hours": 12}).json()

    assert body["available"] is True
    # Dropped: a sentence naming no item, a version not in the facts, and an amount nothing measured.
    # The counts are code's, never the model's.
    assert body["note"] == (
        "Last 12 hours: 4 new findings, 2 cases opened, 1 resolved. 3 cases still open. "
        "Watch case #10 on payments first: still open 8 hours after deploy v2.3."
    )
    facts = client.calls[0].messages[1].content
    assert facts.startswith("Item 1: case #10 (payments error_rate)")
    assert "Cases still open" not in facts


def test_note_with_nothing_usable_is_not_available(seeded) -> None:
    client = _ScriptedClient(response_text="It has been a busy shift with a high volume of alerts.")
    body = seeded(_assistant_with(client)).post("/api/overview/handoff/note").json()
    assert body["available"] is False
    assert body["reason_code"] == "failed"


def test_note_failure_keeps_the_plain_summary(seeded) -> None:
    body = seeded(_assistant_with(_ScriptedClient(raise_error=True))).post("/api/overview/handoff/note").json()
    assert body["available"] is False
    assert body["reason_code"] == "failed"


def test_viewers_may_ask_for_the_note() -> None:
    assert required_role("POST", "/api/overview/handoff/note") is None
    assert required_role("GET", "/api/overview/handoff") is None
