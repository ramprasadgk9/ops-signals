"""AI answer to "Why might it not have held?" on the fix-that-didn't-stick banner (fix_came_back.py).

The model gets the past case (cause, fix, outcome), how soon the problem came back, and the new
finding with any deploy matched to it. It lists possible reasons from those facts only; each reason
goes through the same check as Draft from case (case_ai_drafts.check_draft), so a reason naming a
number, name or fix that isn't in the facts is dropped. Nothing is saved.
"""

from __future__ import annotations

import logging

import re

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from backend.app.ai.exceptions import AIError
from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.interfaces import LLMMessage, LLMRequest
from backend.app.ai.models import StructuredLLMService
from backend.app.config import AlertEnrichmentConfig
from backend.app.memory.schemas import CameBackAfterFix
from backend.app.models.entities import FindingEntity, OperationalCaseEntity
from backend.app.services.case_ai_drafts import TIMEOUT_SECONDS, CaseFacts, _add_deploy, _add_finding, _add_notes, check_draft

logger = logging.getLogger(__name__)

MAX_REASONS = 3
# Tried with real models (gemma3:4b, llama3.1:8b): with a checklist of kinds of reasons in the
# prompt, both copied its lines ("A 'Change on' line") and claimed a deploy or a still-open cause the
# facts didn't have. So code picks the hints that apply to this case and the model words those; with
# no hint the model isn't asked (left to guess, it offered "not fully rolled out" and the like).
# A new deploy claimed with none matched; a deploy named in the past case's own cause is fine.
_NEW_DEPLOY = re.compile(r"\b(new|recent|latest|another)\s+(deploy|release|rollout|version)\w*|\b(deploy|release|rollout)\w*\s+(went out|was made|happened)", re.IGNORECASE)
_STILL_OPEN = re.compile(r"\bstill open\b", re.IGNORECASE)
_STOPGAP = re.compile(r"\b(roll(ed|ing)?[ -]?back|revert\w*|restart\w*)\b", re.IGNORECASE)

WHY_INSTRUCTION = """You help an on-call engineer. A problem came back soon after a past incident case
was marked fixed. Give up to three short possible reasons why that fix may not have held.

You get the past case (its saved cause, fix and outcome), how many days later the problem came back,
the new problem, and "Hint" lines pointing at facts that may explain it. Turn each hint into a
reason in your own words, naming what it rests on.

Rules:
- One sentence per reason. Say "may" or "possibly". Never "definitely" or "confirmed".
- Use only the facts. No numbers, versions, names, deploys or fixes that are not in them.
- If the facts give no reason, return an empty list.
- Plain words, no statistics words.

Return only JSON: {"reasons": [string]}"""


class WhyReply(BaseModel):
    reasons: list[str] = []


def why_facts(
    db: Session,
    came_back: CameBackAfterFix,
    *,
    finding: FindingEntity | None,
    case: OperationalCaseEntity | None = None,
    change_config: AlertEnrichmentConfig | None,
) -> CaseFacts:
    """The past case first (material: its cause and fix), then the new problem."""
    past = db.get(OperationalCaseEntity, came_back.case_id)
    facts = CaseFacts(lines=[f"Past case #{came_back.case_id}: {came_back.title}. It was marked fixed and the problem came back {came_back.days} days later."])
    facts.sources.append({"kind": "similar_case", "label": f"Case #{came_back.case_id}", "detail": came_back.title})
    if past is not None:
        if past.root_cause_summary:
            facts.add(f"Past case saved root cause: {past.root_cause_summary}", "root_cause", f"Case #{past.id} root cause", past.root_cause_summary, material=True)
        if past.corrective_action:
            facts.add(f"Past case saved fix: {past.corrective_action}", "corrective_action", f"Case #{past.id} fix", past.corrective_action, material=True)
        if past.outcome_summary:
            facts.add(f"Past case outcome: {past.outcome_summary}", "corrective_action", f"Case #{past.id} outcome", past.outcome_summary)
    snapshot = (case.finding_snapshot if case is not None else None) or {}
    if finding is not None or snapshot:
        _add_finding(facts, db, finding, snapshot)
    if finding is not None and change_config is not None:
        _add_deploy(facts, db, finding, change_config)
    if case is not None:
        _add_notes(facts, case)
    _add_hints(facts, came_back)
    return facts


def _add_hints(facts: CaseFacts, came_back: CameBackAfterFix) -> None:
    """Only hints the facts back up; they aren't sources (the lines they point at already are)."""
    if came_back.still_open:
        facts.lines.append(f"Hint: the past case said this was still open: {came_back.still_open}")
    if _STOPGAP.search(came_back.fix):
        facts.lines.append(f"Hint: the past fix ({came_back.fix}) stops a problem but can leave its cause in place.")
    if any(source["kind"] == "deploy" for source in facts.sources):
        facts.lines.append("Hint: a deploy went out on this service shortly before the problem came back (the Change line).")


def write_why(ai_services: OptionalAIServices, facts: CaseFacts) -> list[str] | None:
    """Checked reasons; [] without asking when no hint applies; None when the call fails or the
    reply isn't the JSON asked for."""
    if not any(line.startswith("Hint: ") for line in facts.lines):
        return []
    request = LLMRequest(
        messages=[LLMMessage(role="system", content=WHY_INSTRUCTION), LLMMessage(role="user", content=facts.text)],
        temperature=0.1,
        max_tokens=300,
        response_format="json",
        timeout_seconds=TIMEOUT_SECONDS,
    )
    try:
        structured = ai_services.structured or StructuredLLMService(ai_services.client)
        reply = structured.generate_structured(request, WhyReply)
    except (AIError, ValidationError) as exc:
        logger.warning("Fix came-back reasons failed: %s", exc)
        return None
    has_deploy = any(source["kind"] == "deploy" for source in facts.sources)
    has_still_open = bool(_STILL_OPEN.search(facts.text))
    reasons = []
    for reason in reply.reasons:
        if (not has_deploy and _NEW_DEPLOY.search(reason)) or (not has_still_open and _STILL_OPEN.search(reason)):
            logger.info("Fix came-back reason dropped (deploy or still-open claim not in the facts): %r", reason[:160])
            continue
        if checked := check_draft(reason, facts.text, actions=True):
            reasons.append(checked[0].upper() + checked[1:])
    return reasons[:MAX_REASONS]
