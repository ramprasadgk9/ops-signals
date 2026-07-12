from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.capabilities.builtins import UNAVAILABLE_CAPABILITIES
from backend.app.models.db import get_db
from backend.app.models.entities import CapabilityEntity
from backend.app.models.api_schema import CapabilityOut

router = APIRouter(prefix="/api/capabilities", tags=["capabilities"])


@router.get("", response_model=list[CapabilityOut])
def list_capabilities(db: Session = Depends(get_db)) -> list[CapabilityOut]:
    caps = db.execute(select(CapabilityEntity)).scalars().all()
    return [
        CapabilityOut(
            id=cap.id,
            analyzer_id=cap.analyzer_id,
            title=cap.title,
            description=cap.description,
            enabled=cap.enabled,
            metadata_json={**cap.metadata_json, "status": "enabled" if cap.enabled else "disabled"},
        )
        for cap in caps
    ] + [
        CapabilityOut(
            id=item["id"],
            analyzer_id="not_installed",
            title=item["title"],
            description="Capability is planned but not installed in this deployment.",
            enabled=False,
            metadata_json={"status": item["status"], "supported_question_ids": []},
        )
        for item in UNAVAILABLE_CAPABILITIES
    ]
