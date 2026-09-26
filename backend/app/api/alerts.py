"""Alert receivers: Alertmanager webhook + a vendor-neutral generic endpoint.

Both return immediately (Alertmanager retries slow receivers) and enrich in the background.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Header

from backend.app.alerts.alertmanager import from_alertmanager, from_generic
from backend.app.alerts.auth import check_bearer_token
from backend.app.alerts.enrichment import AlertEnrichmentService
from backend.app.alerts.schemas import AlertmanagerWebhook, AlertReceiptOut, GenericAlertRequest, NormalizedAlert
from backend.app.config import AlertEnrichmentConfig, get_alert_enrichment_config, get_prometheus_config
from backend.app.models.db import get_session_local
from backend.app.security import receiver_token_or_api_token

router = APIRouter(prefix="/api", tags=["alerts"])

_service: AlertEnrichmentService | None = None


def get_alert_enrichment_service() -> AlertEnrichmentService:
    # One instance per process so its analysis-concurrency limit is shared by every request.
    global _service
    if _service is None:
        _service = AlertEnrichmentService(
            get_alert_enrichment_config(),
            get_prometheus_config(),
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
