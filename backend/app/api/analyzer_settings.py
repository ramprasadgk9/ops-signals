"""GET /api/analyzer-settings: the analyzer settings analysis runs use and where each comes from
(backend/app/services/analyzer_settings.py). Read-only; it only reads config files."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from backend.app.services.analyzer_settings import PROVIDERS, settings_in_use

router = APIRouter(prefix="/api/analyzer-settings", tags=["analyzer-settings"])


@router.get("")
def get_analyzer_settings(
    provider: str = Query(default="prometheus", description=f"Whose runs: {', '.join(sorted(PROVIDERS))}"),
    service: str | None = Query(default=None, max_length=256),
    metric: str | None = Query(default=None, max_length=512),
) -> dict[str, Any]:
    if provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"provider must be one of {sorted(PROVIDERS)}")
    return settings_in_use(provider, service, metric)
