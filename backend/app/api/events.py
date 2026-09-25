"""Change events (deploys, config changes, flags) reported by CI/CD, correlated with alerts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.alerts.auth import check_bearer_token
from backend.app.alerts.correlation import as_utc
from backend.app.config import AlertEnrichmentConfig, get_alert_enrichment_config
from backend.app.models.db import get_db
from backend.app.models.entities import ChangeEventEntity
from backend.app.security import receiver_token_or_api_token

router = APIRouter(prefix="/api/events", tags=["events"])

EventType = Literal["deploy", "config", "feature_flag", "scale", "rollback", "other"]
_MAX_BATCH = 100
_MAX_FUTURE = timedelta(hours=1)


class ChangeEventIn(BaseModel):
    service: str = Field(min_length=1)
    type: EventType
    timestamp: datetime | None = None
    version: str | None = None
    env: str | None = None
    author: str | None = None
    source: str | None = None
    url: str | None = None
    description: str | None = None
    attributes: dict = Field(default_factory=dict)

    @field_validator("service")
    @classmethod
    def service_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("service must not be blank")
        return value.strip()

    @field_validator("url")
    @classmethod
    def url_is_http(cls, value: str | None) -> str | None:
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return value


class ChangeEventOut(BaseModel):
    id: int
    service: str
    type: str
    timestamp: datetime
    version: str | None = None
    env: str | None = None
    author: str | None = None
    source: str | None = None
    url: str | None = None
    description: str | None = None
    attributes: dict = Field(default_factory=dict)
    received_at: datetime | None = None


def require_events_token(
    authorization: str | None = Header(default=None),
    config: AlertEnrichmentConfig = Depends(get_alert_enrichment_config),
) -> None:
    check_bearer_token(authorization, receiver_token_or_api_token(config.events_token))


def _to_out(row: ChangeEventEntity) -> ChangeEventOut:
    return ChangeEventOut(
        id=row.id,
        service=row.service,
        type=row.event_type,
        timestamp=as_utc(row.timestamp),
        version=row.version,
        env=row.env,
        author=row.author,
        source=row.source,
        url=row.url,
        description=row.description,
        attributes=row.attributes_json or {},
        received_at=as_utc(row.received_at) if row.received_at else None,
    )


@router.post("", status_code=201, response_model=list[ChangeEventOut])
def create_events(
    payload: ChangeEventIn | list[ChangeEventIn],
    db: Session = Depends(get_db),
    _: None = Depends(require_events_token),
) -> list[ChangeEventOut]:
    """Record one change event, or a batch (JSON array, max 100). Always returns a list."""
    events = payload if isinstance(payload, list) else [payload]
    if not events:
        raise HTTPException(status_code=400, detail="no events given")
    if len(events) > _MAX_BATCH:
        raise HTTPException(status_code=400, detail=f"at most {_MAX_BATCH} events per request")
    now = datetime.now(timezone.utc)
    rows: list[ChangeEventEntity] = []
    for event in events:
        timestamp = as_utc(event.timestamp) if event.timestamp else now
        if timestamp > now + _MAX_FUTURE:
            raise HTTPException(status_code=400, detail="timestamp is more than 1h in the future")
        rows.append(
            ChangeEventEntity(
                service=event.service,
                event_type=event.type,
                timestamp=timestamp,
                version=event.version,
                env=event.env,
                author=event.author,
                source=event.source,
                url=event.url,
                description=event.description,
                attributes_json=event.attributes or None,
                received_at=now,
            )
        )
    db.add_all(rows)
    db.commit()
    return [_to_out(row) for row in rows]


@router.get("", response_model=list[ChangeEventOut])
def list_events(
    service: str | None = None,
    type: EventType | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[ChangeEventOut]:
    query = select(ChangeEventEntity)
    if service:
        query = query.where(ChangeEventEntity.service == service)
    if type:
        query = query.where(ChangeEventEntity.event_type == type)
    if since:
        query = query.where(ChangeEventEntity.timestamp >= as_utc(since))
    if until:
        query = query.where(ChangeEventEntity.timestamp <= as_utc(until))
    rows = db.execute(query.order_by(ChangeEventEntity.timestamp.desc()).limit(limit)).scalars().all()
    return [_to_out(row) for row in rows]
