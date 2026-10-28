"""The on-call handoff on the Overview: what happened in the last hours and what to watch first.

Deterministic (ADR-007): the counts, the ranking of what to watch and the summary sentence come
from Postgres with no LLM. With AI on, `write_handoff` turns the same facts into a short note; the
model only rewords them, and a sentence naming a number, version or name not in the facts is
dropped (case_ai_drafts.check_draft). Nothing here writes anything.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.services.narrative_service import synthesize_narrative
from backend.app.alerts.correlation import as_utc
from backend.app.config import AlertEnrichmentConfig
from backend.app.models.entities import BehaviorFindingEntity, FindingEntity, OperationalCaseEntity
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
MAX_LIMIT = 20
# Equal level and age: a case is being worked on, a combined pattern is several metrics agreeing.
KIND_ORDER = {"case": 0, "pattern": 1, "finding": 2}
# Deploy lookups are a query or two each: only for the items that could make the list.
DEPLOY_LOOKUPS = 10

HANDOFF_INSTRUCTION = """You write the shift handoff note for the next on-call engineer.

You get the open problems, already ranked: item 1 is the one to watch first. The counts are
written separately; don't repeat them. Write 1-2 short sentences:
1. Which item to watch first and why, using only its line: how long it has been open, the deploy
   it started after (only if its line names one), how important it is.
2. Optionally, the next item worth a look.

Rules:
- Name each item by its case number ("case #12") or, without one, by its service.
- Use only the words in the item lines. Don't describe what the problem is beyond its title, don't
  add amounts ("many", "a lot", "high volume") and don't guess a cause.
- Plain words, no statistics words. Return only the sentences."""


@dataclass(slots=True)
class WatchItem:
    kind: str  # "case", "pattern" (a combined pattern with no case) or "finding" (no case)
    title: str
    severity: str | None
    service: str | None
    metric_name: str | None
    since: datetime | None
    case_id: int | None = None
    finding_id: int | None = None
    pattern_id: int | None = None
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
    # Open cases nothing happened to in the window; listed after this shift's items, if at all.
    older_open_cases: int = 0
    watch: list[WatchItem] = field(default_factory=list)
    summary: str = ""


def build_handoff(db: Session, hours: int, change_config: AlertEnrichmentConfig, now: datetime | None = None, limit: int = WATCH_LIMIT) -> Handoff:
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
    candidates = _case_items(db, open_cases, since, seen_in_window) + _pattern_items(db, since, cases) + _finding_items(db, findings, cases)
    # This shift's problems first, then the worst; among equals, one after a deploy, a case, the newest.
    candidates.sort(key=lambda item: _rank(item, deploys_known=False))
    _add_deploys(db, candidates[:DEPLOY_LOOKUPS], change_config)
    candidates.sort(key=lambda item: _rank(item, deploys_known=True))
    watch = candidates[: max(1, min(limit, MAX_LIMIT))]
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
        older_open_cases=sum(1 for item in candidates if item.kind == "case" and not item.live),
        watch=watch,
    )
    handoff.summary = handoff_summary(handoff)
    return handoff


def handoff_counts(handoff: Handoff) -> str:
    return (
        f"Last {handoff.hours} hours: {_plural(handoff.new_findings, 'new finding')}, "
        f"{_plural(handoff.cases_opened, 'case')} opened, {handoff.cases_resolved} resolved. "
        f"{_plural(handoff.cases_still_open, 'case')} still open."
    )


def handoff_summary(handoff: Handoff) -> str:
    """The note without AI: the counts, then the item to watch first."""
    counts = handoff_counts(handoff)
    if not handoff.watch:
        return f"{counts} Nothing open needs watching."
    return f"{counts} Watch first: {_label(handoff.watch[0])}, {handoff.watch[0].reason}."


def handoff_facts(handoff: Handoff) -> str:
    items = handoff.watch[:WATCH_LIMIT]
    return "\n".join(f"Item {index}: {_label(item)}; {item.title}; {item.reason}." for index, item in enumerate(items, start=1))


def write_handoff(ai_services: OptionalAIServices, handoff: Handoff) -> str | None:
    """The counts as code writes them, then AI's sentences on what to watch. A sentence that names
    no item (by case number or service), or anything not in the item lines, is dropped: the model
    once opened with "a high volume of error reports", which nothing said."""
    if not handoff.watch:
        return None
    facts = handoff_facts(handoff)
    try:
        text = synthesize_narrative(ai_services, instruction=HANDOFF_INSTRUCTION, evidence_text=facts, max_tokens=160)
    except Exception:  # noqa: BLE001 - the deterministic summary is always there
        logger.warning("Handoff note could not be written", exc_info=True)
        return None
    checked = check_draft(text, facts)
    kept = [sentence for sentence in _SENTENCE.split(checked or "") if _names_an_item(sentence, handoff.watch[:WATCH_LIMIT]) and not _VAGUE.search(sentence)]
    if not kept:
        return None
    return f"{handoff_counts(handoff)} {' '.join(kept)}"


_SENTENCE = re.compile(r"(?<=[.!?])\s+")
# Amounts nothing in the facts measures.
_VAGUE = re.compile(r"\b(high volume|a lot of|lots of|many|numerous|several|significant(ly)? (number|amount)|surge|spike in reports)\b", re.IGNORECASE)


def _names_an_item(sentence: str, items: list[WatchItem]) -> bool:
    text = sentence.lower()
    return any(
        (item.case_id is not None and f"#{item.case_id}" in text) or (item.service and item.service.lower() in text)
        for item in items
    )


def _rank(item: WatchItem, *, deploys_known: bool) -> tuple:
    severity = SEVERITY_RANK.get((item.severity or "").lower(), 4)
    after_deploy = item.deploy_version is None if deploys_known else False
    return (not item.live, severity, after_deploy, KIND_ORDER.get(item.kind, 3), -_epoch(item.since))


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


def _pattern_items(db: Session, since: datetime, cases: list[OperationalCaseEntity]) -> list[WatchItem]:
    """Combined patterns seen in the window that nobody has opened a case for (a case on one is
    already listed as a case)."""
    cased = {case.behavior_finding_id for case in cases if case.behavior_finding_id}
    rows = db.execute(select(BehaviorFindingEntity).where(BehaviorFindingEntity.last_seen_at >= since)).scalars().all()
    return [
        WatchItem(
            kind="pattern",
            title=row.title,
            severity=row.severity,
            service=row.service,
            metric_name=_plural(len(row.input_metrics_json or {}), "metric") if row.input_metrics_json else None,
            since=row.created_at,
            pattern_id=row.id,
        )
        for row in rows
        if _after(row.last_seen_at, since) and row.case_id is None and row.id not in cased
    ]


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
    elif item.kind == "pattern":
        parts.append(f"combined pattern, no case yet, seen {_age(item.since, now)} ago")
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
