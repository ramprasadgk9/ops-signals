from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from backend.app.models.db import get_db
from backend.app.models.entities import NormalizedPoint

router = APIRouter(prefix="/api", tags=["catalog"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/services")
def list_services(db: Session = Depends(get_db)) -> list[str]:
    rows = db.execute(select(distinct(NormalizedPoint.service))).all()
    return [row[0] for row in rows if row[0]]


@router.get("/services/{service}/metrics")
def list_metrics(service: str, db: Session = Depends(get_db)) -> list[str]:
    rows = db.execute(
        select(distinct(NormalizedPoint.metric_name)).where(NormalizedPoint.service == service)
    ).all()
    return [row[0] for row in rows if row[0]]
