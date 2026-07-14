from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.entities import BehaviorFindingEntity


class BehaviorFindingRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def save(self, record: BehaviorFindingEntity) -> BehaviorFindingEntity:
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def list(self, definition_id: str | None = None, service: str | None = None, analysis_run_id: str | None = None) -> list[BehaviorFindingEntity]:
        query = select(BehaviorFindingEntity)
        if definition_id:
            query = query.where(BehaviorFindingEntity.definition_id == definition_id)
        if service:
            query = query.where(BehaviorFindingEntity.service == service)
        if analysis_run_id:
            query = query.where(BehaviorFindingEntity.analysis_run_id == analysis_run_id)
        rows = self.db.execute(query.order_by(BehaviorFindingEntity.created_at.desc())).scalars().all()
        return list(rows)
