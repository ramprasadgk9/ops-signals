from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import generate_latest

from backend.app.otlp.metrics import render_metrics
from backend.app.services.finding_metrics import REGISTRY as FINDINGS_REGISTRY

router = APIRouter(tags=["metrics"])


@router.get("/api/metrics")
def get_metrics() -> Response:
    """OTLP ingestion self-metrics, then active findings (docs/finding-metrics.md). Two registries,
    so the Settings page's OTLP snapshot never queries findings."""
    body, content_type = render_metrics()
    return Response(content=body + generate_latest(FINDINGS_REGISTRY), media_type=content_type)
