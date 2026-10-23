from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.db import get_db
from backend.app.models.entities import BehaviorFindingEntity, FindingEntity, OperationalCaseEntity
from backend.app.services.active_findings import active_findings as still_active
from backend.app.services.active_findings import is_closed as _is_closed
from backend.app.services.active_findings import problem_of as _problem
from backend.app.services.finding_trust import finding_trust

router = APIRouter(prefix="/api/overview", tags=["overview"])

Window = Literal["6h", "24h", "7d"]
SEVERITIES = ("critical", "high", "medium", "low")


class SeverityTrendPoint(BaseModel):
    timestamp: datetime
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0


class CategoryBreakdownItem(BaseModel):
    category: str
    count: int


class OverviewSummaryOut(BaseModel):
    generated_at: datetime
    window: Window
    active_findings: int
    # active_findings split by trust tier (services/finding_trust.py): a problem needs attention
    # when any of its findings does; the rest are context, one click away on the Findings page.
    attention_findings: int = 0
    context_findings: int = 0
    open_cases: int
    behavior_changes: int
    impacted_services: int
    memory_items: int
    severity_trend: list[SeverityTrendPoint]
    category_breakdown: list[CategoryBreakdownItem]


def _window_start(window: Window, now: datetime) -> datetime:
    if window == "6h":
        return now - timedelta(hours=6)
    if window == "7d":
        return now - timedelta(days=7)
    return now - timedelta(hours=24)


def _bucket_start(value: datetime, window: Window) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    if window == "7d":
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    return value.replace(minute=0, second=0, microsecond=0)


@router.get("/summary", response_model=OverviewSummaryOut)
def get_overview_summary(
    window: Window = Query(default="24h"),
    db: Session = Depends(get_db),
) -> OverviewSummaryOut:
    generated_at = datetime.now(timezone.utc)
    start_at = _window_start(window, generated_at)

    findings = db.execute(select(FindingEntity).where(FindingEntity.created_at >= start_at)).scalars().all()
    cases = db.execute(select(OperationalCaseEntity)).scalars().all()
    # A problem every run sees again is one problem: counted once, closed when a case on any of
    # its findings (or on the first one, even before this window) is closed.
    active_findings = still_active(db, findings, cases)
    open_cases = [case for case in cases if not _is_closed(case.case_status)]
    behavior_changes = db.scalar(
        select(func.count()).select_from(BehaviorFindingEntity).where(BehaviorFindingEntity.created_at >= start_at)
    ) or 0
    memory_items = db.scalar(
        select(func.count()).select_from(OperationalCaseEntity).where(OperationalCaseEntity.memory_status == "indexed")
    ) or 0

    # Each problem once per bucket, at its worst severity there; each problem once per category.
    worst_in_bucket: dict[tuple[datetime, int | None], str] = {}
    problem_categories: dict[str, set[int | None]] = {}
    for finding in findings:
        bucket = _bucket_start(finding.created_at or generated_at, window)
        severity = (finding.health_status or "").lower()
        if severity in SEVERITIES:
            key = (bucket, _problem(finding))
            current = worst_in_bucket.get(key)
            if current is None or SEVERITIES.index(severity) < SEVERITIES.index(current):
                worst_in_bucket[key] = severity
        problem_categories.setdefault(finding.category or "unknown", set()).add(_problem(finding))
    trend_by_bucket: dict[datetime, dict[str, int]] = {}
    for (bucket, _), severity in worst_in_bucket.items():
        trend_by_bucket.setdefault(bucket, {item: 0 for item in SEVERITIES})[severity] += 1
    category_counts = {category: len(problems) for category, problems in problem_categories.items()}

    active_problems = {_problem(finding) for finding in active_findings}
    trust = finding_trust(db, active_findings) if active_findings else {}
    attention_problems = {
        _problem(finding) for finding in active_findings if (trust.get(finding.id) or {}).get("tier") == "needs_attention"
    }

    return OverviewSummaryOut(
        generated_at=generated_at,
        window=window,
        active_findings=len(active_problems),
        attention_findings=len(attention_problems),
        context_findings=len(active_problems - attention_problems),
        open_cases=len(open_cases),
        behavior_changes=int(behavior_changes),
        impacted_services=len({finding.service for finding in active_findings if finding.service}),
        memory_items=int(memory_items),
        severity_trend=[
            SeverityTrendPoint(timestamp=bucket, **counts)
            for bucket, counts in sorted(trend_by_bucket.items(), key=lambda item: item[0])
        ],
        category_breakdown=[
            CategoryBreakdownItem(category=category, count=count)
            for category, count in sorted(category_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
    )
