"""A case's timeline for the Publish Knowledge tab, built from what the case holds: the deploy matched
to its finding, the finding, the case opening, the linked ticket, notes, ticket comments and the
resolution. No AI: it shows the same with AI off, and the write-up draft reads it as facts.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.alerts.correlation import as_utc
from backend.app.config import AlertEnrichmentConfig
from backend.app.models.entities import CaseTicketEventEntity, CaseTicketLinkEntity, FindingEntity, OperationalCaseEntity
from backend.app.services.finding_changes import finding_changes
from backend.app.services.finding_plain import finding_plain

logger = logging.getLogger(__name__)

_COMMENT_TYPES = ("comment_added", "comment")
_CLOSED_LABELS = {"resolved": "Resolved", "mitigated": "Mitigated", "won_t_fix": "Closed as won't fix", "escalated": "Escalated"}


def case_timeline(case: OperationalCaseEntity, db: Session, change_config: AlertEnrichmentConfig | None) -> dict[str, Any]:
    """{"events": [{time, kind, text, who}], "time_to_fix_minutes"}: events oldest first."""
    events: list[dict[str, Any]] = []
    snapshot = case.finding_snapshot or {}
    finding = db.get(FindingEntity, case.finding_id) if case.finding_id else None

    started = None
    if finding is not None:
        changes = _changes(db, finding, change_config)
        matches = (changes.get("matches") or []) if changes.get("status") == "matched" else []
        for match in matches:
            what = " ".join(part for part in (str(match.get("event_type") or "change").capitalize(), match.get("version")) if part)
            _add(events, match.get("timestamp"), "deploy", f"{what} on {finding.service}", None)
        started = _parse(changes.get("anchor")) or _utc(finding.created_at)
        _add(events, started, "finding", f"Finding: {_headline(db, finding, snapshot)}", None)
    elif snapshot.get("summary") or snapshot.get("title"):
        started = _utc(case.created_at)

    _add(events, case.created_at, "opened", "Case opened", case.created_by)
    for key, provider, created in db.execute(
        select(CaseTicketLinkEntity.display_key, CaseTicketLinkEntity.provider, CaseTicketLinkEntity.created_at).where(CaseTicketLinkEntity.case_id == case.id)
    ).all():
        _add(events, created, "ticket", f"Ticket {key} linked", provider)
    for note in case.investigation_notes or []:
        if (note.get("note") or "").strip():
            _add(events, note.get("timestamp"), "note", note["note"].strip(), note.get("author"))
    for event in db.execute(
        select(CaseTicketEventEntity).where(CaseTicketEventEntity.case_id == case.id, CaseTicketEventEntity.event_type.in_(_COMMENT_TYPES))
    ).scalars():
        # A promoted comment is already a note above.
        if event.summary and not (event.payload or {}).get("promoted_at"):
            _add(events, event.occurred_at, "ticket_comment", event.summary.strip(), event.author)
    if case.resolved_at:
        _add(events, case.resolved_at, "resolved", _CLOSED_LABELS.get(case.outcome_status, "Closed"), case.resolved_by)

    events.sort(key=lambda event: event["time"])
    resolved = _utc(case.resolved_at)
    minutes = round((resolved - started).total_seconds() / 60) if resolved and started and resolved >= started else None
    return {"events": [{**event, "time": event["time"].isoformat()} for event in events], "time_to_fix_minutes": minutes}


def _changes(db: Session, finding: FindingEntity, config: AlertEnrichmentConfig | None) -> dict[str, Any]:
    if config is None:
        return {}
    return finding_changes(db, [finding], config).get(finding.id) or {}


def _headline(db: Session, finding: FindingEntity, snapshot: dict[str, Any]) -> str:
    try:
        plain = finding_plain(db, [finding]).get(finding.id)
    except Exception:  # noqa: BLE001 - the snapshot still names the finding
        logger.warning("Plain wording for case finding %s failed", finding.id, exc_info=True)
        db.rollback()
        plain = None
    return (plain or {}).get("headline") or snapshot.get("title") or finding.title or finding.metric_name


def _add(events: list[dict[str, Any]], when: Any, kind: str, text: str, who: str | None) -> None:
    moment = _parse(when) if isinstance(when, str) else _utc(when)
    if moment is not None:
        events.append({"time": moment, "kind": kind, "text": text, "who": who})


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _utc(value: datetime | None) -> datetime | None:
    return as_utc(value) if value else None
