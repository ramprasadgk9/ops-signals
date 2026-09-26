"""Example questions for the Ask Ops Signals first screen, built from what this install has analysed.

Fixed examples ("What caused checkout CPU trend?") name things most installs don't have and come
back empty on a fresh one. These name the newest finding, case and busiest service, so clicking
one finds evidence; with nothing analysed there are none, and the page offers a next step instead.
Each is worded to hit the keyword router's routes for its evidence ("finding", "case", "changed").
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.entities import BehaviorFindingEntity, FindingEntity, OperationalCaseEntity

# Longest title quoted in a question; longer ones are cut at a word boundary.
MAX_TITLE_CHARS = 60
# Recent findings looked at to pick the service most of them are about.
RECENT_FINDINGS = 50
PLACEHOLDER_SERVICES = frozenset({"unknown", "none", "null", "n/a", "-"})


class StarterQuestions(BaseModel):
    has_data: bool
    questions: list[str] = Field(default_factory=list)


def starter_questions(db: Session) -> StarterQuestions:
    findings = db.execute(select(FindingEntity).order_by(FindingEntity.created_at.desc()).limit(RECENT_FINDINGS)).scalars().all()
    case = db.execute(select(OperationalCaseEntity).order_by(OperationalCaseEntity.updated_at.desc()).limit(1)).scalars().first()
    has_behaviors = bool(db.execute(select(func.count()).select_from(BehaviorFindingEntity)).scalar())
    if not findings and case is None and not has_behaviors:
        return StarterQuestions(has_data=False)

    questions: list[str] = []
    services = Counter(finding.service for finding in findings if _real_service(finding.service))
    if services:
        # Most findings among the recent ones; ties go to the one seen most recently.
        top = max(services.values())
        service = next(finding.service for finding in findings if _real_service(finding.service) and services[finding.service] == top)
        questions.append(f"What changed recently on {service}?")
    if findings:
        questions.append(f'Tell me about the finding "{_shorten(findings[0].title)}"')
    if case is not None:
        questions.append(f'Have we seen a case like "{_shorten(case.case_title)}" before?')
    if findings:
        questions.append("Did any metric stop reporting?")
    if has_behaviors:
        questions.append("Which behavior patterns were detected?")
    return StarterQuestions(has_data=True, questions=questions[:4])


def _real_service(service: str | None) -> bool:
    # The pipeline stores "unknown" for a series with no service label; "What changed recently on
    # unknown?" is not a question anyone would ask.
    return bool(service) and service.strip().lower() not in PLACEHOLDER_SERVICES


def _shorten(title: str) -> str:
    title = " ".join(title.split()).rstrip(".")
    if len(title) <= MAX_TITLE_CHARS:
        return title
    return title[:MAX_TITLE_CHARS].rsplit(" ", 1)[0].rstrip(",;:-") + "…"
