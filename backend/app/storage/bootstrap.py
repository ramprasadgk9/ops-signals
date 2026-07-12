from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.capabilities.registry import CapabilityRegistry
from backend.app.models.entities import QuestionCatalogEntity
from backend.app.questions.catalog import QUESTION_CATALOG


def seed_reference_data(db: Session) -> None:
    existing = {row.id for row in db.execute(select(QuestionCatalogEntity)).scalars().all()}
    for question in QUESTION_CATALOG:
        if question["id"] not in existing:
            db.add(
                QuestionCatalogEntity(
                    id=str(question["id"]),
                    label=str(question["label"]),
                    description=str(question["description"]),
                    enabled=bool(question["enabled"]),
                    display_order=int(question["display_order"]),
                    created_at=datetime.utcnow(),
                )
            )
    db.commit()
    CapabilityRegistry(db).ensure_seeded()
