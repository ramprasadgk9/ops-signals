from __future__ import annotations

from fastapi import APIRouter

from backend.app.behavior_intelligence.schemas import BehaviorDefinitionOut
from backend.app.behavior_intelligence.service import BehaviorIntelligenceService

router = APIRouter(prefix="/api/behavior-definitions", tags=["behavior-definitions"])


@router.get("", response_model=list[BehaviorDefinitionOut])
def list_behavior_definitions() -> list[BehaviorDefinitionOut]:
    service = BehaviorIntelligenceService("config/behavior_definitions.yml")
    return [BehaviorDefinitionOut(**definition) for definition in service.list_definitions()]
