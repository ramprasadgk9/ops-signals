from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.db import get_db
from backend.app.models.entities import NormalizedPoint
from backend.app.services.run_points import run_points_filter

router = APIRouter(prefix="/api/timeseries", tags=["timeseries"])


@router.get("")
def get_timeseries(
    service: str,
    metric_name: str,
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    analysis_run_id: str | None = Query(default=None),
    cluster: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(NormalizedPoint).where(
        NormalizedPoint.service == service,
        NormalizedPoint.metric_name == metric_name,
    )
    if start_time:
        query = query.where(NormalizedPoint.timestamp >= start_time)
    if end_time:
        query = query.where(NormalizedPoint.timestamp <= end_time)
    if analysis_run_id:
        query = query.where(run_points_filter(db, analysis_run_id))
    if cluster:
        query = query.where(NormalizedPoint.cluster == cluster)
    points = db.execute(query.order_by(NormalizedPoint.timestamp.asc())).scalars().all()
    return [
        {
            "timestamp": p.timestamp,
            "value": p.value,
            "service": p.service,
            "metric_name": p.metric_name,
            "cluster": p.cluster,
            "analysis_run_id": p.analysis_run_id,
        }
        for p in points
    ]
