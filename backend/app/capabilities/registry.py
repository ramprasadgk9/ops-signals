from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.capabilities.builtins import BUILTIN_CAPABILITIES
from backend.app.models.entities import CapabilityEntity, CapabilityQuestionEntity
from backend.app.questions.catalog import QUESTION_CATALOG


class CapabilityRegistry:
    def __init__(self, db: Session) -> None:
        self.db = db

    def ensure_seeded(self) -> None:
        existing = {
            row for row in self.db.execute(select(CapabilityEntity.id)).scalars().all()
        }
        for capability in BUILTIN_CAPABILITIES:
            if capability.id not in existing:
                self.db.add(
                    CapabilityEntity(
                        id=capability.id,
                        analyzer_id=capability.analyzer_id,
                        title=capability.title,
                        description=capability.description,
                        enabled=capability.enabled,
                        metadata_json={"supported_question_ids": capability.supported_question_ids},
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow(),
                    )
                )
        self.db.commit()

        self.db.query(CapabilityQuestionEntity).delete()
        self.db.commit()

        supported = {entry["id"] for entry in QUESTION_CATALOG}
        caps = self.db.execute(select(CapabilityEntity)).scalars().all()
        for cap in caps:
            for qid in cap.metadata_json.get("supported_question_ids", []):
                if qid in supported:
                    self.db.add(CapabilityQuestionEntity(capability_id=cap.id, question_id=qid))
        self.db.commit()

    def enabled_capabilities(self) -> list[CapabilityEntity]:
        return (
            self.db.execute(select(CapabilityEntity).where(CapabilityEntity.enabled.is_(True)))
            .scalars()
            .all()
        )
