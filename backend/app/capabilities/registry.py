from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.app.capabilities.builtins import BUILTIN_CAPABILITIES
from backend.app.models.entities import CapabilityEntity, CapabilityQuestionEntity
from backend.app.questions.catalog import QUESTION_CATALOG


# Any fixed 64-bit number, unique to this lock among the app's advisory locks.
SEED_LOCK_KEY = 7_140_020_261


class CapabilityRegistry:
    def __init__(self, db: Session) -> None:
        self.db = db

    def ensure_seeded(self) -> None:
        """Syncs the built-in capabilities and their question links, in one transaction. Two
        backends on one database (run_all.sh and run_grafana_stack.sh both reload on every change)
        used to interleave the delete and re-insert of capability_questions and fail startup with a
        duplicate key; on Postgres the second now waits for the first."""
        self._lock_for_seeding()
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
        self.db.flush()

        self.db.query(CapabilityQuestionEntity).delete()
        self.db.flush()

        supported = {entry["id"] for entry in QUESTION_CATALOG}
        caps = self.db.execute(select(CapabilityEntity)).scalars().all()
        for cap in caps:
            for qid in cap.metadata_json.get("supported_question_ids", []):
                if qid in supported:
                    self.db.add(CapabilityQuestionEntity(capability_id=cap.id, question_id=qid))
        self.db.commit()

    def _lock_for_seeding(self) -> None:
        # Held until this transaction commits; SQLite serializes writers on its own.
        if self.db.get_bind().dialect.name == "postgresql":
            self.db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SEED_LOCK_KEY})

    def enabled_capabilities(self) -> list[CapabilityEntity]:
        return (
            self.db.execute(select(CapabilityEntity).where(CapabilityEntity.enabled.is_(True)))
            .scalars()
            .all()
        )
