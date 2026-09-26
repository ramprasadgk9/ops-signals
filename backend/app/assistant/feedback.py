"""Thumbs up / down on Ask Ops Signals answers.

A thumbs-down is the most direct evidence of a question the assistant gets wrong. The Docs check
page lists open ones, grouped by question, so whoever maintains the docs can fix the doc or keep
the question as a golden test.
"""

from __future__ import annotations

import re
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.assistant.schemas import AssistantFeedbackCreate, AssistantFeedbackOut, AssistantFeedbackUpdate, FlaggedQuestion
from backend.app.models.entities import AssistantFeedbackEntity

# Flagged questions listed at most; the oldest open rows beyond this many are not read.
MAX_FLAGGED_ROWS = 2000


def record_feedback(db: Session, payload: AssistantFeedbackCreate) -> AssistantFeedbackOut:
    row = AssistantFeedbackEntity(
        conversation_id=str(payload.conversation_id) if payload.conversation_id else None,
        question=payload.question.strip(),
        answer=payload.answer,
        helpful=payload.helpful,
        reason=None if payload.helpful else payload.reason,
        ai_synthesis_used=payload.ai_synthesis_used,
        cited_json=payload.cited[:10],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _out(row)


def update_feedback(db: Session, feedback_id: int, payload: AssistantFeedbackUpdate) -> AssistantFeedbackOut | None:
    row = db.get(AssistantFeedbackEntity, feedback_id)
    if row is None:
        return None
    if payload.reason is not None and not row.helpful:
        row.reason = payload.reason
    if payload.status is not None:
        row.status = payload.status
    db.commit()
    db.refresh(row)
    return _out(row)


def set_status(db: Session, feedback_ids: list[int], status: str) -> None:
    if not feedback_ids:
        return
    for row in db.execute(select(AssistantFeedbackEntity).where(AssistantFeedbackEntity.id.in_(feedback_ids))).scalars():
        row.status = status
    db.commit()


def flagged_questions(db: Session, limit: int = 50) -> list[FlaggedQuestion]:
    """Open thumbs-down answers grouped by question, most-flagged first."""
    rows = db.execute(
        select(AssistantFeedbackEntity)
        .where(AssistantFeedbackEntity.helpful.is_(False), AssistantFeedbackEntity.status == "open")
        .order_by(AssistantFeedbackEntity.created_at.desc())
        .limit(MAX_FLAGGED_ROWS)
    ).scalars().all()
    groups: dict[str, list[AssistantFeedbackEntity]] = {}
    for row in rows:
        groups.setdefault(_normalize(row.question), []).append(row)
    flagged = [
        FlaggedQuestion(
            # Newest phrasing first: rows come back newest first.
            question=members[0].question,
            count=len(members),
            reasons=dict(Counter(member.reason for member in members if member.reason).most_common()),
            cited=list(dict.fromkeys(ref for member in members for ref in (member.cited_json or [])[:1])),
            feedback_ids=[member.id for member in members],
            last_flagged_at=members[0].created_at,
        )
        for members in groups.values()
    ]
    flagged.sort(key=lambda item: (item.count, item.last_flagged_at), reverse=True)
    return flagged[:limit]


def _normalize(question: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[?.!]+$", "", question.strip().lower()))


def _out(row: AssistantFeedbackEntity) -> AssistantFeedbackOut:
    return AssistantFeedbackOut(id=row.id, question=row.question, helpful=row.helpful, reason=row.reason, status=row.status, created_at=row.created_at)
