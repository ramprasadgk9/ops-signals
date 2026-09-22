from __future__ import annotations

from fastapi import APIRouter, Response

from backend.app.otlp.metrics import render_metrics

router = APIRouter(tags=["metrics"])


@router.get("/api/metrics")
def get_metrics() -> Response:
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)
