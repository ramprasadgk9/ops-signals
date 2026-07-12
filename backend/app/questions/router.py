from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.entities import CapabilityEntity, SignalEntity


@dataclass(slots=True)
class RoutedSignals:
    question_id: str
    analyzer_ids: list[str]
    capability_ids: list[str]
    signals: list[SignalEntity]


class QuestionRouter:
    def __init__(self, db: Session) -> None:
        self.db = db

    def route(
        self,
        question_id: str,
        service: str,
        metric_name: str,
        analysis_run_id: str,
    ) -> RoutedSignals:
        capabilities = (
            self.db.execute(
                select(CapabilityEntity).where(
                    CapabilityEntity.enabled.is_(True),
                )
            )
            .scalars()
            .all()
        )
        selected = [
            cap
            for cap in capabilities
            if question_id in cap.metadata_json.get("supported_question_ids", [])
        ]
        analyzer_ids = [cap.analyzer_id for cap in selected]
        query = select(SignalEntity).where(
            SignalEntity.service == service,
            SignalEntity.metric_name == metric_name,
            SignalEntity.analysis_run_id == analysis_run_id,
        )
        if analyzer_ids:
            query = query.where(SignalEntity.analyzer_id.in_(analyzer_ids))
        signals = self.db.execute(query).scalars().all()
        return RoutedSignals(
            question_id=question_id,
            analyzer_ids=analyzer_ids,
            capability_ids=[cap.id for cap in selected],
            signals=signals,
        )
