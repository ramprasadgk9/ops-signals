from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.api_schema import AnalysisRunOut
from backend.app.models.db import get_db
from backend.app.models.entities import AnalysisRunEntity

router = APIRouter(prefix="/api/analysis-runs", tags=["analysis-runs"])


@router.get("", response_model=list[AnalysisRunOut])
def list_analysis_runs(db: Session = Depends(get_db)) -> list[AnalysisRunOut]:
    runs = db.execute(select(AnalysisRunEntity).order_by(AnalysisRunEntity.created_at.desc())).scalars().all()
    return [
        AnalysisRunOut(
            id=run.id,
            source_type=run.source_type,
            provider=run.provider or "generic",
            service=run.service,
            metric_name=run.metric_name,
            start_time=run.start_time,
            end_time=run.end_time,
            sample_count=run.sample_count,
            status=run.status,
            created_at=run.created_at,
        )
        for run in runs
    ]


@router.get("/{run_id}", response_model=AnalysisRunOut)
def get_analysis_run(run_id: str, db: Session = Depends(get_db)) -> AnalysisRunOut:
    run = db.get(AnalysisRunEntity, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="analysis run not found")
    return AnalysisRunOut(
        id=run.id,
        source_type=run.source_type,
        provider=run.provider or "generic",
        service=run.service,
        metric_name=run.metric_name,
        start_time=run.start_time,
        end_time=run.end_time,
        sample_count=run.sample_count,
        status=run.status,
        created_at=run.created_at,
    )
