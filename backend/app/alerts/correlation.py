"""Find change events (deploys, config, flags) near an alert's change point.

A temporal hint only: messages say "started N min after deploy X", never "caused by".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.entities import ChangeEventEntity


@dataclass
class ChangeMatch:
    id: int
    event_type: str
    timestamp: datetime
    version: str | None
    author: str | None
    url: str | None
    description: str | None
    minutes_before_anchor: float  # positive: the change happened before the anchor


@dataclass
class ChangeCorrelation:
    service: str | None
    anchor: datetime
    window_before_minutes: int
    window_after_minutes: int
    matches: list[ChangeMatch] = field(default_factory=list)
    service_has_any_events: bool = False

    @property
    def nearest(self) -> ChangeMatch | None:
        return self.matches[0] if self.matches else None


def as_utc(value: datetime) -> datetime:
    # SQLite hands back naive datetimes even for timezone=True columns; everything here is UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def correlate_changes(
    db: Session,
    service: str | None,
    anchor: datetime,
    before: timedelta,
    after: timedelta,
    limit: int = 3,
) -> ChangeCorrelation:
    anchor = as_utc(anchor)
    correlation = ChangeCorrelation(
        service=service,
        anchor=anchor,
        window_before_minutes=int(before.total_seconds() // 60),
        window_after_minutes=int(after.total_seconds() // 60),
    )
    if not service:
        return correlation

    correlation.service_has_any_events = bool(
        db.execute(select(func.count(ChangeEventEntity.id)).where(ChangeEventEntity.service == service)).scalar()
    )
    if not correlation.service_has_any_events:
        return correlation

    rows = db.execute(
        select(ChangeEventEntity).where(
            ChangeEventEntity.service == service,
            ChangeEventEntity.timestamp >= anchor - before,
            ChangeEventEntity.timestamp <= anchor + after,
        )
    ).scalars().all()
    matches = [
        ChangeMatch(
            id=row.id,
            event_type=row.event_type,
            timestamp=as_utc(row.timestamp),
            version=row.version,
            author=row.author,
            url=row.url,
            description=row.description,
            minutes_before_anchor=(anchor - as_utc(row.timestamp)).total_seconds() / 60.0,
        )
        for row in rows
    ]
    matches.sort(key=lambda match: abs(match.minutes_before_anchor))
    correlation.matches = matches[:limit]
    return correlation
