from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.db import get_db
from backend.app.models.entities import BehaviorFindingEntity, FindingEntity, OperationalCaseEntity

router = APIRouter(prefix="/api/overview", tags=["overview"])

Window = Literal["24h", "7d"]
CLOSED_STATUSES = {"resolved", "verified", "closed", "completed"}
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
    open_cases: int
    behavior_changes: int
    impacted_services: int
    memory_items: int
    severity_trend: list[SeverityTrendPoint]
    category_breakdown: list[CategoryBreakdownItem]


def _window_start(window: Window, now: datetime) -> datetime:
    if window == "7d":
        return now - timedelta(days=7)
    return now - timedelta(hours=24)


def _bucket_start(value: datetime, window: Window) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    if window == "7d":
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    return value.replace(minute=0, second=0, microsecond=0)


def _is_closed(status: str | None) -> bool:
    return (status or "").lower() in CLOSED_STATUSES


@router.get("/summary", response_model=OverviewSummaryOut)
def get_overview_summary(
    window: Window = Query(default="24h"),
    db: Session = Depends(get_db),
) -> OverviewSummaryOut:
    generated_at = datetime.now(timezone.utc)
    start_at = _window_start(window, generated_at)

    findings = db.execute(select(FindingEntity).where(FindingEntity.created_at >= start_at)).scalars().all()
    cases = db.execute(select(OperationalCaseEntity)).scalars().all()
    cases_by_finding_id = {case.finding_id: case for case in cases}

    active_findings = [
        finding
        for finding in findings
        if not (
            finding.id in cases_by_finding_id
            and (
                _is_closed(cases_by_finding_id[finding.id].case_status)
                or _is_closed(cases_by_finding_id[finding.id].outcome_status)
            )
        )
    ]
    open_cases = [case for case in cases if not _is_closed(case.case_status)]
    behavior_changes = db.scalar(
        select(func.count()).select_from(BehaviorFindingEntity).where(BehaviorFindingEntity.created_at >= start_at)
    ) or 0
    memory_items = db.scalar(
        select(func.count()).select_from(OperationalCaseEntity).where(OperationalCaseEntity.memory_status == "indexed")
    ) or 0

    trend_by_bucket: dict[datetime, dict[str, int]] = {}
    category_counts: dict[str, int] = {}
    for finding in findings:
        bucket = _bucket_start(finding.created_at or generated_at, window)
        severity = (finding.health_status or "").lower()
        if severity in SEVERITIES:
            trend_by_bucket.setdefault(bucket, {item: 0 for item in SEVERITIES})[severity] += 1
        category = finding.category or "unknown"
        category_counts[category] = category_counts.get(category, 0) + 1

    return OverviewSummaryOut(
        generated_at=generated_at,
        window=window,
        active_findings=len(active_findings),
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
