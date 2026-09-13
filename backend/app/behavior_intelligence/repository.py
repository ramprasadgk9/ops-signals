from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.entities import BehaviorFindingEntity

# How long an ongoing behavior stays "the same incident" for dedup purposes — a fresh match
# within this window of the last one bumps occurrence_count instead of inserting a new row.
# Chosen to comfortably span typical autonomous-monitoring polling intervals (seconds to tens of
# minutes) without merging two genuinely separate incidents that happen to recur days apart.
DEDUP_WINDOW = timedelta(hours=2)


class BehaviorFindingRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def find_recent_match(self, definition_id: str, service: str | None, now: datetime | None = None) -> BehaviorFindingEntity | None:
        now = now or datetime.utcnow()
        query = select(BehaviorFindingEntity).where(
            BehaviorFindingEntity.definition_id == definition_id,
            BehaviorFindingEntity.service == service,
            BehaviorFindingEntity.last_seen_at >= now - DEDUP_WINDOW,
        ).order_by(BehaviorFindingEntity.last_seen_at.desc())
        return self.db.execute(query).scalars().first()

    def save_or_bump(self, record: BehaviorFindingEntity) -> BehaviorFindingEntity:
        """Inserts a new finding, unless an ongoing match for the same definition+service was
        seen within DEDUP_WINDOW — in which case that existing row's occurrence_count and
        last_seen_at (plus its facts/confidence, so the displayed evidence reflects the latest
        evaluation) are updated instead. Without this, a condition that stays true across many
        consecutive analysis runs would create a new row every single run — confirmed as a real
        gap before this existed, not a hypothetical one."""
        existing = self.find_recent_match(record.definition_id, record.service)
        if existing is not None:
            existing.occurrence_count += 1
            existing.last_seen_at = datetime.utcnow()
            existing.facts_json = record.facts_json
            existing.matched_conditions_json = record.matched_conditions_json
            existing.confidence = record.confidence
            existing.correlation_json = record.correlation_json
            existing.analysis_run_id = record.analysis_run_id
            self.db.add(existing)
            self.db.commit()
            self.db.refresh(existing)
            return existing
        return self.save(record)

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
