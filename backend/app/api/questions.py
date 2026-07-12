from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.db import get_db
from backend.app.models.entities import CapabilityEntity, QuestionCatalogEntity
from backend.app.questions.composer import AnswerComposer
from backend.app.questions.router import QuestionRouter
from backend.app.questions.schema import AvailableQuestion, Question, QuestionAnswerRequest, QuestionAnswerResponse

router = APIRouter(prefix="/api/questions", tags=["questions"])


@router.get("", response_model=list[Question])
def list_questions(db: Session = Depends(get_db)) -> list[Question]:
    rows = db.execute(select(QuestionCatalogEntity).where(QuestionCatalogEntity.enabled.is_(True)).order_by(QuestionCatalogEntity.display_order.asc())).scalars().all()
    return [
        Question(
            id=q.id,
            label=q.label,
            description=q.description,
            enabled=q.enabled,
            display_order=q.display_order,
        )
        for q in rows
    ]


@router.get("/available", response_model=list[AvailableQuestion])
def available_questions(
    service: str,
    metric_name: str,
    analysis_run_id: str,
    db: Session = Depends(get_db),
) -> list[AvailableQuestion]:
    questions = list_questions(db)
    caps = db.execute(select(CapabilityEntity).where(CapabilityEntity.enabled.is_(True))).scalars().all()
    out: list[AvailableQuestion] = []
    for q in questions:
        contributors = [
            cap.title
            for cap in caps
            if q.id in cap.metadata_json.get("supported_question_ids", [])
        ]
        out.append(
            AvailableQuestion(
                **q.model_dump(),
                contributors=contributors,
                available=len(contributors) > 0,
            )
        )
    return [row for row in out if row.available]


@router.post("/answer", response_model=QuestionAnswerResponse)
def answer_question(payload: QuestionAnswerRequest, db: Session = Depends(get_db)) -> QuestionAnswerResponse:
    routed = QuestionRouter(db).route(
        question_id=payload.question_id,
        service=payload.service,
        metric_name=payload.metric_name,
        analysis_run_id=payload.analysis_run_id,
    )
    signal_dicts = [
        {
            "id": sig.signal_id,
            "signal_type": sig.signal_type,
            "analyzer_id": sig.analyzer_id,
            "severity": sig.severity,
            "confidence": sig.confidence,
            "importance_score": sig.importance_score,
            "summary": sig.summary,
            "evidence": sig.evidence_json or {},
        }
        for sig in routed.signals
    ]
    return AnswerComposer().compose(payload.question_id, signal_dicts)
