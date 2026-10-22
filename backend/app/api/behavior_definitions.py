from __future__ import annotations

from fastapi import APIRouter

from backend.app.behavior_intelligence.catalog import load_catalog
from backend.app.behavior_intelligence.schemas import BehaviorDefinitionOut, CatalogPatternOut
from backend.app.behavior_intelligence.service import BehaviorIntelligenceService

router = APIRouter(prefix="/api/behavior-definitions", tags=["behavior-definitions"])


@router.get("", response_model=list[BehaviorDefinitionOut])
def list_behavior_definitions() -> list[BehaviorDefinitionOut]:
    service = BehaviorIntelligenceService("config/behavior_definitions.d")
    return [BehaviorDefinitionOut(**definition) for definition in service.list_definitions()]


@router.get("/catalog", response_model=list[CatalogPatternOut])
def list_pattern_catalog() -> list[CatalogPatternOut]:
    """Known patterns in plain words: the shipped rules with their proof, and templates to start from."""
    service = BehaviorIntelligenceService("config/behavior_definitions.d")
    return [CatalogPatternOut(**entry) for entry in load_catalog("config/behavior_patterns_catalog.yml", service.definitions())]
