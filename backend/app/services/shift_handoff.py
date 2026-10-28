"""The on-call handoff on the Overview: what happened in the last hours and what to watch first.

Deterministic (ADR-007): the counts, the ranking of what to watch and the summary sentence come
from Postgres with no LLM. With AI on, `write_handoff` turns the same facts into a short note; the
model only rewords them, and a sentence naming a number, version or name not in the facts is
dropped (case_ai_drafts.check_draft). Nothing here writes anything.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.services.narrative_service import synthesize_narrative
from backend.app.alerts.correlation import as_utc
from backend.app.config import AlertEnrichmentConfig
from backend.app.models.entities import FindingEntity, OperationalCaseEntity
from backend.app.services.active_findings import active_findings, is_closed, problem_of
from backend.app.services.case_ai_drafts import check_draft
from backend.app.services.finding_changes import finding_changes
from backend.app.services.finding_trust import finding_trust

logger = logging.getLogger(__name__)

# Findings store critical / significant / normal (from the importance score); some cases carry
# the alert's own severity words. Both rank, and read as the Findings page's High / Medium / Low.
SEVERITY_RANK = {"critical": 0, "high": 1, "significant": 1, "medium": 2, "normal": 3, "low": 3}
LEVEL_WORDS = {"critical": "high importance", "high": "high importance", "significant": "medium importance", "medium": "medium importance", "normal": "low importance", "low": "low importance"}
WATCH_LIMIT = 3
# Deploy lookups are a query or two each: only for the items that could make the list.
DEPLOY_LOOKUPS = 10

HANDOFF_INSTRUCTION = """You write the shift handoff note for the next on-call engineer.

You get counts for the last hours and the open problems, already ranked: item 1 is the one to
watch first. Write 2-3 short sentences:
1. What happened, using the counts.
2. Which item to watch first and why (still open, how long, after which deploy, how serious).
3. Optionally, one more item worth a look.

Rules:
- Use only the facts given. No numbers, versions, services or names that are not in them.
- Don't guess a cause. "Started after deploy X" is fine only when the facts say so.
- Plain words, no statistics words. Return only the sentences."""


@dataclass(slots=True)
class WatchItem:
    kind: str  # "case" or "finding"
    title: str
    severity: str | None
    service: str | None
    metric_name: str | None
    since: datetime | None
    case_id: int | None = None
    finding_id: int | None = None
    case_status: str | None = None
    deploy_version: str | None = None
    deploy_at: datetime | None = None
    reason: str = ""
    # Something happened in the window: the case was opened or updated, or the problem seen again.
    live: bool = True


@dataclass(slots=True)
class Handoff:
    generated_at: datetime
    hours: int
    since: datetime
    new_findings: int
    cases_opened: int
    cases_resolved: int
    cases_still_open: int
    watch: list[WatchItem] = field(default_factory=list)
    summary: str = ""


def build_handoff(db: Session, hours: int, change_config: AlertEnrichmentConfig, now: datetime | None = None) -> Handoff:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)

    findings = [row for row in db.execute(select(FindingEntity).where(FindingEntity.created_at >= since)).scalars().all() if _after(row.created_at, since)]
    cases = db.execute(select(OperationalCaseEntity)).scalars().all()
    # Imported past incidents are memory, not this shift's work.
    detected = [case for case in cases if not case.is_imported]
    open_cases = [case for case in detected if not _closed(case)]

    # A problem first seen in the window; one seen again by every run counts once, as on the Overview.
    new_problems = {problem_of(row) for row in findings if problem_of(row) == row.id}

    seen_in_window = {problem_of(row) for row in findings}
    candidates = _case_items(db, open_cases, since, seen_in_window) + _finding_items(db, findings, cases)
    # This shift's problems first, then the worst; among equals, one after a deploy, a case, the newest.
    candidates.sort(key=lambda item: _rank(item, deploys_known=False))
    _add_deploys(db, candidates[:DEPLOY_LOOKUPS], change_config)
    candidates.sort(key=lambda item: _rank(item, deploys_known=True))
    watch = candidates[:WATCH_LIMIT]
    for item in watch:
        item.reason = _reason(item, now)

    handoff = Handoff(
        generated_at=now,
        hours=hours,
        since=since,
        new_findings=len(new_problems),
        cases_opened=sum(1 for case in detected if _after(case.created_at, since)),
        cases_resolved=sum(1 for case in detected if _closed(case) and _after(case.resolved_at or case.updated_at, since)),
        cases_still_open=len(open_cases),
        watch=watch,
    )
    handoff.summary = handoff_summary(handoff)
    return handoff


def handoff_summary(handoff: Handoff) -> str:
    """The note without AI: the counts, then the item to watch first."""
    counts = (
        f"Last {handoff.hours} hours: {_plural(handoff.new_findings, 'new finding')}, "
        f"{_plural(handoff.cases_opened, 'case')} opened, {handoff.cases_resolved} resolved. "
        f"{_plural(handoff.cases_still_open, 'case')} still open."
    )
    if not handoff.watch:
        return f"{counts} Nothing open needs watching."
    return f"{counts} Watch first: {_label(handoff.watch[0])}, {handoff.watch[0].reason}."


def handoff_facts(handoff: Handoff) -> str:
    lines = [
        f"Window: last {handoff.hours} hours.",
        f"New findings: {handoff.new_findings}. Cases opened: {handoff.cases_opened}. Cases resolved: {handoff.cases_resolved}. Cases still open: {handoff.cases_still_open}.",
    ]
    if not handoff.watch:
        lines.append("Nothing open needs watching.")
    for index, item in enumerate(handoff.watch, start=1):
        lines.append(f"Item {index}: {_label(item)}; {item.title}; {item.reason}.")
    return "\n".join(lines)


def write_handoff(ai_services: OptionalAIServices, handoff: Handoff) -> str | None:
    facts = handoff_facts(handoff)
    try:
        text = synthesize_narrative(ai_services, instruction=HANDOFF_INSTRUCTION, evidence_text=facts, max_tokens=220)
    except Exception:  # noqa: BLE001 - the deterministic summary is always there
        logger.warning("Handoff note could not be written", exc_info=True)
        return None
    return check_draft(text, facts)


def _rank(item: WatchItem, *, deploys_known: bool) -> tuple:
    severity = SEVERITY_RANK.get((item.severity or "").lower(), 4)
    after_deploy = item.deploy_version is None if deploys_known else False
    return (not item.live, severity, after_deploy, item.kind != "case", -_epoch(item.since))


def _case_items(db: Session, open_cases: list[OperationalCaseEntity], since: datetime, seen_in_window: set[int | None]) -> list[WatchItem]:
    finding_ids = [case.finding_id for case in open_cases if case.finding_id]
    linked = {row.id: row for row in db.execute(select(FindingEntity).where(FindingEntity.id.in_(finding_ids))).scalars().all()} if finding_ids else {}
    items = []
    for case in open_cases:
        snapshot = case.finding_snapshot or {}
        finding = linked.get(case.finding_id)
        items.append(
            WatchItem(
                kind="case",
                title=case.case_title,
                severity=(finding.health_status if finding else None) or snapshot.get("health_status") or snapshot.get("severity"),
                service=(finding.service if finding else None) or snapshot.get("service"),
                metric_name=(finding.metric_name if finding else None) or snapshot.get("metric_name"),
                since=case.created_at,
                case_id=case.id,
                finding_id=case.finding_id,
                case_status=case.case_status,
                live=_after(case.created_at, since) or _after(case.updated_at, since) or (finding is not None and problem_of(finding) in seen_in_window),
            )
        )
    return items


def _finding_items(db: Session, findings: list[FindingEntity], cases: list[OperationalCaseEntity]) -> list[WatchItem]:
    """Problems in the window that need attention and nobody has opened a case for."""
    cased = {case.finding_id for case in cases if case.finding_id}
    active = active_findings(db, findings, cases)
    trust = finding_trust(db, active) if active else {}
    latest: dict[int | None, FindingEntity] = {}
    for row in active:
        if (trust.get(row.id) or {}).get("tier") != "needs_attention":
            continue
        problem = problem_of(row)
        if problem in cased or row.id in cased:
            continue
        current = latest.get(problem)
        if current is None or (row.importance_score or 0) > (current.importance_score or 0):
            latest[problem] = row
    first_seen: dict[int | None, datetime] = {}
    for row in findings:
        if row.created_at and (problem_of(row) not in first_seen or _epoch(row.created_at) < _epoch(first_seen[problem_of(row)])):
            first_seen[problem_of(row)] = row.created_at
    return [
        WatchItem(
            kind="finding",
            title=row.title,
            severity=row.health_status,
            service=row.service,
            metric_name=row.metric_name,
            since=first_seen.get(problem, row.created_at),
            finding_id=row.id,
        )
        for problem, row in latest.items()
    ]


def _add_deploys(db: Session, items: list[WatchItem], change_config: AlertEnrichmentConfig) -> None:
    ids = [item.finding_id for item in items if item.finding_id]
    if not ids:
        return
    rows = db.execute(select(FindingEntity).where(FindingEntity.id.in_(ids))).scalars().all()
    changes = finding_changes(db, list(rows), change_config)
    for item in items:
        deploy = _deploy(changes.get(item.finding_id) or {})
        if deploy:
            item.deploy_version = deploy.get("version") or deploy.get("description") or "a deploy"
            item.deploy_at = _parse(deploy.get("timestamp"))


def _deploy(changes: dict[str, Any]) -> dict[str, Any] | None:
    if changes.get("status") != "matched":
        return None
    return next((match for match in changes.get("matches") or [] if match.get("version")), None) or next(iter(changes.get("matches") or []), None)


def _reason(item: WatchItem, now: datetime) -> str:
    parts = []
    if item.kind == "case":
        parts.append(f"open {_age(item.since, now)}")
    else:
        parts.append(f"no case yet, seen {_age(item.since, now)} ago")
    if item.deploy_version:
        parts.append(f"started after deploy {item.deploy_version}")
    if level := LEVEL_WORDS.get((item.severity or "").lower()):
        parts.append(level)
    return ", ".join(parts)


def _label(item: WatchItem) -> str:
    where = " ".join(part for part in (item.service, item.metric_name) if part) or item.title
    return f"case #{item.case_id} ({where})" if item.case_id else where


def _age(value: datetime | None, now: datetime) -> str:
    if value is None:
        return "for a while"
    minutes = max(0, int((now - as_utc(value)).total_seconds() // 60))
    if minutes < 60:
        return _plural(max(minutes, 1), "minute")
    if minutes < 48 * 60:
        return _plural(minutes // 60, "hour")
    return _plural(minutes // (24 * 60), "day")


def _closed(case: OperationalCaseEntity) -> bool:
    return is_closed(case.case_status) or is_closed(case.outcome_status)


def _after(value: datetime | None, since: datetime) -> bool:
    return value is not None and as_utc(value) >= since


def _epoch(value: datetime | None) -> float:
    return as_utc(value).timestamp() if value else 0.0


def _parse(value: Any) -> datetime | None:
    try:
        return as_utc(datetime.fromisoformat(str(value))) if value else None
    except ValueError:
        return None


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"
