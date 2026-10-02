from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from backend.app.config import JiraConfig, TicketingConfig
from backend.app.integrations.ticketing.models import (
    AmbiguousResolutionRequest,
    RemoteEventDraft,
    RemoteTicketSnapshot,
    TicketCreationResult,
    TicketDraft,
)
from backend.app.integrations.ticketing.protocols import (
    AmbiguousOutcomeError,
    LeaseLostError,
    ProviderNotConfiguredError,
)
from backend.app.integrations.ticketing.service import CaseTicketing
from backend.app.models.db import get_session_local
from backend.app.models.entities import (
    AnalysisRunEntity,
    CaseTicketEventEntity,
    CaseTicketLinkEntity,
    FindingEntity,
    OperationalCaseEntity,
    TicketOperationEntity,
    TicketWebhookDeliveryEntity,
)


def _setup_test_case(db_session) -> int:
    from uuid import uuid4
    now = datetime.now(timezone.utc)
    run = AnalysisRunEntity(
        id=f"run_{uuid4().hex[:12]}",
        source_type="prometheus",
        provider="prometheus",
        service="checkout-service",
        metric_name="http_errors",
        start_time=now - timedelta(hours=1),
        end_time=now,
        sample_count=50,
        status="completed",
    )
    db_session.add(run)
    finding = FindingEntity(
        analysis_run_id=run.id,
        service="checkout-service",
        metric_name="http_errors",
        title="Elevated HTTP 5xx errors",
        summary="Error rate spiked above 5%",
        category="error_rate",
        health_status="critical",
        importance_score=0.95,
        investigation_priority=1,
        signal_ids=["sig-1"],
    )
    db_session.add(finding)
    db_session.commit()
    db_session.refresh(finding)

    case = OperationalCaseEntity(
        finding_id=finding.id,
        analysis_run_id=run.id,
        case_title="Elevated HTTP 5xx errors",
        case_status="open",
        finding_snapshot={"service": "checkout-service", "metric_name": "http_errors", "summary": "Spike in errors"},
    )
    db_session.add(case)
    db_session.commit()
    db_session.refresh(case)
    return case.id


class DummyJiraProvider:
    def __init__(self, config=None):
        self.config = config or JiraConfig(
            base_url="https://example.atlassian.net",
            email="eng@example.com",
            api_token="tok",
            project_key="OPS",
            webhook_secret="test-secret",
        )
        self.is_configured = True
        self.base_url = "https://example.atlassian.net"
        self.reconcile_or_create_calls = []

    def reconcile_or_create(self, draft: TicketDraft, operation_id: str) -> TicketCreationResult:
        self.reconcile_or_create_calls.append((draft, operation_id))
        return TicketCreationResult(
            remote_id="10101",
            display_key="OPS-101",
            ticket_url="https://example.atlassian.net/browse/OPS-101",
            initial_status="open",
        )

    def pull_remote_ticket(self, remote_id: str, display_key: str, cursor: str | None) -> RemoteTicketSnapshot:
        return RemoteTicketSnapshot(
            remote_id="10101",
            display_key=display_key,
            remote_status="In Progress",
            comments=[{"id": "c-1", "author": "dev", "body": "Looking into it"}],
            changelog_items=[],
            cursor="cursor-123",
        )

    def verify_signature(self, raw_body: bytes, headers, secret: str) -> bool:
        sig = headers.get("X-Hub-Signature", "")
        expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)

    def extract_delivery_id(self, headers) -> str | None:
        return headers.get("X-Atlassian-Webhook-Identifier")

    def parse_webhook_event(self, raw_body: bytes, headers) -> RemoteEventDraft | None:
        import json
        data = json.loads(raw_body.decode())
        issue = data.get("issue", {})
        return RemoteEventDraft(
            remote_id=str(issue.get("id")),
            display_key=issue.get("key"),
            remote_event_id=data.get("event_id", "evt_1"),
            event_type="status_changed",
            author="Jira User",
            summary="Remote status changed to Resolved",
            observed_remote_status="Resolved",
            occurred_at=datetime.now(timezone.utc),
        )


def test_outbox_create_and_process_lifecycle(db_session):
    case_id = _setup_test_case(db_session)
    provider = DummyJiraProvider()
    config = TicketingConfig(enabled=True, active_provider="jira")
    service = CaseTicketing(
        session_factory=lambda: db_session,
        config=config,
        providers={"jira": provider},
    )

    # 1. Enqueue create operation
    op_view = service.request_create(case_id)
    assert op_view.status == "pending"
    assert op_view.operation_type == "create_ticket"
    assert op_view.case_id == case_id

    # 2. Process pending operation
    processed = service.process_pending_operations(limit=10)
    assert processed == 1
    assert len(provider.reconcile_or_create_calls) == 1

    # 3. Assert operation completed and link persisted
    op_after = service.get_operation_view(op_view.operation_id)
    assert op_after.status == "completed"

    link_view = service.get_ticket_view(case_id)
    assert link_view is not None
    assert link_view.remote_id == "10101"
    assert link_view.display_key == "OPS-101"
    assert link_view.observed_remote_status == "open"

    # 4. Assert timeline event created
    events = service.list_ticket_events(case_id)
    assert len(events) == 1
    assert events[0].event_type == "ticket_created"
    assert "OPS-101" in events[0].summary

    # 5. Idempotent second create returns completed operation
    second_op = service.request_create(case_id)
    assert second_op.status == "completed"


def test_sweeper_transitions_expired_creates_to_ambiguous_outcome(db_session):
    case_id = _setup_test_case(db_session)
    provider = DummyJiraProvider()
    config = TicketingConfig(enabled=True)
    service = CaseTicketing(session_factory=lambda: db_session, config=config, providers={"jira": provider})

    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    expired_op = TicketOperationEntity(
        id="op_expired",
        case_id=case_id,
        provider="jira",
        operation_type="create_ticket",
        idempotency_key="idem_expired",
        status="processing",
        attempts=1,
        max_attempts=5,
        available_at=past,
        lease_token="stale_token",
        lease_expires_at=past,
        created_at=past,
        updated_at=past,
    )
    db_session.add(expired_op)
    db_session.commit()

    swept = service.sweep_expired_creates()
    assert swept == 1

    op_after = service.get_operation_view("op_expired")
    assert op_after.status == "ambiguous_outcome"
    assert "Worker lease expired" in (op_after.last_error or "")

    # Expired creates must NOT be automatically reclaimed by process_pending_operations
    claimed = service.process_pending_operations(limit=10)
    assert claimed == 0


def test_ambiguous_outcome_circuit_and_three_way_resolution(db_session):
    # Setup 3 independent cases to test each resolution path
    case_1 = _setup_test_case(db_session)
    case_2 = _setup_test_case(db_session)
    case_3 = _setup_test_case(db_session)

    mock_provider = MagicMock()
    mock_provider.is_configured = True
    mock_provider.reconcile_or_create.side_effect = AmbiguousOutcomeError("HTTP 504 Gateway Timeout")

    config = TicketingConfig(enabled=True)
    service = CaseTicketing(session_factory=lambda: db_session, config=config, providers={"jira": mock_provider})

    # Case 1: Ambiguous -> Choice 1: Check Jira Again (reconcile by label)
    op_1 = service.request_create(case_1)
    service.process_pending_operations(limit=10)
    assert service.get_operation_view(op_1.operation_id).status == "ambiguous_outcome"

    mock_provider.reconcile_or_create.side_effect = None
    mock_provider.reconcile_or_create.return_value = TicketCreationResult(
        remote_id="20202", display_key="OPS-202", ticket_url="https://example/OPS-202", initial_status="open"
    )
    res_1 = service.resolve_ambiguity(case_1, AmbiguousResolutionRequest(action="check_again"))
    assert res_1.display_key == "OPS-202"
    assert service.get_ticket_view(case_1).display_key == "OPS-202"

    # Case 2: Ambiguous -> Choice 2: Link Existing Ticket
    mock_provider.reconcile_or_create.side_effect = AmbiguousOutcomeError("HTTP 504 Gateway Timeout")
    op_2 = service.request_create(case_2)
    service.process_pending_operations(limit=10)
    assert service.get_operation_view(op_2.operation_id).status == "ambiguous_outcome"

    mock_provider.pull_remote_ticket.return_value = RemoteTicketSnapshot(
        remote_id="30303", display_key="OPS-303", remote_status="In Review"
    )
    res_2 = service.resolve_ambiguity(
        case_2, AmbiguousResolutionRequest(action="link_existing", remote_key="OPS-303")
    )
    assert res_2.display_key == "OPS-303"
    assert service.get_ticket_view(case_2).remote_id == "30303"

    # Case 3: Ambiguous -> Choice 3: Force Create New (spawn successor operation)
    op_3 = service.request_create(case_3)
    service.process_pending_operations(limit=10)
    assert service.get_operation_view(op_3.operation_id).status == "ambiguous_outcome"

    force_op = service.resolve_ambiguity(
        case_3, AmbiguousResolutionRequest(action="force_create_new")
    )
    assert force_op.status == "pending"
    assert force_op.operation_id != op_3.operation_id


def test_fault_injection_completion_rolls_back_atomically(db_session, monkeypatch):
    case_id = _setup_test_case(db_session)
    provider = DummyJiraProvider()
    config = TicketingConfig(enabled=True)
    service = CaseTicketing(session_factory=lambda: db_session, config=config, providers={"jira": provider})

    op_view = service.request_create(case_id)

    # Inject failure right after operation update by raising during link insertion
    real_add = db_session.add
    def failing_add(instance):
        if isinstance(instance, CaseTicketLinkEntity):
            raise RuntimeError("Database crash during link upsert!")
        return real_add(instance)

    monkeypatch.setattr(db_session, "add", failing_add)

    # Process operations
    service.process_pending_operations(limit=1)

    # Assert single-transaction atomic rollback:
    # No link was persisted
    assert service.get_ticket_view(case_id) is None
    # Operation was rolled back and failed with the error
    op_after = service.get_operation_view(op_view.operation_id)
    assert op_after.status == "failed"
    assert "Database crash during link upsert!" in (op_after.last_error or "")


def test_fault_injection_lost_lease_rolls_back(db_session):
    case_id = _setup_test_case(db_session)
    provider = DummyJiraProvider()
    config = TicketingConfig(enabled=True)
    service = CaseTicketing(session_factory=lambda: db_session, config=config, providers={"jira": provider})

    op_view = service.request_create(case_id)

    # Simulate another worker stealing the lease by changing lease_token in DB
    with db_session.begin_nested():
        row = db_session.query(TicketOperationEntity).filter_by(id=op_view.operation_id).first()
        row.lease_token = "stolen_by_worker_b"
        db_session.commit()

    # Attempt execution with original token
    service._execute_create_operation(op_view.operation_id, "original_token", case_id, provider)

    # Assert lease lost handled cleanly: no link created and operation not marked completed
    assert service.get_ticket_view(case_id) is None
    op = service.get_operation_view(op_view.operation_id)
    assert op.status != "completed"



def test_webhook_ingestion_and_deduplication(db_session):
    case_id = _setup_test_case(db_session)
    provider = DummyJiraProvider()
    config = TicketingConfig(enabled=True)
    service = CaseTicketing(session_factory=lambda: db_session, config=config, providers={"jira": provider})

    # First link ticket OPS-101
    service.link_existing_ticket(case_id, "jira", "OPS-101")

    # Inbound webhook payload
    raw_body = b'{"event_id": "wh_001", "issue": {"id": "10101", "key": "OPS-101"}}'
    sig = "sha256=" + hmac.new(b"test-secret", raw_body, hashlib.sha256).hexdigest()
    headers = {
        "X-Hub-Signature": sig,
        "X-Atlassian-Webhook-Identifier": "deliv-12345",
    }

    # 1. Process valid webhook
    status_code, body = service.accept_webhook("jira", raw_body, headers)
    assert status_code == 200
    assert body["status"] == "processed"
    assert body["case_id"] == case_id

    # Assert status updated to Resolved
    link = service.get_ticket_view(case_id)
    assert link.observed_remote_status == "Resolved"

    # 2. Duplicate delivery ignored
    dup_code, dup_body = service.accept_webhook("jira", raw_body, headers)
    assert dup_code == 200
    assert dup_body["status"] == "duplicate_ignored"

    # 3. Invalid signature rejected
    bad_code, bad_body = service.accept_webhook("jira", raw_body, {"X-Hub-Signature": "sha256=bad"})
    assert bad_code == 401
    assert "Invalid webhook" in bad_body["error"]

    # 4. Unlinked ticket acknowledged and ignored
    unlinked_body = b'{"event_id": "wh_002", "issue": {"id": "99999", "key": "OPS-999"}}'
    unlinked_sig = "sha256=" + hmac.new(b"test-secret", unlinked_body, hashlib.sha256).hexdigest()
    unlinked_code, unlinked_res = service.accept_webhook(
        "jira", unlinked_body, {"X-Hub-Signature": unlinked_sig, "X-Atlassian-Webhook-Identifier": "deliv-999"}
    )
    assert unlinked_code == 200
    assert unlinked_res["status"] == "unlinked_ticket_acknowledged"


def test_fastapi_ticketing_endpoints(client):
    # Create finding & case via existing API
    finding_res = client.post("/api/cases/findings/1/create")
    assert finding_res.status_code in (200, 404)
    # If finding 1 doesn't exist in in-memory DB, use direct session
    session_local = get_session_local()
    with session_local() as db:
        case_id = _setup_test_case(db)

    # 1. POST /api/cases/{case_id}/ticket/create -> 202
    create_res = client.post(f"/api/cases/{case_id}/ticket/create")
    assert create_res.status_code == 202
    data = create_res.json()
    assert data["status"] == "pending"
    assert data["operation_type"] == "create_ticket"
    op_id = data["operation_id"]

    # 2. GET /api/cases/{case_id}/ticket/operations/{op_id} -> 200
    op_res = client.get(f"/api/cases/{case_id}/ticket/operations/{op_id}")
    assert op_res.status_code == 200
    assert op_res.json()["operation_id"] == op_id

    # 3. GET /api/cases/{case_id}/ticket -> 200 (initially None before link is stored)
    ticket_res = client.get(f"/api/cases/{case_id}/ticket")
    assert ticket_res.status_code == 200

    # 4. GET /api/cases/{case_id}/ticket/events -> 200
    events_res = client.get(f"/api/cases/{case_id}/ticket/events")
    assert events_res.status_code == 200
    assert isinstance(events_res.json(), list)
