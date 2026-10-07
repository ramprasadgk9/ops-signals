from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.services.comment_triage_service import (
    CaseTriageContext,
    CommentTriageEvaluation,
    CommentTriageService,
)
from backend.app.config import TicketingConfig
from backend.app.integrations.ticketing.jira.adapter import JiraTicketProvider
from backend.app.integrations.ticketing.models import (
    AmbiguousResolutionRequest,
    CaseNotePromoteResult,
    CommentTriageResult,
    RemoteEventDraft,
    TicketCreationResult,
    TicketDraft,
    TicketEventView,
    TicketOperationView,
    TicketResolutionDraft,
    TicketResolutionResult,
    TicketView,
    WebhookInfoView,
)
from backend.app.integrations.ticketing.protocols import (
    AmbiguousOutcomeError,
    LeaseLostError,
    ProviderNotConfiguredError,
    TicketNotFoundError,
    TicketResolver,
    TicketingError,
)
from backend.app.models.entities import (
    CaseTicketEventEntity,
    CaseTicketLinkEntity,
    FindingEntity,
    OperationalCaseEntity,
    TicketOperationEntity,
    TicketWebhookDeliveryEntity,
)

logger = logging.getLogger(__name__)


class CaseTicketing:
    """Core domain façade and outbox engine for case ticketing integrations."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        config: TicketingConfig,
        providers: dict[str, Any] | None = None,
        ai_services: OptionalAIServices | None = None,
        ai_services_supplier: Callable[[], OptionalAIServices | None] | None = None,
        triage_service: CommentTriageService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self.config = config
        self._ai_services = ai_services
        self._ai_services_supplier = ai_services_supplier
        self._triage_service = triage_service or CommentTriageService()
        if providers is not None:
            self.providers = providers
        else:
            self.providers = {
                "jira": JiraTicketProvider(config.jira),
            }

    def _get_ai_services(self, override: OptionalAIServices | None = None) -> OptionalAIServices | None:
        if override is not None:
            return override
        if self._ai_services is not None:
            return self._ai_services
        if self._ai_services_supplier is not None:
            try:
                return self._ai_services_supplier()
            except Exception as exc:
                logger.warning("Failed to resolve ai_services from supplier: %s", exc)
        return None

    def _get_provider(self, provider_name: str) -> Any:
        provider = self.providers.get(provider_name)
        if not provider:
            raise TicketingError(f"Unknown ticketing provider: {provider_name}")
        return provider

    def request_create(
        self,
        case_id: int,
        idempotency_key: str | None = None,
        provider: str | None = None,
    ) -> TicketOperationView:
        """Enqueues an asynchronous create_ticket operation."""
        provider_name = provider or self.config.active_provider
        idem_key = idempotency_key or f"case_{case_id}_create"

        with self._session_factory() as session:
            # 1. Check if link already exists
            existing_link = (
                session.query(CaseTicketLinkEntity)
                .filter_by(case_id=case_id, provider=provider_name)
                .first()
            )
            if existing_link:
                # Return synthetic completed view or existing operation view
                existing_op = (
                    session.query(TicketOperationEntity)
                    .filter_by(case_id=case_id, provider=provider_name, operation_type="create_ticket")
                    .order_by(TicketOperationEntity.created_at.desc())
                    .first()
                )
                if existing_op:
                    return self._to_operation_view(existing_op)

            # 2. Check for existing operation with this idempotency key
            existing_op = (
                session.query(TicketOperationEntity)
                .filter_by(provider=provider_name, idempotency_key=idem_key)
                .first()
            )
            if existing_op:
                # If a previous attempt explicitly failed, allow the operator to re-trigger it
                if existing_op.status == "failed":
                    now = datetime.now(timezone.utc)
                    existing_op.status = "pending"
                    existing_op.attempts = 0
                    existing_op.available_at = now
                    existing_op.error_message = None
                    existing_op.lease_token = None
                    existing_op.lease_expires_at = None
                    existing_op.updated_at = now
                    session.commit()
                    session.refresh(existing_op)
                return self._to_operation_view(existing_op)

            now = datetime.now(timezone.utc)
            op = TicketOperationEntity(
                id=f"op_{uuid4().hex[:16]}",
                case_id=case_id,
                provider=provider_name,
                operation_type="create_ticket",
                idempotency_key=idem_key,
                status="pending",
                attempts=0,
                max_attempts=self.config.outbox_max_attempts,
                available_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(op)
            session.commit()
            session.refresh(op)
            return self._to_operation_view(op)

    def request_sync(self, case_id: int, provider: str | None = None) -> TicketOperationView:
        """Enqueues an asynchronous sync_ticket operation."""
        provider_name = provider or self.config.active_provider
        with self._session_factory() as session:
            now = datetime.now(timezone.utc)
            op = TicketOperationEntity(
                id=f"op_{uuid4().hex[:16]}",
                case_id=case_id,
                provider=provider_name,
                operation_type="sync_ticket",
                idempotency_key=f"sync_{case_id}_{uuid4().hex[:8]}",
                status="pending",
                attempts=0,
                max_attempts=self.config.outbox_max_attempts,
                available_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(op)
            session.commit()
            session.refresh(op)
            return self._to_operation_view(op)

    def request_resolve(
        self,
        case_id: int,
        provider: str | None = None,
        session: Session | None = None,
    ) -> TicketOperationView | None:
        """Enqueues an asynchronous resolve_ticket operation if a linked ticket exists.

        Deep module invariant:
        - If ticketing is disabled or provider is not configured, returns None (fail-safe no-op).
        - If no linked ticket exists for this case, returns None (fail-safe no-op).
        - Validates that case is resolved or mitigated.
        - Enqueues operation with deterministic idempotency key based on resolution payload.
        - When an existing session is provided, enqueues within that session's transaction without committing,
          ensuring transactional atomicity with the caller's persistence boundary.
        """
        provider_name = provider or self.config.active_provider
        if not self.config.enabled:
            return None

        provider_obj = self.providers.get(provider_name)
        if not provider_obj or not getattr(provider_obj, "is_configured", True):
            return None

        if session is not None:
            return self._enqueue_resolve_in_session(session, case_id, provider_name, should_commit=False)

        with self._session_factory() as local_session:
            return self._enqueue_resolve_in_session(local_session, case_id, provider_name, should_commit=True)

    def _enqueue_resolve_in_session(
        self,
        session: Session,
        case_id: int,
        provider_name: str,
        should_commit: bool,
    ) -> TicketOperationView | None:
        # 1. Check if an active link exists for this case and provider
        link = (
            session.query(CaseTicketLinkEntity)
            .filter_by(case_id=case_id, provider=provider_name)
            .first()
        )
        if not link:
            return None

        # 2. Check if case exists
        case = session.query(OperationalCaseEntity).filter_by(id=case_id).first()
        if not case:
            return None

        if case.outcome_status not in {"resolved", "mitigated"}:
            raise TicketingError(
                f"Cannot resolve ticket: case #{case_id} status is '{case.outcome_status}', "
                "expected 'resolved' or 'mitigated'"
            )

        # 3. Deterministic idempotency key based on resolution state
        content_bytes = (
            f"{case.outcome_status}:{case.outcome_summary or ''}:"
            f"{case.corrective_action or ''}:{case.root_cause_summary or ''}"
        ).encode("utf-8")
        content_hash = hashlib.sha256(content_bytes).hexdigest()[:12]
        idem_key = f"resolve_{case_id}_{content_hash}"

        # 4. Check for existing operation with this idempotency key
        existing_op = (
            session.query(TicketOperationEntity)
            .filter_by(provider=provider_name, idempotency_key=idem_key)
            .first()
        )
        if existing_op:
            if existing_op.status == "failed":
                now = datetime.now(timezone.utc)
                existing_op.status = "pending"
                existing_op.attempts = 0
                existing_op.available_at = now
                existing_op.error_message = None
                existing_op.lease_token = None
                existing_op.lease_expires_at = None
                existing_op.updated_at = now
                if should_commit:
                    session.commit()
                    session.refresh(existing_op)
                else:
                    session.flush()
            return self._to_operation_view(existing_op)

        now = datetime.now(timezone.utc)
        op = TicketOperationEntity(
            id=f"op_{uuid4().hex[:16]}",
            case_id=case_id,
            provider=provider_name,
            operation_type="resolve_ticket",
            idempotency_key=idem_key,
            status="pending",
            attempts=0,
            max_attempts=self.config.outbox_max_attempts,
            available_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(op)
        if should_commit:
            session.commit()
            session.refresh(op)
        else:
            session.flush()
        return self._to_operation_view(op)

    def retry_operation(self, operation_id: str) -> TicketOperationView:
        """Reopens a failed or ambiguous operation for execution."""
        with self._session_factory() as session:
            op = session.query(TicketOperationEntity).filter_by(id=operation_id).first()
            if not op:
                raise TicketingError(f"Operation not found: {operation_id}")
            now = datetime.now(timezone.utc)
            op.status = "pending"
            op.attempts = 0
            op.available_at = now
            op.error_message = None
            op.lease_token = None
            op.lease_expires_at = None
            op.updated_at = now
            session.commit()
            session.refresh(op)
            return self._to_operation_view(op)

    def force_create_ticket(self, case_id: int, operation_id: str) -> TicketOperationView:
        """Supersedes an ambiguous operation and enqueues a fresh create_ticket operation."""
        with self._session_factory() as session:
            prior_op = session.query(TicketOperationEntity).filter_by(id=operation_id).first()
            if not prior_op:
                raise TicketingError(f"Prior operation not found: {operation_id}")
            now = datetime.now(timezone.utc)
            prior_op.status = "superseded"
            prior_op.updated_at = now

            new_op = TicketOperationEntity(
                id=f"op_{uuid4().hex[:16]}",
                case_id=case_id,
                provider=prior_op.provider,
                operation_type="create_ticket",
                idempotency_key=f"force_create_{uuid4().hex[:12]}",
                status="pending",
                attempts=0,
                max_attempts=self.config.outbox_max_attempts,
                available_at=now,
                supersedes_operation_id=prior_op.id,
                created_at=now,
                updated_at=now,
            )
            session.add(new_op)
            session.commit()
            session.refresh(new_op)
            return self._to_operation_view(new_op)

    def link_existing_ticket(self, case_id: int, provider: str, display_key: str) -> TicketView:
        """Manually links an existing remote ticket to the case."""
        provider_obj = self._get_provider(provider)
        snapshot = provider_obj.pull_remote_ticket(
            remote_id=display_key, display_key=display_key, cursor=None
        )

        with self._session_factory() as session:
            now = datetime.now(timezone.utc)
            link = (
                session.query(CaseTicketLinkEntity)
                .filter_by(case_id=case_id, provider=provider)
                .first()
            )
            ticket_url = f"{getattr(provider_obj, 'base_url', '')}/browse/{display_key}"
            if link:
                link.remote_id = snapshot.remote_id
                link.display_key = snapshot.display_key
                link.ticket_url = ticket_url
                link.observed_remote_status = snapshot.remote_status
                link.last_synced_at = now
                link.updated_at = now
            else:
                link = CaseTicketLinkEntity(
                    case_id=case_id,
                    provider=provider,
                    remote_id=snapshot.remote_id,
                    display_key=snapshot.display_key,
                    ticket_url=ticket_url,
                    observed_remote_status=snapshot.remote_status,
                    last_synced_at=now,
                    created_at=now,
                    updated_at=now,
                )
                session.add(link)

            # Record event
            event = CaseTicketEventEntity(
                case_id=case_id,
                provider=provider,
                remote_event_id=f"manual_link_{uuid4().hex[:10]}",
                event_type="ticket_linked",
                author="operator",
                summary=f"Manually linked external ticket {display_key} ({snapshot.remote_status})",
                payload={"display_key": display_key, "remote_id": snapshot.remote_id},
                occurred_at=now,
                created_at=now,
            )
            session.add(event)
            session.commit()
            session.refresh(link)
            return self._to_ticket_view(link)

    def resolve_ambiguity(
        self, case_id: int, request: AmbiguousResolutionRequest
    ) -> TicketView | TicketOperationView | dict[str, Any]:
        """Handles operator choices for ambiguous outcome operations."""
        provider_name = self.config.active_provider

        with self._session_factory() as session:
            ambiguous_op = (
                session.query(TicketOperationEntity)
                .filter_by(
                    case_id=case_id,
                    provider=provider_name,
                    operation_type="create_ticket",
                    status="ambiguous_outcome",
                )
                .order_by(TicketOperationEntity.created_at.desc())
                .first()
            )
            if not ambiguous_op:
                raise TicketingError(f"No ambiguous create operation found for case {case_id}")
            op_id = ambiguous_op.id

        if request.action == "check_again":
            # Strictly read-only search: do NOT create an issue if not found!
            provider_obj = self._get_provider(provider_name)
            if hasattr(provider_obj, "reconcile_only"):
                result = provider_obj.reconcile_only(op_id, case_id)
            else:
                case_draft = self._build_ticket_draft(case_id)
                result = provider_obj.reconcile_or_create(case_draft, op_id)

            if not result:
                with self._session_factory() as session:
                    op = session.query(TicketOperationEntity).filter_by(id=op_id).first()
                    if op:
                        op.error_message = (
                            "Reconciliation did not find a matching Jira issue for this operation. "
                            "Wait a moment for Jira indexing or choose Force Create New."
                        )
                        op.updated_at = datetime.now(timezone.utc)
                        session.commit()
                return {
                    "status": "not_found",
                    "operation_id": op_id,
                    "message": "No matching Jira issue found yet. The issue may still be indexing, or you can force-create a new ticket.",
                }

            with self._session_factory() as session:
                now = datetime.now(timezone.utc)
                # Atomically complete operation and store link
                op = session.query(TicketOperationEntity).filter_by(id=op_id).first()
                if op:
                    op.status = "completed"
                    op.updated_at = now
                link = (
                    session.query(CaseTicketLinkEntity)
                    .filter_by(case_id=case_id, provider=provider_name)
                    .first()
                )
                if not link:
                    link = CaseTicketLinkEntity(
                        case_id=case_id,
                        provider=provider_name,
                        remote_id=result.remote_id,
                        display_key=result.display_key,
                        ticket_url=result.ticket_url,
                        observed_remote_status=result.initial_status,
                        last_synced_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(link)
                session.commit()
                session.refresh(link)
                return self._to_ticket_view(link)

        elif request.action == "link_existing":
            if not request.remote_key:
                raise TicketingError("remote_key is required when action is link_existing")
            link_view = self.link_existing_ticket(case_id, provider_name, request.remote_key)
            with self._session_factory() as session:
                op = session.query(TicketOperationEntity).filter_by(id=op_id).first()
                if op:
                    op.status = "completed"
                    op.updated_at = datetime.now(timezone.utc)
                    session.commit()
            return link_view

        elif request.action == "force_create_new":
            return self.force_create_ticket(case_id, op_id)

        raise TicketingError(f"Unsupported ambiguity resolution action: {request.action}")

    def get_ticket_view(self, case_id: int, provider: str | None = None) -> TicketView | None:
        """Retrieves active link for a case."""
        provider_name = provider or self.config.active_provider
        with self._session_factory() as session:
            link = (
                session.query(CaseTicketLinkEntity)
                .filter_by(case_id=case_id, provider=provider_name)
                .first()
            )
            return self._to_ticket_view(link) if link else None

    def get_operation_view(self, operation_id: str) -> TicketOperationView | None:
        """Retrieves an operation by ID."""
        with self._session_factory() as session:
            op = session.query(TicketOperationEntity).filter_by(id=operation_id).first()
            return self._to_operation_view(op) if op else None

    def list_ticket_events(self, case_id: int, limit: int = 50) -> list[TicketEventView]:
        """Retrieves external activity timeline events."""
        with self._session_factory() as session:
            events = (
                session.query(CaseTicketEventEntity)
                .filter_by(case_id=case_id)
                .order_by(CaseTicketEventEntity.occurred_at.desc())
                .limit(limit)
                .all()
            )
            return [
                TicketEventView(
                    id=e.id,
                    case_id=e.case_id,
                    provider=e.provider,
                    remote_event_id=e.remote_event_id,
                    event_type=e.event_type,
                    author=e.author,
                    summary=e.summary,
                    occurred_at=e.occurred_at,
                    created_at=e.created_at,
                    promoted_to_note=bool(e.payload and e.payload.get("promoted_at")),
                    auto_promoted=bool(e.payload and e.payload.get("auto_promoted")),
                )
                for e in events
            ]

    @staticmethod
    def _format_promoted_note(event: CaseTicketEventEntity, auto_promoted: bool) -> str:
        provider = (event.provider or "ticket").upper()
        author = event.author or "Team"
        clue_or_note = "clue" if auto_promoted else "note"
        tag = " (AI auto-promoted)" if auto_promoted else ""
        return f"[{provider} {clue_or_note} from {author}{tag}]: {event.summary}"

    def promote_event_to_case_note(
        self,
        case_id: int,
        event_id: int,
        auto_promoted: bool = False,
    ) -> CaseNotePromoteResult:
        """Promotes an external ticket event (comment) into an operational investigation note.

        Invariants enforced:
        - Event must exist and belong to case_id.
        - Event must be a comment event (event_type in ('comment_added', 'comment')).
        - Idempotent: If already promoted, returns success without duplicating notes.
        - Advances case.investigation_status from 'not_started' to 'in_progress'.
        - Updates case.updated_at.
        - Marks event.payload['promoted_at'] with ISO timestamp.
        - Marks event.payload['auto_promoted'] = True if auto_promoted.
        """
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            event = (
                session.query(CaseTicketEventEntity)
                .filter_by(id=event_id, case_id=case_id)
                .first()
            )
            if not event:
                raise TicketNotFoundError(f"Ticket event #{event_id} not found for case #{case_id}")

            if event.event_type not in ("comment_added", "comment"):
                raise TicketingError(f"Event #{event_id} of type '{event.event_type}' is not a comment and cannot be promoted to a note")

            case = session.query(OperationalCaseEntity).filter_by(id=case_id).first()
            if not case:
                raise TicketNotFoundError(f"Case #{case_id} not found")

            payload = dict(event.payload or {})
            if payload.get("promoted_at"):
                # Idempotent: already promoted
                is_auto = bool(payload.get("auto_promoted"))
                default_note = self._format_promoted_note(event, is_auto)
                formatted_note = payload.get("promoted_note") or default_note
                return CaseNotePromoteResult(
                    success=True,
                    case_id=case_id,
                    event_id=event_id,
                    note=formatted_note,
                    investigation_status=case.investigation_status,
                    already_promoted=True,
                    auto_promoted=is_auto,
                )

            # Format the note with clear provenance
            formatted_note = self._format_promoted_note(event, auto_promoted)

            notes = list(case.investigation_notes or [])
            note_entry = {
                "timestamp": now.isoformat(),
                "note": formatted_note,
                "source": "ticketing",
                "provider": event.provider,
                "author": event.author,
            }
            if auto_promoted:
                note_entry["auto_promoted"] = True
            notes.append(note_entry)
            case.investigation_notes = notes

            if case.investigation_status == "not_started":
                case.investigation_status = "in_progress"

            # If case was already indexed in operational memory, mark it stale so vector search refreshes
            if case.memory_status == "indexed":
                case.memory_status = "stale"

            case.updated_at = now

            payload["promoted_at"] = now.isoformat()
            payload["promoted_note"] = formatted_note
            if auto_promoted:
                payload["auto_promoted"] = True
            event.payload = payload

            session.commit()

            return CaseNotePromoteResult(
                success=True,
                case_id=case_id,
                event_id=event_id,
                note=formatted_note,
                investigation_status=case.investigation_status,
                already_promoted=False,
                auto_promoted=auto_promoted,
            )

    def triage_comments(
        self,
        case_id: int,
        ai_services: OptionalAIServices | None = None,
    ) -> CommentTriageResult:
        """Evaluates unpromoted external ticket comments against case telemetry and automatically
        promotes high-confidence operational clues into investigation notes.

        Never crashes: if AI services are unavailable or errors occur, returns a graceful
        CommentTriageResult with 0 promotions.
        """
        with self._session_factory() as session:
            case = session.query(OperationalCaseEntity).filter_by(id=case_id).first()
            if not case:
                raise TicketNotFoundError(f"Case #{case_id} not found")

            effective_ai = self._get_ai_services(ai_services)
            if not effective_ai:
                return CommentTriageResult(
                    case_id=case_id,
                    evaluated_count=0,
                    promoted_count=0,
                    promoted_notes=[],
                )

            snapshot = case.finding_snapshot or {}
            case_context = CaseTriageContext(
                case_title=case.case_title,
                service=snapshot.get("service", "unknown"),
                metric_name=snapshot.get("metric_name", "unknown"),
                summary=snapshot.get("summary", ""),
            )

            # Fetch all comment events for this case in chronological order
            events = (
                session.query(CaseTicketEventEntity)
                .filter(
                    CaseTicketEventEntity.case_id == case_id,
                    CaseTicketEventEntity.event_type.in_(["comment_added", "comment"]),
                )
                .order_by(CaseTicketEventEntity.occurred_at.asc())
                .all()
            )

            # Filter to unpromoted and untriaged comments
            unpromoted_events = [
                (e.id, e.author, e.summary)
                for e in events
                if not (e.payload and (e.payload.get("promoted_at") or e.payload.get("triaged_at")))
            ]

        if not unpromoted_events:
            return CommentTriageResult(
                case_id=case_id,
                evaluated_count=0,
                promoted_count=0,
                promoted_notes=[],
            )

        promoted_notes: list[str] = []
        evaluated_count = 0
        for event_id, author, summary in unpromoted_events:
            if not summary or not summary.strip():
                continue
            evaluated_count += 1
            evaluation = self._triage_service.evaluate(
                effective_ai,
                case_context=case_context,
                author=author,
                comment_body=summary,
            )
            if self._triage_service.is_promotable(evaluation):
                res = self.promote_event_to_case_note(
                    case_id=case_id,
                    event_id=event_id,
                    auto_promoted=True,
                )
                promoted_notes.append(res.note)
            elif evaluation is not None:
                self._mark_event_triaged(event_id, evaluation)

        return CommentTriageResult(
            case_id=case_id,
            evaluated_count=evaluated_count,
            promoted_count=len(promoted_notes),
            promoted_notes=promoted_notes,
        )

    def _mark_event_triaged(
        self,
        event_id: int,
        evaluation: CommentTriageEvaluation,
    ) -> None:
        """Records triage evaluation results on an event so it is not re-evaluated on subsequent runs."""
        with self._session_factory() as session:
            ev = session.query(CaseTicketEventEntity).filter_by(id=event_id).first()
            if ev:
                payload = dict(ev.payload or {})
                payload["triaged_at"] = datetime.now(timezone.utc).isoformat()
                payload["triage_evaluation"] = evaluation.model_dump()
                ev.payload = payload
                session.commit()

    def _trigger_auto_triage(self, case_id: int, trigger_context: str) -> None:
        """Triggers automatic comment triage in a fail-safe block without breaking the calling flow."""
        try:
            self.triage_comments(case_id)
        except Exception as triage_exc:
            logger.warning(
                "Automatic comment triage failed during %s for case %s: %s",
                trigger_context,
                case_id,
                triage_exc,
            )

    def get_external_comments_for_analysis(
        self, case_id: int, limit: int = 10, unpromoted_only: bool = True
    ) -> list[str]:
        """Returns condensed external team comments for an operational case, suitable for LLM analysis.

        If unpromoted_only is True (default), comments that have already been promoted into
        case.investigation_notes are omitted to prevent redundant prompt duplication.
        Fetches the most recent comments and orders them chronologically to avoid starvation.
        """
        with self._session_factory() as session:
            query = (
                session.query(CaseTicketEventEntity)
                .filter(
                    CaseTicketEventEntity.case_id == case_id,
                    CaseTicketEventEntity.event_type.in_(["comment_added", "comment"]),
                )
                .order_by(CaseTicketEventEntity.occurred_at.desc())
            )
            if not unpromoted_only:
                events = query.limit(limit).all()
            else:
                events = query.limit(500).all()

            snippets: list[str] = []
            for ev in events:
                if unpromoted_only and ev.payload and ev.payload.get("promoted_at"):
                    continue
                summary = (ev.summary or "").strip()
                if summary:
                    author = ev.author or "Team member"
                    snippets.append(f"- [{author}]: {summary}")
                if len(snippets) >= limit:
                    break

            snippets.reverse()
            return snippets

    def sweep_expired_creates(self) -> int:
        """Sweeps in-flight create operations with expired leases directly to ambiguous_outcome."""
        now = datetime.now(timezone.utc)
        swept = 0
        with self._session_factory() as session:
            expired_creates = (
                session.query(TicketOperationEntity)
                .filter(
                    TicketOperationEntity.operation_type == "create_ticket",
                    TicketOperationEntity.status == "processing",
                    TicketOperationEntity.lease_expires_at < now,
                )
                .all()
            )
            for op in expired_creates:
                op.status = "ambiguous_outcome"
                op.error_message = (
                    "Worker lease expired during ticket creation. Remote outcome is uncertain."
                )
                op.lease_token = None
                op.updated_at = now
                swept += 1
            if swept > 0:
                session.commit()
                logger.warning("Swept %d expired in-flight create operations to ambiguous_outcome", swept)
        return swept

    def process_pending_operations(self, limit: int = 10) -> int:
        """Claims and executes pending/failed operations and expired sync operations."""
        now = datetime.now(timezone.utc)
        lease_seconds = self.config.outbox_lease_seconds
        expires_at = now + timedelta(seconds=lease_seconds)

        claimed_ops: list[tuple[str, str, int, str, str]] = []

        # 1. Claim batch
        with self._session_factory() as session:
            # Reclaim condition:
            # - status == pending and available_at <= now
            # - status == failed and attempts < max_attempts and available_at <= now
            # - status == processing and operation_type == sync_ticket and lease_expires_at < now
            eligible = (
                session.query(TicketOperationEntity)
                .filter(
                    or_(
                        (TicketOperationEntity.status == "pending") & (TicketOperationEntity.available_at <= now),
                        (TicketOperationEntity.status == "failed")
                        & (TicketOperationEntity.attempts < TicketOperationEntity.max_attempts)
                        & (TicketOperationEntity.available_at <= now),
                        (TicketOperationEntity.status == "processing")
                        & (TicketOperationEntity.operation_type.in_(["sync_ticket", "resolve_ticket"]))
                        & (TicketOperationEntity.lease_expires_at < now),
                    )
                )
                .order_by(TicketOperationEntity.available_at.asc())
                .limit(limit)
                .all()
            )

            for op in eligible:
                token = uuid4().hex
                op.status = "processing"
                op.lease_token = token
                op.lease_expires_at = expires_at
                op.attempts += 1
                op.updated_at = now
                claimed_ops.append((op.id, token, op.case_id, op.provider, op.operation_type))

            if claimed_ops:
                session.commit()

        # 2. Execute claimed operations
        for op_id, lease_token, case_id, provider_name, op_type in claimed_ops:
            try:
                self._execute_one_operation(op_id, lease_token, case_id, provider_name, op_type)
            except Exception:
                logger.exception("Failed processing operation %s", op_id)

        return len(claimed_ops)

    def _execute_one_operation(
        self, op_id: str, lease_token: str, case_id: int, provider_name: str, op_type: str
    ) -> None:
        provider = self.providers.get(provider_name)
        if not provider or not getattr(provider, "is_configured", True):
            self._fail_operation(op_id, lease_token, f"Provider {provider_name} is not configured")
            return

        if op_type == "create_ticket":
            self._execute_create_operation(op_id, lease_token, case_id, provider)
        elif op_type == "sync_ticket":
            self._execute_sync_operation(op_id, lease_token, case_id, provider_name, provider)
        elif op_type == "resolve_ticket":
            self._execute_resolve_operation(op_id, lease_token, case_id, provider_name, provider)

    def _complete_operation_under_lease(
        self,
        session: Session,
        op_id: str,
        lease_token: str,
        now: datetime,
    ) -> TicketOperationEntity:
        """Verifies lease ownership and transitions operation to completed status."""
        op = (
            session.query(TicketOperationEntity)
            .filter(
                TicketOperationEntity.id == op_id,
                TicketOperationEntity.lease_token == lease_token,
                TicketOperationEntity.status == "processing",
                TicketOperationEntity.lease_expires_at > now,
            )
            .first()
        )
        if not op:
            session.rollback()
            raise LeaseLostError(f"Lease lost for operation {op_id}")

        op.status = "completed"
        op.lease_token = None
        op.lease_expires_at = None
        op.updated_at = now
        return op

    def _execute_create_operation(
        self, op_id: str, lease_token: str, case_id: int, provider: Any
    ) -> None:
        try:
            draft = self._build_ticket_draft(case_id)
            result = provider.reconcile_or_create(draft, op_id)

            # Single atomic completion transaction
            with self._session_factory() as session:
                now = datetime.now(timezone.utc)
                op = self._complete_operation_under_lease(session, op_id, lease_token, now)

                # Upsert link
                link = (
                    session.query(CaseTicketLinkEntity)
                    .filter_by(case_id=case_id, provider=op.provider)
                    .first()
                )
                if link:
                    link.remote_id = result.remote_id
                    link.display_key = result.display_key
                    link.ticket_url = result.ticket_url
                    link.observed_remote_status = result.initial_status
                    link.last_synced_at = now
                    link.updated_at = now
                else:
                    link = CaseTicketLinkEntity(
                        case_id=case_id,
                        provider=op.provider,
                        remote_id=result.remote_id,
                        display_key=result.display_key,
                        ticket_url=result.ticket_url,
                        observed_remote_status=result.initial_status,
                        last_synced_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(link)

                # Append event
                event = CaseTicketEventEntity(
                    case_id=case_id,
                    provider=op.provider,
                    remote_event_id=f"create_{result.remote_id}",
                    event_type="ticket_created",
                    author="system",
                    summary=f"Created external ticket {result.display_key} ({result.initial_status})",
                    payload={"remote_id": result.remote_id, "display_key": result.display_key},
                    occurred_at=now,
                    created_at=now,
                )
                session.add(event)
                session.commit()
                logger.info("Operation %s completed and linked to %s", op_id, result.display_key)

        except AmbiguousOutcomeError as e:
            logger.warning("Operation %s encountered ambiguous outcome: %s", op_id, e)
            with self._session_factory() as session:
                op = (
                    session.query(TicketOperationEntity)
                    .filter(
                        TicketOperationEntity.id == op_id,
                        TicketOperationEntity.lease_token == lease_token,
                        TicketOperationEntity.status == "processing",
                    )
                    .first()
                )
                if op:
                    op.status = "ambiguous_outcome"
                    op.error_message = str(e)
                    op.lease_token = None
                    op.lease_expires_at = None
                    op.updated_at = datetime.now(timezone.utc)
                    session.commit()
        except LeaseLostError:
            logger.warning("Operation %s lease was lost; skipping completion commit", op_id)
        except Exception as e:
            logger.exception("Operation %s failed with non-ambiguous error", op_id)
            self._fail_operation(op_id, lease_token, str(e))

    def _execute_sync_operation(
        self, op_id: str, lease_token: str, case_id: int, provider_name: str, provider: Any
    ) -> None:
        try:
            with self._session_factory() as session:
                link = (
                    session.query(CaseTicketLinkEntity)
                    .filter_by(case_id=case_id, provider=provider_name)
                    .first()
                )
                if not link:
                    self._fail_operation(op_id, lease_token, "No ticket link found for case")
                    return
                remote_id = link.remote_id
                display_key = link.display_key
                cursor = link.sync_cursor

            snapshot = provider.pull_remote_ticket(remote_id, display_key, cursor)

            with self._session_factory() as session:
                now = datetime.now(timezone.utc)
                op = (
                    session.query(TicketOperationEntity)
                    .filter(
                        TicketOperationEntity.id == op_id,
                        TicketOperationEntity.lease_token == lease_token,
                        TicketOperationEntity.status == "processing",
                        TicketOperationEntity.lease_expires_at > now,
                    )
                    .first()
                )
                if not op:
                    session.rollback()
                    raise LeaseLostError(f"Lease lost for sync op {op_id}")

                op.status = "completed"
                op.lease_token = None
                op.lease_expires_at = None
                op.updated_at = now

                link = session.query(CaseTicketLinkEntity).filter_by(case_id=case_id, provider=provider_name).first()
                if link:
                    link.observed_remote_status = snapshot.remote_status
                    link.sync_cursor = snapshot.cursor
                    link.last_synced_at = now
                    link.updated_at = now

                # Ingest comments as events
                new_comments_count = 0
                for c in snapshot.comments:
                    ev_id = f"comment_{c.get('id')}"
                    exists = session.query(CaseTicketEventEntity).filter_by(provider=provider_name, remote_event_id=ev_id).first()
                    if not exists:
                        session.add(
                            CaseTicketEventEntity(
                                case_id=case_id,
                                provider=provider_name,
                                remote_event_id=ev_id,
                                event_type="comment_added",
                                author=c.get("author"),
                                summary=c.get("body", ""),
                                payload=c,
                                occurred_at=now,
                                created_at=now,
                            )
                        )
                        new_comments_count += 1
                session.commit()

            if new_comments_count > 0:
                self._trigger_auto_triage(case_id, "ticket sync")
        except AmbiguousOutcomeError as e:
            self._fail_operation(op_id, lease_token, str(e))
        except LeaseLostError:
            pass
        except Exception as e:
            self._fail_operation(op_id, lease_token, str(e))

    def _execute_resolve_operation(
        self, op_id: str, lease_token: str, case_id: int, provider_name: str, provider: Any
    ) -> None:
        try:
            with self._session_factory() as session:
                link = (
                    session.query(CaseTicketLinkEntity)
                    .filter_by(case_id=case_id, provider=provider_name)
                    .first()
                )
                if not link:
                    self._fail_operation(op_id, lease_token, "No ticket link found for case")
                    return

                case = session.query(OperationalCaseEntity).filter_by(id=case_id).first()
                if not case:
                    self._fail_operation(op_id, lease_token, "Case not found")
                    return

                remote_id = link.remote_id
                display_key = link.display_key
                ui_base = os.getenv("OPS_SIGNALS_UI_BASE_URL", "http://localhost:3000").rstrip("/")
                resolution = TicketResolutionDraft(
                    case_id=case.id,
                    display_key=link.display_key,
                    root_cause_summary=case.root_cause_summary,
                    root_cause_verified=case.root_cause_verified,
                    corrective_action=case.corrective_action,
                    outcome_status=case.outcome_status or "resolved",
                    outcome_summary=case.outcome_summary,
                    deep_link_url=f"{ui_base}/cases/{case.id}",
                )

            if not hasattr(provider, "resolve_ticket"):
                self._fail_operation(op_id, lease_token, f"Provider {provider_name} does not support resolving tickets")
                return

            result: TicketResolutionResult = provider.resolve_ticket(
                remote_id=remote_id,
                display_key=display_key,
                resolution=resolution,
            )

            with self._session_factory() as session:
                now = datetime.now(timezone.utc)
                op = self._complete_operation_under_lease(session, op_id, lease_token, now)

                link = (
                    session.query(CaseTicketLinkEntity)
                    .filter_by(case_id=case_id, provider=provider_name)
                    .first()
                )
                if link:
                    if result.transitioned_to:
                        link.observed_remote_status = result.transitioned_to
                    link.last_synced_at = now
                    link.updated_at = now

                summary_text = f"Posted case resolution to {result.display_key}"
                if result.transitioned_to:
                    summary_text += f" (transitioned to {result.transitioned_to})"

                event = CaseTicketEventEntity(
                    case_id=case_id,
                    provider=provider_name,
                    remote_event_id=f"resolve_{result.remote_id}_{uuid4().hex[:8]}",
                    event_type="resolution_posted",
                    author="system",
                    summary=summary_text,
                    payload={
                        "remote_id": result.remote_id,
                        "display_key": result.display_key,
                        "comment_id": result.comment_id,
                        "transitioned_to": result.transitioned_to,
                    },
                    occurred_at=now,
                    created_at=now,
                )
                session.add(event)
                session.commit()
                logger.info("Resolve operation %s completed for %s", op_id, result.display_key)

        except AmbiguousOutcomeError as e:
            self._fail_operation(op_id, lease_token, str(e))
        except LeaseLostError:
            pass
        except Exception as e:
            self._fail_operation(op_id, lease_token, str(e))

    def _fail_operation(self, op_id: str, lease_token: str, error_message: str) -> None:
        with self._session_factory() as session:
            op = (
                session.query(TicketOperationEntity)
                .filter(
                    TicketOperationEntity.id == op_id,
                    TicketOperationEntity.lease_token == lease_token,
                    TicketOperationEntity.status == "processing",
                )
                .first()
            )
            if op:
                now = datetime.now(timezone.utc)
                op.status = "failed"
                op.error_message = error_message
                # Exponential backoff
                backoff_seconds = min(300, 5 * (2 ** op.attempts))
                op.available_at = now + timedelta(seconds=backoff_seconds)
                op.lease_token = None
                op.lease_expires_at = None
                op.updated_at = now
                session.commit()

    def accept_webhook(
        self, provider_name: str, raw_body: bytes, headers: Mapping[str, str]
    ) -> tuple[int, dict[str, Any]]:
        """Handles an inbound webhook with signature verification and atomic database commit."""
        provider = self.providers.get(provider_name)
        if not provider or not getattr(provider, "is_configured", True):
            return (400, {"error": f"Provider {provider_name} is not configured"})

        # The webhook route is exempt from the API token, so the signature is the only proof the
        # request came from the provider. Without a secret there is nothing to check: refuse rather
        # than accept unsigned comments, which can reach case notes and AI drafts.
        secret = getattr(provider.config, "webhook_secret", None)
        if not secret or not secret.strip():
            return (401, {"error": f"Webhook secret is not configured for {provider_name}; unsigned webhooks are refused"})
        if not provider.verify_signature(raw_body, headers, secret):
            return (401, {"error": "Invalid webhook cryptographic signature"})

        delivery_id = provider.extract_delivery_id(headers) or f"del_{uuid4().hex}"
        event_draft: RemoteEventDraft | None = provider.parse_webhook_event(raw_body, headers)
        if not event_draft:
            return (200, {"status": "ignored", "reason": "unsupported_event"})

        with self._session_factory() as session:
            now = datetime.now(timezone.utc)
            # Deduplicate delivery
            existing_del = (
                session.query(TicketWebhookDeliveryEntity)
                .filter_by(provider=provider_name, delivery_id=delivery_id)
                .first()
            )
            if existing_del:
                return (200, {"status": "duplicate_ignored"})

            session.add(
                TicketWebhookDeliveryEntity(
                    provider=provider_name, delivery_id=delivery_id, processed_at=now
                )
            )

            # Resolve case by link (match on remote_id or display_key)
            link = (
                session.query(CaseTicketLinkEntity)
                .filter(
                    CaseTicketLinkEntity.provider == provider_name,
                    or_(
                        CaseTicketLinkEntity.remote_id == event_draft.remote_id,
                        CaseTicketLinkEntity.display_key == event_draft.display_key,
                    ),
                )
                .first()
            )
            if not link:
                session.commit()
                return (200, {"status": "unlinked_ticket_acknowledged", "remote_id": event_draft.remote_id})

            new_comment_added = False
            # Check if event already exists
            existing_event = (
                session.query(CaseTicketEventEntity)
                .filter_by(provider=provider_name, remote_event_id=event_draft.remote_event_id)
                .first()
            )
            if not existing_event:
                event = CaseTicketEventEntity(
                    case_id=link.case_id,
                    provider=provider_name,
                    remote_event_id=event_draft.remote_event_id,
                    event_type=event_draft.event_type,
                    author=event_draft.author,
                    summary=event_draft.summary,
                    payload=event_draft.payload,
                    occurred_at=event_draft.occurred_at,
                    created_at=now,
                )
                session.add(event)
                if event_draft.event_type in ("comment", "comment_added"):
                    new_comment_added = True

            if event_draft.observed_remote_status:
                link.observed_remote_status = event_draft.observed_remote_status
                link.last_synced_at = now
                link.updated_at = now

            case_id = link.case_id
            session.commit()

            if new_comment_added:
                self._trigger_auto_triage(case_id, "webhook processing")

            return (200, {"status": "processed", "case_id": case_id})

    def get_webhook_info(self, provider: str = "jira") -> WebhookInfoView:
        """Returns configuration details and delivery metrics for the incoming webhook."""
        provider_obj = self.providers.get(provider)
        secret = getattr(getattr(provider_obj, "config", None), "webhook_secret", None) if provider_obj else None
        is_secret_configured = bool(secret and secret.strip())

        with self._session_factory() as session:
            deliveries_count = (
                session.query(TicketWebhookDeliveryEntity)
                .filter_by(provider=provider)
                .count()
            )
            last_delivery = (
                session.query(TicketWebhookDeliveryEntity)
                .filter_by(provider=provider)
                .order_by(TicketWebhookDeliveryEntity.processed_at.desc())
                .first()
            )
            last_delivery_at = last_delivery.processed_at if last_delivery else None

        webhook_base = (
            os.getenv("OPS_SIGNALS_WEBHOOK_BASE_URL")
            or os.getenv("OPS_SIGNALS_BASE_URL")
            or os.getenv("OPS_SIGNALS_API_BASE_URL")
            or ""
        ).rstrip("/")
        webhook_url = (
            f"{webhook_base}/api/integrations/ticketing/{provider}/webhook"
            if webhook_base
            else f"/api/integrations/ticketing/{provider}/webhook"
        )

        return WebhookInfoView(
            provider=provider,
            webhook_url=webhook_url,
            is_secret_configured=is_secret_configured,
            deliveries_count=deliveries_count,
            last_delivery_at=last_delivery_at,
        )

    def _build_ticket_draft(self, case_id: int) -> TicketDraft:
        with self._session_factory() as session:
            case = session.query(OperationalCaseEntity).filter_by(id=case_id).first()
            if not case:
                raise TicketingError(f"Case {case_id} not found")

            finding_snapshot = case.finding_snapshot or {}
            service = finding_snapshot.get("service") or "unknown-service"
            metric = finding_snapshot.get("metric_name") or "unknown-metric"
            health_status = finding_snapshot.get("health_status") or "warning"
            importance = float(finding_snapshot.get("importance_score") or 0.5)

            ui_base = os.getenv("OPS_SIGNALS_UI_BASE_URL", "http://localhost:3000").rstrip("/")
            return TicketDraft(
                case_id=case.id,
                case_title=case.case_title,
                summary=finding_snapshot.get("summary") or case.case_title,
                service=service,
                metric_name=metric,
                health_status=health_status,
                importance_score=importance,
                analysis_run_id=case.analysis_run_id,
                rca_summary=case.root_cause_summary,
                outcome_summary=case.outcome_summary,
                deep_link_url=f"{ui_base}/cases/{case.id}",
                raw_findings=[finding_snapshot],
            )

    @staticmethod
    def _to_operation_view(op: TicketOperationEntity) -> TicketOperationView:
        return TicketOperationView(
            operation_id=op.id,
            case_id=op.case_id,
            provider=op.provider,
            operation_type=op.operation_type,
            status=op.status,
            attempts=op.attempts,
            last_error=op.error_message,
            created_at=op.created_at,
            updated_at=op.updated_at,
        )

    @staticmethod
    def _to_ticket_view(link: CaseTicketLinkEntity) -> TicketView:
        return TicketView(
            case_id=link.case_id,
            provider=link.provider,
            remote_id=link.remote_id,
            display_key=link.display_key,
            ticket_url=link.ticket_url,
            observed_remote_status=link.observed_remote_status,
            last_synced_at=link.last_synced_at,
            sync_status="synced",
        )
