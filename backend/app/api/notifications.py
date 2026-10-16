from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.config import get_slack_config
from backend.app.models.db import get_db
from backend.app.models.entities import SlackNotificationEntity
from backend.app.notifications.slack_client import DELIVERED, FAILED, PENDING

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

RECENT = timedelta(hours=24)


class SlackFailureOut(BaseModel):
    title: str
    service: str | None = None
    metric_name: str | None = None
    error: str | None = None
    attempts: int
    status: str
    created_at: datetime
    next_retry_at: datetime | None = None


class SlackStatusOut(BaseModel):
    enabled: bool
    delivered_last_24h: int
    retrying: int
    failed_last_24h: int
    last_failure: SlackFailureOut | None = None


@router.get("/slack", response_model=SlackStatusOut)
def slack_status(db: Session = Depends(get_db)) -> SlackStatusOut:
    """Whether finding messages are reaching Slack: delivered and failed in the last day, and how
    many are waiting to be retried. A failure used to leave only a server log line."""
    config = get_slack_config()
    since = datetime.utcnow() - RECENT
    counts = dict(
        db.execute(
            select(SlackNotificationEntity.status, func.count())
            .where((SlackNotificationEntity.created_at >= since) | (SlackNotificationEntity.status == PENDING))
            .group_by(SlackNotificationEntity.status)
        ).all()
    )
    last = db.scalars(
        select(SlackNotificationEntity)
        .where(SlackNotificationEntity.last_error.is_not(None))
        .order_by(SlackNotificationEntity.created_at.desc(), SlackNotificationEntity.id.desc())
        .limit(1)
    ).first()
    return SlackStatusOut(
        enabled=bool(config.enabled and config.webhook_url),
        delivered_last_24h=int(counts.get(DELIVERED, 0)),
        retrying=int(counts.get(PENDING, 0)),
        failed_last_24h=int(counts.get(FAILED, 0)),
        last_failure=SlackFailureOut(
            title=last.title,
            service=last.service,
            metric_name=last.metric_name,
            error=last.last_error,
            attempts=last.attempts,
            status=last.status,
            created_at=last.created_at,
            next_retry_at=last.next_attempt_at if last.status == PENDING else None,
        )
        if last is not None
        else None,
    )
