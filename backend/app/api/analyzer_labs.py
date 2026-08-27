from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.models.db import get_db
from backend.app.models.entities import AnalyzerConfigSuggestionEntity

router = APIRouter(prefix="/api/analyzer-labs", tags=["analyzer-labs"])

PassFailStatus = Literal["pass", "fail", "unknown"]


class AnalyzerConfigSuggestionIn(BaseModel):
    analyzer_id: str = Field(min_length=1, max_length=64)
    lab_name: str = Field(min_length=1, max_length=128)
    suggestion_name: str = Field(min_length=1, max_length=256)
    yaml_text: str = Field(min_length=1)
    implementation_json: dict = Field(default_factory=dict)
    finding_rules_json: dict = Field(default_factory=dict)
    benchmark_summary_json: dict = Field(default_factory=dict)
    pass_fail_status: PassFailStatus = "unknown"
    created_by: str = Field(default="local", max_length=128)


class AnalyzerConfigSuggestionOut(AnalyzerConfigSuggestionIn):
    id: int
    created_at: datetime


def _to_out(row: AnalyzerConfigSuggestionEntity) -> AnalyzerConfigSuggestionOut:
    return AnalyzerConfigSuggestionOut(
        id=row.id,
        analyzer_id=row.analyzer_id,
        lab_name=row.lab_name,
        suggestion_name=row.suggestion_name,
        yaml_text=row.yaml_text,
        implementation_json=row.implementation_json or {},
        finding_rules_json=row.finding_rules_json or {},
        benchmark_summary_json=row.benchmark_summary_json or {},
        pass_fail_status=row.pass_fail_status or "unknown",
        created_by=row.created_by or "local",
        created_at=row.created_at,
    )


@router.get("/config-suggestions", response_model=list[AnalyzerConfigSuggestionOut])
def list_config_suggestions(
    analyzer_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[AnalyzerConfigSuggestionOut]:
    stmt = select(AnalyzerConfigSuggestionEntity).order_by(AnalyzerConfigSuggestionEntity.created_at.desc())
    if analyzer_id:
        stmt = stmt.where(AnalyzerConfigSuggestionEntity.analyzer_id == analyzer_id)
    rows = db.execute(stmt).scalars().all()
    return [_to_out(row) for row in rows]


@router.post("/config-suggestions", response_model=AnalyzerConfigSuggestionOut)
def create_config_suggestion(
    payload: AnalyzerConfigSuggestionIn,
    db: Session = Depends(get_db),
) -> AnalyzerConfigSuggestionOut:
    row = AnalyzerConfigSuggestionEntity(
        analyzer_id=payload.analyzer_id,
        lab_name=payload.lab_name,
        suggestion_name=payload.suggestion_name,
        yaml_text=payload.yaml_text,
        implementation_json=payload.implementation_json,
        finding_rules_json=payload.finding_rules_json,
        benchmark_summary_json=payload.benchmark_summary_json,
        pass_fail_status=payload.pass_fail_status,
        created_by=payload.created_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.delete("/config-suggestions/{suggestion_id}", response_model=dict)
def delete_config_suggestion(suggestion_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(AnalyzerConfigSuggestionEntity, suggestion_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Analyzer config suggestion not found")
    db.delete(row)
    db.commit()
    return {"deleted": 1}


@router.delete("/config-suggestions", response_model=dict)
def clear_config_suggestions(
    analyzer_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    stmt = delete(AnalyzerConfigSuggestionEntity)
    if analyzer_id:
        stmt = stmt.where(AnalyzerConfigSuggestionEntity.analyzer_id == analyzer_id)
    result = db.execute(stmt)
    db.commit()
    return {"deleted": result.rowcount or 0}
