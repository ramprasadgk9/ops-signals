"""Alert receivers: Alertmanager webhook + a vendor-neutral generic endpoint.

Both return immediately (Alertmanager retries slow receivers) and enrich in the background.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.alerts.alertmanager import from_alertmanager, from_generic
from backend.app.alerts.auth import check_bearer_token
from backend.app.alerts.enrichment import AlertEnrichmentService
from backend.app.alerts.schemas import AlertmanagerWebhook, AlertReceiptOut, GenericAlertRequest, NormalizedAlert
from backend.app.config import AlertEnrichmentConfig, get_alert_enrichment_config, get_prometheus_connections
from backend.app.alerts.correlation import as_utc
from backend.app.models.db import get_db, get_session_local
from backend.app.models.entities import AlertEnrichmentEntity, OperationalCaseEntity
from backend.app.security import receiver_token_or_api_token

router = APIRouter(prefix="/api", tags=["alerts"])

_service: AlertEnrichmentService | None = None


def get_alert_enrichment_service() -> AlertEnrichmentService:
    # One instance per process so its analysis-concurrency limit is shared by every request.
    global _service
    if _service is None:
        _service = AlertEnrichmentService(
            get_alert_enrichment_config(),
            get_prometheus_connections,
            session_factory=lambda: get_session_local()(),
        )
    return _service


def require_receiver_token(
    authorization: str | None = Header(default=None),
    config: AlertEnrichmentConfig = Depends(get_alert_enrichment_config),
) -> None:
    check_bearer_token(authorization, receiver_token_or_api_token(config.receiver_token))


def _accept(
    alerts: list[NormalizedAlert],
    config: AlertEnrichmentConfig,
    service: AlertEnrichmentService,
    background_tasks: BackgroundTasks,
) -> AlertReceiptOut:
    if not config.enabled:
        # 200, not an error: Alertmanager would otherwise retry forever.
        return AlertReceiptOut(accepted=0, disabled=True)
    receipt, work = service.receive(alerts)
    for kind, enrichment_id in work:
        background_tasks.add_task(service.process, kind, enrichment_id)
    return receipt


@router.post("/integrations/alertmanager", status_code=202, response_model=AlertReceiptOut)
def receive_alertmanager(
    payload: AlertmanagerWebhook,
    background_tasks: BackgroundTasks,
    config: AlertEnrichmentConfig = Depends(get_alert_enrichment_config),
    service: AlertEnrichmentService = Depends(get_alert_enrichment_service),
    _: None = Depends(require_receiver_token),
) -> AlertReceiptOut:
    """Alertmanager webhook receiver. Add it as an extra receiver with `continue: true` so existing
    routes are untouched - see docs/design/alert-enrichment-plan.md."""
    return _accept(from_alertmanager(payload, config.service_labels), config, service, background_tasks)


TEST_ALERT_NAME = "OpsSignalsTestAlert"
TEST_ALERT_SOURCE = "test"


@router.post("/integrations/alertmanager/test", status_code=202, response_model=AlertReceiptOut)
def send_test_alert(
    background_tasks: BackgroundTasks,
    config: AlertEnrichmentConfig = Depends(get_alert_enrichment_config),
    service: AlertEnrichmentService = Depends(get_alert_enrichment_service),
) -> AlertReceiptOut:
    """The Integrations page's "Send test alert": one synthetic alert through the same receive,
    enrich and notify path a real one takes, so a single click proves the whole flow (including
    Slack, if configured). Unlike the receivers above this is not public - the API token applies.
    A fresh fingerprint per click, so a second test is never swallowed as a duplicate."""
    now = datetime.now(timezone.utc)
    alert = NormalizedAlert(
        source=TEST_ALERT_SOURCE,
        fingerprint=f"ops-signals-test-{uuid.uuid4().hex[:12]}",
        status="firing",
        alert_name=TEST_ALERT_NAME,
        service=None,
        severity="info",
        starts_at=now,
        ends_at=None,
        labels={"alertname": TEST_ALERT_NAME, "ops_signals_test": "true"},
        annotations={"summary": "Test alert sent from the Ops Signals Integrations page"},
    )
    return _accept([alert], config, service, background_tasks)


@router.post("/alerts", status_code=202, response_model=AlertReceiptOut)
def receive_generic_alert(
    payload: GenericAlertRequest,
    background_tasks: BackgroundTasks,
    config: AlertEnrichmentConfig = Depends(get_alert_enrichment_config),
    service: AlertEnrichmentService = Depends(get_alert_enrichment_service),
    _: None = Depends(require_receiver_token),
) -> AlertReceiptOut:
    """Vendor-neutral alert intake for sources other than Alertmanager."""
    return _accept([from_generic(payload, config.service_labels)], config, service, background_tasks)


class AlertChangeOut(BaseModel):
    """A change event matched to the alert (backend/app/alerts/correlation.py)."""

    id: int | None = None
    event_type: str | None = None
    version: str | None = None
    description: str | None = None
    author: str | None = None
    url: str | None = None
    timestamp: datetime | None = None
    minutes_before_anchor: float | None = None
    cluster: str | None = None


class AlertOut(BaseModel):
    """One received alert occurrence, as the UI lists it. The Slack message and the raw enrichment
    payload stay out - this is the index, not the audit record - but the parts the UI shows next to
    the alert come along: the start time used for deploy matching (backend/app/alerts/timing.py),
    the matched change events, and the finding's pod breakdown."""

    id: int
    source: str
    alert_name: str
    status: str
    service: str | None = None
    severity: str | None = None
    summary: str
    starts_at: datetime
    ends_at: datetime | None = None
    received_at: datetime
    labels: dict[str, str] = Field(default_factory=dict)
    generator_url: str | None = None
    analysis_status: str | None = None
    recommendation: str | None = None
    notify_status: str | None = None
    finding_id: int | None = None
    case_id: int | None = None
    timing: dict | None = None
    changes: list[AlertChangeOut] = Field(default_factory=list)
    change_window_before_minutes: int | None = None
    service_has_change_events: bool | None = None
    breakdown: dict | None = None


def _enrichment_fields(row: AlertEnrichmentEntity) -> dict:
    enrichment = row.enrichment_json or {}
    analysis = enrichment.get("analysis") or {}
    changes = enrichment.get("changes") or {}
    return {
        "timing": analysis.get("timing"),
        "changes": [AlertChangeOut(**{key: match.get(key) for key in AlertChangeOut.model_fields}) for match in changes.get("matches") or []],
        "change_window_before_minutes": changes.get("window_before_minutes"),
        "service_has_change_events": changes.get("service_has_any_events") if changes else None,
        "breakdown": (analysis.get("finding") or {}).get("breakdown"),
    }


def _alert_summary(row: AlertEnrichmentEntity) -> str:
    annotations = row.annotations_json or {}
    return annotations.get("summary") or annotations.get("description") or row.alert_name


@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(
    status: Literal["firing", "resolved"] | None = None,
    service: str | None = None,
    finding_id: int | None = None,
    since: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[AlertOut]:
    """Received alerts, newest first. Behind the API token like every read - only the POST
    receivers on these paths are public (backend/app/security.py)."""
    query = select(AlertEnrichmentEntity)
    if status:
        query = query.where(AlertEnrichmentEntity.status == status)
    if service:
        query = query.where(AlertEnrichmentEntity.service == service)
    if finding_id is not None:
        query = query.where(AlertEnrichmentEntity.finding_id == finding_id)
    if since:
        query = query.where(AlertEnrichmentEntity.created_at >= as_utc(since))
    rows = db.execute(
        query.order_by(AlertEnrichmentEntity.created_at.desc(), AlertEnrichmentEntity.id.desc()).limit(limit)
    ).scalars().all()

    finding_ids = {row.finding_id for row in rows if row.finding_id is not None}
    case_by_finding: dict[int, int] = {}
    if finding_ids:
        for case_id, case_finding_id in db.execute(
            select(OperationalCaseEntity.id, OperationalCaseEntity.finding_id)
            .where(OperationalCaseEntity.finding_id.in_(finding_ids))
            .order_by(OperationalCaseEntity.id)
        ).all():
            case_by_finding.setdefault(case_finding_id, case_id)

    return [
        AlertOut(
            id=row.id,
            source=row.source,
            alert_name=row.alert_name,
            status=row.status,
            service=row.service,
            severity=row.severity,
            summary=_alert_summary(row),
            starts_at=as_utc(row.starts_at),
            ends_at=as_utc(row.ends_at) if row.ends_at else None,
            received_at=as_utc(row.created_at),
            labels=row.labels_json or {},
            generator_url=row.generator_url,
            analysis_status=row.analysis_status,
            recommendation=row.recommendation,
            notify_status=row.notify_status,
            finding_id=row.finding_id,
            **_enrichment_fields(row),
            case_id=case_by_finding.get(row.finding_id) if row.finding_id is not None else None,
        )
        for row in rows
    ]
