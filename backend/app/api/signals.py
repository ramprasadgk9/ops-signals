from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.api_schema import SignalOut
from backend.app.models.db import get_db
from backend.app.models.entities import SignalEntity

router = APIRouter(prefix="/api/signals", tags=["signals"])


def _to_signal_out(signal: SignalEntity) -> SignalOut:
    return SignalOut(
        id=signal.signal_id,
        signal_type=signal.signal_type,
        analyzer_id=signal.analyzer_id,
        metric_name=signal.metric_name,
        service=signal.service,
        severity=signal.severity,
        confidence=signal.confidence,
        importance_score=signal.importance_score,
        start_time=signal.start_time,
        end_time=signal.end_time,
        summary=signal.summary,
        evidence=signal.evidence_json or {},
        analysis_run_id=signal.analysis_run_id,
    )


@router.get("", response_model=list[SignalOut])
def list_signals(
    service: str | None = None,
    metric_name: str | None = None,
    severity: str | None = None,
    signal_type: str | None = None,
    analysis_run_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[SignalOut]:
    query = select(SignalEntity)
    if service:
        query = query.where(SignalEntity.service == service)
    if metric_name:
        query = query.where(SignalEntity.metric_name == metric_name)
    if severity:
        query = query.where(SignalEntity.severity == severity)
    if signal_type:
        query = query.where(SignalEntity.signal_type == signal_type)
    if analysis_run_id:
        query = query.where(SignalEntity.analysis_run_id == analysis_run_id)
    rows = db.execute(query.order_by(SignalEntity.importance_score.desc())).scalars().all()
    return [_to_signal_out(row) for row in rows]


@router.get("/{signal_id}", response_model=SignalOut)
def get_signal(signal_id: str, db: Session = Depends(get_db)) -> SignalOut:
    row = db.execute(select(SignalEntity).where(SignalEntity.signal_id == signal_id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="signal not found")
    return _to_signal_out(row)
