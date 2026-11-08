"""What a team knows about a service, and dependencies suggested from its own metrics.

Notes are written by people: in the Investigate dialog before a guided investigation starts, or
saved from one. Suggestions never become notes on their own; a person adds or dismisses each one.

A suggestion comes from a label on the service's own series that names something it talks to:
`db_name="payments"`, `peer_service="catalog"`, `queue="orders"`. Which label carries the service
name differs between teams, so each of the configured service labels is tried in turn (the same
list alert enrichment uses, OPS_SIGNALS_ALERT_SERVICE_LABELS).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.entities import ServiceNoteEntity
from backend.app.services.prometheus_service import PrometheusQueryService

logger = logging.getLogger(__name__)

KINDS = ("service", "database", "queue", "cache", "outside")

# Labels that name something the service talks to, and what kind of thing that is.
DEPENDENCY_LABELS: dict[str, str] = {
    "peer_service": "service",
    "upstream": "service",
    "upstream_service": "service",
    "target_service": "service",
    "destination_service": "service",
    "destination_workload": "service",
    "server_address": "service",
    "db_name": "database",
    "db_namespace": "database",
    "database": "database",
    "datname": "database",
    "queue": "queue",
    "queue_name": "queue",
    "topic": "queue",
    "messaging_destination_name": "queue",
    "consumergroup": "queue",
    "cache_name": "cache",
    "redis_instance": "cache",
}
MAX_SUGGESTIONS = 8
# Series read per service label when looking for suggestions; enough to see its label names.
SERIES_LIMIT = 2000
LOOKBACK = timedelta(hours=1)


def note_dict(row: ServiceNoteEntity | None, service: str) -> dict[str, Any]:
    if row is None:
        return {"service": service, "exists": False, "depends_on": [], "behaviours": [], "dismissed": [], "owner": None, "channel": None, "runbook_url": None, "updated_by": None, "updated_at": None}
    return {
        "service": row.service,
        "exists": True,
        "depends_on": list(row.depends_on or []),
        "behaviours": list(row.behaviours or []),
        "dismissed": list(row.dismissed or []),
        "owner": row.owner,
        "channel": row.channel,
        "runbook_url": row.runbook_url,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def get_note(db: Session, service: str) -> dict[str, Any]:
    return note_dict(db.get(ServiceNoteEntity, service), service)


def save_note(db: Session, service: str, values: dict[str, Any], by: str | None) -> dict[str, Any]:
    """Replace the service's notes. Behaviours keep who wrote them and when; a new line gets `by`."""
    row = db.get(ServiceNoteEntity, service)
    if row is None:
        row = ServiceNoteEntity(service=service)
        db.add(row)
    now = datetime.now(timezone.utc).isoformat()
    row.depends_on = _clean_dependencies(values.get("depends_on") or [])
    row.behaviours = [
        {**{key: item[key] for key in ("case_id",) if item.get(key) is not None}, "text": str(item["text"]).strip(), "by": item.get("by") or by, "at": item.get("at") or now}
        for item in values.get("behaviours") or []
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]
    row.dismissed = sorted({str(name) for name in values.get("dismissed") or [] if str(name).strip()})
    row.owner = _text(values.get("owner"))
    row.channel = _text(values.get("channel"))
    row.runbook_url = _text(values.get("runbook_url"))
    row.updated_by = by
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return note_dict(row, service)


def add_behaviour(db: Session, service: str, text: str, by: str | None, case_id: int | None = None) -> dict[str, Any]:
    """Save one "always true" line, from the Investigate dialog's note or an investigation step."""
    note = get_note(db, service)
    note["behaviours"].append({"text": text, "by": by, **({"case_id": case_id} if case_id else {})})
    return save_note(db, service, note, by)


def suggest_dependencies(
    prometheus: PrometheusQueryService,
    service: str,
    service_labels: list[str],
    known: set[str],
    now: datetime | None = None,
) -> list[dict[str, str]]:
    """Dependencies named by labels on the service's own series, newest data only. Never raises: a
    Prometheus that can't be reached gives no suggestions."""
    end = now or datetime.now(timezone.utc)
    found: dict[str, dict[str, str]] = {}
    for label in service_labels:
        try:
            series = prometheus.direct_scoped_series(f'{{{label}="{_escape(service)}"}}', start=end - LOOKBACK, end=end, limit=SERIES_LIMIT)
        except Exception:  # noqa: BLE001 - suggestions are extra
            logger.info("Dependency suggestions for %s: series lookup on %s failed", service, label, exc_info=True)
            continue
        for row in series:
            for key, value in row.items():
                kind = DEPENDENCY_LABELS.get(key)
                name = (value or "").strip()
                if not kind or not name or name == service or name in known or name in found:
                    continue
                found[name] = {"name": name, "kind": kind, "label": f'{key}="{name}"'}
        if found:
            break
    return sorted(found.values(), key=lambda item: (KINDS.index(item["kind"]), item["name"]))[:MAX_SUGGESTIONS]


def known_names(note: dict[str, Any]) -> set[str]:
    return {str(item.get("name")) for item in note.get("depends_on") or []} | set(note.get("dismissed") or [])


def notes_text(note: dict[str, Any]) -> str | None:
    """The notes as lines for the investigation prompt, or None when there are none."""
    lines: list[str] = []
    if note.get("depends_on"):
        lines.append("Depends on: " + ", ".join(f"{item['name']} ({item.get('kind') or 'service'})" for item in note["depends_on"]) + ".")
    for item in note.get("behaviours") or []:
        source = f"case #{item['case_id']}" if item.get("case_id") else (item.get("by") or "a teammate")
        lines.append(f'Known behaviour ({source}): "{item["text"]}"')
    owner = ", ".join(part for part in (note.get("owner"), note.get("channel")) if part)
    if owner:
        lines.append(f"Owner: {owner}.")
    if note.get("runbook_url"):
        lines.append(f"Runbook: {note['runbook_url']}")
    return "\n".join(lines) or None


def all_notes(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(select(ServiceNoteEntity).order_by(ServiceNoteEntity.service)).scalars()
    return [note_dict(row, row.service) for row in rows]


def _clean_dependencies(items: list[Any]) -> list[dict[str, str]]:
    seen: set[str] = set()
    cleaned: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        kind = str(item.get("kind") or "service")
        cleaned.append({"name": name, "kind": kind if kind in KINDS else "service"})
    return cleaned


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
