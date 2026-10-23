"""Find change events (deploys, config, flags) near an alert's change point.

A temporal hint only: messages say "started N min after deploy X", never "caused by".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_, select
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
    cluster: str | None = None
    # Who reported it: CI's own `source`, or `ops-signals:...` for a deploy found in Prometheus.
    source: str | None = None


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


def service_names(service: str, aliases: list[list[str]] | None = None) -> list[str]:
    """The service plus every name an alias group gives it, compared case-insensitively."""
    names = [service]
    for group in aliases or []:
        if any(name.lower() == service.lower() for name in group):
            names.extend(name for name in group if name not in names)
    return names


def correlate_changes(
    db: Session,
    service: str | None,
    anchor: datetime,
    before: timedelta,
    after: timedelta,
    limit: int = 3,
    env: str | None = None,
    aliases: list[list[str]] | None = None,
    cluster: str | None = None,
) -> ChangeCorrelation:
    """With `env` or `cluster`, events from another environment or cluster are skipped; events that
    name none still match (a deploy without a cluster counts for every cluster).
    `aliases` lists names that mean the same service (AlertEnrichmentConfig.service_aliases)."""
    anchor = as_utc(anchor)
    correlation = ChangeCorrelation(
        service=service,
        anchor=anchor,
        window_before_minutes=int(before.total_seconds() // 60),
        window_after_minutes=int(after.total_seconds() // 60),
    )
    if not service:
        return correlation

    names = service_names(service, aliases)
    correlation.service_has_any_events = bool(
        db.execute(select(func.count(ChangeEventEntity.id)).where(ChangeEventEntity.service.in_(names))).scalar()
    )
    if not correlation.service_has_any_events:
        return correlation

    query = select(ChangeEventEntity).where(
        ChangeEventEntity.service.in_(names),
        ChangeEventEntity.timestamp >= anchor - before,
        ChangeEventEntity.timestamp <= anchor + after,
    )
    if env:
        query = query.where(or_(ChangeEventEntity.env.is_(None), ChangeEventEntity.env == "", func.lower(ChangeEventEntity.env) == env.lower()))
    if cluster:
        query = query.where(
            or_(ChangeEventEntity.cluster.is_(None), ChangeEventEntity.cluster == "", func.lower(ChangeEventEntity.cluster) == cluster.lower())
        )
    rows = db.execute(query).scalars().all()
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
            cluster=row.cluster or None,
            source=row.source or None,
        )
        for row in rows
    ]
    matches.sort(key=lambda match: abs(match.minutes_before_anchor))
    correlation.matches = matches[:limit]
    return correlation


def changes_to_dict(changes: ChangeCorrelation | None) -> dict[str, Any] | None:
    """The stored / API form, shared by alerts and findings."""
    if changes is None:
        return None
    return {
        "anchor": changes.anchor.isoformat(),
        "window_before_minutes": changes.window_before_minutes,
        "window_after_minutes": changes.window_after_minutes,
        "service_has_any_events": changes.service_has_any_events,
        "matches": [
            {
                "id": match.id,
                "event_type": match.event_type,
                "timestamp": match.timestamp.isoformat(),
                "version": match.version,
                "author": match.author,
                "url": match.url,
                "description": match.description,
                "minutes_before_anchor": round(match.minutes_before_anchor, 1),
                "cluster": match.cluster,
                "source": match.source,
            }
            for match in changes.matches
        ],
    }
