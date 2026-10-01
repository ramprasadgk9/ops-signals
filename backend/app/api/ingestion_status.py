"""GET /api/ingestion/status - one read for "is any data getting in?", behind the Overview page's
first-run "Get data in" panel and its source-status strip.

Read-only and best-effort: every lookup that can fail degrades to "unknown" (None / False) rather
than failing the request, so the Overview never breaks because of this card.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.config import get_alert_enrichment_config, get_prometheus_config
from backend.app.models.db import get_db
from backend.app.models.entities import (
    AlertEnrichmentEntity,
    AnalysisRunEntity,
    AutonomousPolicyEntity,
    ChangeEventEntity,
    FindingEntity,
    OtlpPendingPointEntity,
)
from backend.app.otlp.metrics import last_received_at as otlp_last_received_at
from backend.app.security import receiver_token_or_api_token
from backend.app.services.prometheus_service import PrometheusQueryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])

OTLP_ENDPOINT_PATH = "/api/otlp/v1/metrics"
ALERTMANAGER_ENDPOINT_PATH = "/api/integrations/alertmanager"
EVENTS_ENDPOINT_PATH = "/api/events"
# The page polls this every 15s; a Prometheus reachability check is cached so it isn't hit that often.
PROMETHEUS_CHECK_TTL_SECONDS = 30.0
PROMETHEUS_CHECK_TIMEOUT_SECONDS = 3.0
_prometheus_check: tuple[float, str, bool] | None = None
# analysis_runs.source_type the OTLP backlog cycle writes (backend/app/autonomous/scheduler.py).
OTLP_RUN_SOURCE_TYPE = "otel"


class OtlpSourceStatus(BaseModel):
    endpoint_path: str
    last_received_at: datetime | None


class AlertmanagerSourceStatus(BaseModel):
    endpoint_path: str
    enabled: bool
    token_required: bool
    last_received_at: datetime | None
    received_24h: int


class PrometheusSourceStatus(BaseModel):
    configured: bool
    url: str | None = None  # without any user:password@ part
    reachable: bool | None = None  # None when not configured
    scheduled_policies: int = 0  # enabled autonomous analysis policies
    alert_enrichment_enabled: bool = False


class LastChangeEvent(BaseModel):
    service: str
    type: str
    version: str | None = None
    env: str | None = None
    timestamp: datetime


class EventsSourceStatus(BaseModel):
    """Deploy and other change events sent to POST /api/events (by CI, or later by GitHub)."""

    endpoint_path: str
    token_required: bool
    last_received_at: datetime | None
    received_24h: int
    last_event: LastChangeEvent | None = None


class IngestionSources(BaseModel):
    otlp: OtlpSourceStatus
    alertmanager: AlertmanagerSourceStatus
    prometheus: PrometheusSourceStatus
    events: EventsSourceStatus


class IngestionStatusOut(BaseModel):
    generated_at: datetime
    has_any_data: bool
    sources: IngestionSources


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _latest(*values: datetime | None) -> datetime | None:
    present = [value for value in (_as_utc(item) for item in values) if value is not None]
    return max(present) if present else None


def _scalar(db: Session, statement, label: str):
    try:
        return db.scalar(statement)
    except Exception:
        logger.warning("ingestion status: %s lookup failed", label, exc_info=True)
        db.rollback()
        return None


def _exists(db: Session, entity, label: str) -> bool:
    return _scalar(db, select(entity.id).limit(1), label) is not None


def _display_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(netloc=parts.hostname + (f":{parts.port}" if parts.port else ""))) if parts.hostname else url


def _prometheus_reachable() -> bool | None:
    global _prometheus_check
    config = get_prometheus_config()
    if not config.base_url:
        return None
    now = time.monotonic()
    if _prometheus_check and _prometheus_check[1] == config.base_url and now - _prometheus_check[0] < PROMETHEUS_CHECK_TTL_SECONDS:
        return _prometheus_check[2]
    try:
        reachable = PrometheusQueryService(config.model_copy(update={"timeout_seconds": PROMETHEUS_CHECK_TIMEOUT_SECONDS})).test_connection()[0]
    except Exception:  # noqa: BLE001 - a status read never fails because Prometheus is down
        reachable = False
    _prometheus_check = (now, config.base_url, reachable)
    return reachable


def _last_change_event(db: Session) -> ChangeEventEntity | None:
    try:
        return db.execute(select(ChangeEventEntity).order_by(ChangeEventEntity.received_at.desc(), ChangeEventEntity.id.desc()).limit(1)).scalars().first()
    except Exception:  # noqa: BLE001
        logger.warning("Ingestion status: change events lookup failed", exc_info=True)
        db.rollback()
        return None


@router.get("/status", response_model=IngestionStatusOut)
def get_ingestion_status(db: Session = Depends(get_db)) -> IngestionStatusOut:
    now = datetime.now(timezone.utc)
    alert_config = get_alert_enrichment_config()

    otlp_last = _latest(
        otlp_last_received_at(),
        _scalar(db, select(func.max(OtlpPendingPointEntity.received_at)), "otlp pending points"),
        _scalar(
            db,
            select(func.max(AnalysisRunEntity.created_at)).where(AnalysisRunEntity.source_type == OTLP_RUN_SOURCE_TYPE),
            "otlp analysis runs",
        ),
    )
    alerts_last = _as_utc(_scalar(db, select(func.max(AlertEnrichmentEntity.created_at)), "alerts"))
    alerts_24h = _scalar(
        db,
        select(func.count()).select_from(AlertEnrichmentEntity).where(AlertEnrichmentEntity.created_at >= now - timedelta(hours=24)),
        "alerts 24h",
    )

    # Any trace of past activity counts, so an install that already has data never falls back to
    # the first-run panel (analysis runs cover CSV, demo, Prometheus and OTLP alike). A run that
    # failed produced nothing to look at, so on its own it does not end the first-run state.
    has_any_data = (
        otlp_last is not None
        or alerts_last is not None
        or _scalar(
            db,
            select(AnalysisRunEntity.id).where(AnalysisRunEntity.status != "failed").limit(1),
            "analysis runs",
        )
        is not None
        or _exists(db, FindingEntity, "findings")
    )

    prometheus_config = get_prometheus_config()
    last_event = _last_change_event(db)
    events_24h = _scalar(
        db,
        select(func.count()).select_from(ChangeEventEntity).where(ChangeEventEntity.received_at >= now - timedelta(hours=24)),
        "change events 24h",
    )
    scheduled_policies = _scalar(
        db,
        select(func.count()).select_from(AutonomousPolicyEntity).where(AutonomousPolicyEntity.enabled.is_(True)),
        "autonomous policies",
    )

    return IngestionStatusOut(
        generated_at=now,
        has_any_data=has_any_data,
        sources=IngestionSources(
            otlp=OtlpSourceStatus(endpoint_path=OTLP_ENDPOINT_PATH, last_received_at=otlp_last),
            alertmanager=AlertmanagerSourceStatus(
                endpoint_path=ALERTMANAGER_ENDPOINT_PATH,
                enabled=alert_config.enabled,
                token_required=bool(receiver_token_or_api_token(alert_config.receiver_token)),
                last_received_at=alerts_last,
                received_24h=int(alerts_24h or 0),
            ),
            prometheus=PrometheusSourceStatus(
                configured=bool(prometheus_config.base_url),
                url=_display_url(prometheus_config.base_url) if prometheus_config.base_url else None,
                reachable=_prometheus_reachable(),
                scheduled_policies=int(scheduled_policies or 0),
                alert_enrichment_enabled=alert_config.enabled,
            ),
            events=EventsSourceStatus(
                endpoint_path=EVENTS_ENDPOINT_PATH,
                token_required=bool(receiver_token_or_api_token(alert_config.events_token)),
                last_received_at=_as_utc(last_event.received_at) if last_event else None,
                received_24h=int(events_24h or 0),
                last_event=LastChangeEvent(
                    service=last_event.service,
                    type=last_event.event_type,
                    version=last_event.version,
                    env=last_event.env,
                    timestamp=_as_utc(last_event.timestamp),
                ) if last_event else None,
            ),
        ),
    )
