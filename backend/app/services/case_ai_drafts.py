"""AI drafts for a case's Root Cause and Resolution tabs ("Draft from case").

The model only writes up what the case already holds: investigation notes, ticket comments, the
finding, the deploy matched to it and how similar past cases were fixed. It never decides a cause
on its own. Every draft comes back with the facts it was given (shown under the box, so the person
can check each claim), and a sentence naming a number, version or name not in those facts is
dropped before it is shown. Nothing here writes to the case: PATCH /rca and /resolution save.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ai.exceptions import AIError
from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.interfaces import LLMMessage, LLMRequest
from backend.app.ai.models import StructuredLLMService
from backend.app.config import AlertEnrichmentConfig
from backend.app.integrations.ticketing.service import CaseTicketing
from backend.app.memory.similarity_service import SimilarityService
from backend.app.models.entities import CaseTicketLinkEntity, FindingEntity, OperationalCaseEntity
from backend.app.services.finding_ai_wording import numbers_in, unknown_names, unknown_numbers
from backend.app.services.finding_changes import finding_changes
from backend.app.services.finding_plain import finding_plain, utc_text

logger = logging.getLogger(__name__)

RCA_INSTRUCTION = """You help an on-call engineer fill in the root cause of one incident case.

You get what the case already holds: the finding, the deploy matched to it, investigation notes,
ticket comments and how similar past cases were fixed. Write 1-3 sentences on the most likely cause.

Rules:
- Use only what the case says. The cause must come from a note, a ticket comment, the deploy or a
  similar past case; say which ("from the ticket", "case #118 had the same pattern").
- If no note, comment or similar case names a cause, describe what changed and when, and say the
  cause is not recorded yet. A restart or rollback that helped does not tell the cause: don't guess
  one (no "transient issue", "a problem within the pods" or similar).
- Say "may" or "likely". Never "definitely" or "confirmed".
- No numbers, versions, names or tickets that are not in the facts.
- Plain words, no statistics words. Return only the sentences."""

RESOLUTION_INSTRUCTION = """You help an on-call engineer fill in how one incident case was resolved.

You get the case's investigation notes, ticket comments, and the saved root cause and corrective
action if any. Write two short fields:

"outcome_summary": 1-2 sentences on what was done and what happened after.
"corrective_action": 1-2 sentences on what someone did, as the notes or comments say it. Only say
something was removed, changed or fixed if a note or comment says it was done; finding a cause is
not fixing it. If the problem stopped (for example after a rollback or a restart) but nothing says
the root cause itself was fixed, end with "Still open: " and what remains to fix.

Rules:
- Use only what the case says. Do not invent fixes, causes, numbers, versions or names.
- If the facts don't say, return null for that field.
- Plain words, no statistics words.

Return only JSON: {"outcome_summary": string|null, "corrective_action": string|null}"""

WRITEUP_INSTRUCTION = """You help an on-call engineer write the short write-up of one closed incident case,
for the next person who sees the same problem.

You get the case's saved root cause and resolution, its timeline and similar past cases. Write four
short fields, 1-2 sentences each:

"summary": what happened and what fixed it.
"likely_cause": the saved root cause in plain words, saying where it came from (a note, the ticket).
"seen_before": only if similar past cases are given: which one looks the same (by its #number) and
how it was fixed. Otherwise null.
"still_open": what is not fixed yet, if the resolution or notes say so (for example a rollback
stopped it but the bug is still in the code). Otherwise null.

Rules:
- Use only what the case says. Do not invent causes, fixes, numbers, versions or names.
- Only say something was removed, changed or fixed if the case says it was done.
- Don't write clock times; the timeline shows them. Durations given in the facts are fine.
- If a field has nothing from the facts, return null for it.
- Plain words, no statistics words.

Return only JSON: {"summary": string|null, "likely_cause": string|null, "seen_before": string|null, "still_open": string|null}"""

WRITEUP_LABELS = (("summary", "Summary"), ("likely_cause", "Likely cause"), ("seen_before", "Seen before"), ("still_open", "Still open"))

TIMEOUT_SECONDS = 20
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_BANNED = re.compile(r"\b(?:definitely|certainly|the cause is(?! not)|confirmed root cause|baseline|z-?score|anomal\w*|sigma|statistically)\b", re.IGNORECASE)
# Saying a fix was done that nobody recorded is the worst thing a resolution draft can do (tried
# with real models: "the validation was removed" after only a rollback). The word's stem must be in
# the case: "remov" allows "removed" when a note says "remove".
_ACTION = re.compile(
    r"\b(remov|fix|patch|chang|disabl|enabl|revert|increas|decreas|rais|lower|upgrad|downgrad|replac|scal|delet|rewr|redeploy|resiz|tun)\w*",
    re.IGNORECASE,
)
_COMMENT = re.compile(r"^-\s*\[(?P<author>[^\]]*)\]:\s*(?P<text>.+)$", re.DOTALL)
_DETAIL_CHARS = 160


@dataclass
class CaseFacts:
    """What the model is given, and the same facts as short items for the person to check."""

    lines: list[str] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    # Something someone found or did, beyond the finding itself; without it a draft is a guess.
    has_material: bool = False
    similar_case_ids: list[int] = field(default_factory=list)

    def add(self, line: str, kind: str, label: str, detail: str | None = None, *, material: bool = False) -> None:
        self.lines.append(line)
        self.sources.append({"kind": kind, "label": label, "detail": _short(detail)})
        self.has_material = self.has_material or material

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def rca_facts(
    case: OperationalCaseEntity,
    db: Session,
    *,
    ticketing: CaseTicketing | None,
    similarity: SimilarityService | None,
    change_config: AlertEnrichmentConfig | None,
) -> CaseFacts:
    facts = CaseFacts(lines=[f"Case title: {case.case_title}"])
    snapshot = case.finding_snapshot or {}
    finding = db.get(FindingEntity, case.finding_id) if case.finding_id else None
    _add_finding(facts, db, finding, snapshot)
    if finding is not None and change_config is not None:
        _add_deploy(facts, db, finding, change_config)
    _add_ticket(facts, db, case.id)
    _add_notes(facts, case)
    _add_comments(facts, case.id, ticketing)
    if similarity:
        _add_similar(facts, db, case.id, similarity)
    return facts


def resolution_facts(case: OperationalCaseEntity, db: Session, *, ticketing: CaseTicketing | None) -> CaseFacts:
    facts = CaseFacts(lines=[f"Case title: {case.case_title}"])
    _add_ticket(facts, db, case.id)
    _add_notes(facts, case)
    _add_comments(facts, case.id, ticketing)
    if case.root_cause_summary:
        facts.add(f"Saved root cause: {case.root_cause_summary}", "root_cause", "Saved root cause", case.root_cause_summary, material=True)
    if case.corrective_action:
        facts.add(f"Saved corrective action: {case.corrective_action}", "corrective_action", "Saved corrective action", case.corrective_action, material=True)
    return facts


def writeup_facts(
    case: OperationalCaseEntity,
    db: Session,
    *,
    timeline: dict[str, Any],
    similarity: SimilarityService | None,
) -> CaseFacts:
    """The saved root cause and resolution (material), the timeline and similar past cases."""
    facts = CaseFacts(lines=[f"Case title: {case.case_title}"])
    if case.root_cause_summary:
        facts.add(f"Saved root cause: {case.root_cause_summary}", "root_cause", "Saved root cause", case.root_cause_summary, material=True)
    if case.corrective_action:
        facts.add(f"Saved corrective action: {case.corrective_action}", "corrective_action", "Saved corrective action", case.corrective_action, material=True)
    if case.outcome_summary:
        facts.add(f"Saved outcome: {case.outcome_summary}", "corrective_action", "Saved outcome", case.outcome_summary, material=True)
    events = timeline.get("events") or []
    if events:
        lines = [f"- {_when(event['time'])}: {event['text']}" + (f" ({event['who']})" if event.get("who") else "") for event in events]
        facts.add("Timeline:\n" + "\n".join(lines), "timeline", "Timeline", f"{len(events)} events")
    if timeline.get("time_to_fix_minutes") is not None:
        facts.lines.append(f"Time to fix: {timeline['time_to_fix_minutes']} minutes from the first finding")
    if similarity:
        _add_similar(facts, db, case.id, similarity)
    return facts


class WriteupReply(BaseModel):
    summary: str | None = None
    likely_cause: str | None = None
    seen_before: str | None = None
    still_open: str | None = None


def write_writeup(ai_services: OptionalAIServices, facts: CaseFacts) -> str | None:
    """The write-up as labelled paragraphs, each checked; None when the call fails, the reply isn't
    the JSON asked for, or every paragraph was dropped."""
    request = LLMRequest(
        messages=[LLMMessage(role="system", content=WRITEUP_INSTRUCTION), LLMMessage(role="user", content=facts.text)],
        temperature=0.1,
        max_tokens=400,
        response_format="json",
        timeout_seconds=TIMEOUT_SECONDS,
    )
    try:
        structured = ai_services.structured or StructuredLLMService(ai_services.client)
        reply = structured.generate_structured(request, WriteupReply)
    except (AIError, ValidationError) as exc:
        logger.warning("Write-up draft failed: %s", exc)
        return None
    paragraphs = []
    for field_name, label in WRITEUP_LABELS:
        if field_name == "seen_before" and not facts.similar_case_ids:
            continue
        # "Still open" is advice ("fix the retry loop"), not a claim that something was done.
        text = check_draft(getattr(reply, field_name), facts.text, actions=field_name != "still_open")
        if text:
            paragraphs.append(f"{label}: {text}")
    return "\n\n".join(paragraphs) or None


def check_draft(text: str | None, facts_text: str, *, actions: bool = False) -> str | None:
    """The draft without any sentence that names a number, version or name not in the facts, or
    says it is certain; None when no sentence is left. With `actions` (the resolution fields), also
    without a sentence saying something was removed, fixed, changed... when the case never says so."""
    if not text or not text.strip():
        return None
    allowed = facts_text.lower()
    allowed_numbers = numbers_in(allowed)
    kept = []
    for sentence in _SENTENCE.split(" ".join(text.split())):
        problem = None
        if bad := unknown_numbers(sentence, allowed_numbers):
            problem = f"numbers not in the case: {bad}"
        elif bad := unknown_names(sentence, allowed):
            problem = f"names not in the case: {bad}"
        elif match := _BANNED.search(sentence):
            problem = f"a banned phrase: {match.group(0)!r}"
        elif actions and not sentence.lower().startswith("still open") and (bad := [stem for stem in _ACTION.findall(sentence) if stem.lower() not in allowed]):
            problem = f"an action not in the case: {bad}"
        if problem:
            logger.info("Case draft sentence dropped (%s): %r", problem, sentence[:160])
        else:
            kept.append(sentence)
    return " ".join(kept) or None


class ResolutionReply(BaseModel):
    outcome_summary: str | None = None
    corrective_action: str | None = None


def write_resolution(ai_services: OptionalAIServices, facts: CaseFacts) -> dict[str, str | None] | None:
    """Both resolution fields from one call, each checked. None when the call fails or the reply
    isn't the JSON asked for."""
    request = LLMRequest(
        messages=[LLMMessage(role="system", content=RESOLUTION_INSTRUCTION), LLMMessage(role="user", content=facts.text)],
        temperature=0.1,
        max_tokens=250,
        response_format="json",
        timeout_seconds=TIMEOUT_SECONDS,
    )
    try:
        structured = ai_services.structured or StructuredLLMService(ai_services.client)
        reply = structured.generate_structured(request, ResolutionReply)
    except (AIError, ValidationError) as exc:
        logger.warning("Resolution draft failed: %s", exc)
        return None
    return {
        "outcome_summary": check_draft(reply.outcome_summary, facts.text, actions=True),
        "corrective_action": check_draft(reply.corrective_action, facts.text, actions=True),
    }


def _add_finding(facts: CaseFacts, db: Session, finding: FindingEntity | None, snapshot: dict[str, Any]) -> None:
    service = snapshot.get("service") or (finding.service if finding else None)
    metric = snapshot.get("metric_name") or (finding.metric_name if finding else None)
    plain = None
    if finding is not None:
        try:
            plain = finding_plain(db, [finding]).get(finding.id)
        except Exception:  # noqa: BLE001 - the snapshot still describes the finding
            logger.warning("Plain wording for case finding %s failed", finding.id, exc_info=True)
            db.rollback()
    what = utc_text(plain["what"]) if plain and plain.get("what") else snapshot.get("summary") or ""
    headline = (plain or {}).get("headline") or snapshot.get("title") or metric or "Finding"
    facts.add(f"Finding on {service or 'unknown service'}, metric {metric or 'unknown'}: {headline}. {what}".strip(), "finding", f"Finding: {headline}", what)


def _add_deploy(facts: CaseFacts, db: Session, finding: FindingEntity, config: AlertEnrichmentConfig) -> None:
    changes = finding_changes(db, [finding], config).get(finding.id) or {}
    if changes.get("status") != "matched":
        return
    for match in changes.get("matches") or []:
        what = " ".join(part for part in (match.get("event_type"), match.get("version")) if part)
        when = _when(match.get("timestamp"))
        before = match.get("minutes_before_anchor")
        timing = f", {round(before)} minutes before the metric changed" if isinstance(before, (int, float)) and before >= 0 else ""
        facts.add(f"Change on {finding.service}: {what} at {when}{timing}. {match.get('description') or ''}".strip(), "deploy", f"Change: {what}", f"{when}{timing}", material=True)


def _add_ticket(facts: CaseFacts, db: Session, case_id: int) -> None:
    for key, provider in db.execute(select(CaseTicketLinkEntity.display_key, CaseTicketLinkEntity.provider).where(CaseTicketLinkEntity.case_id == case_id)).all():
        facts.add(f"Linked ticket: {key} ({provider})", "ticket", f"Ticket {key}")


def _add_notes(facts: CaseFacts, case: OperationalCaseEntity) -> None:
    for note in case.investigation_notes or []:
        text = (note.get("note") or "").strip()
        if text:
            when = _when(note.get("timestamp"))
            facts.add(f"Investigation note ({when}): {text}" if when else f"Investigation note: {text}", "note", f"Note{', ' + when if when else ''}", text, material=True)


def _add_comments(facts: CaseFacts, case_id: int, ticketing: CaseTicketing | None) -> None:
    if not ticketing:
        return
    try:
        comments = ticketing.get_external_comments_for_analysis(case_id)
    except Exception as exc:  # noqa: BLE001 - a ticket system being down must not block the draft
        logger.warning("Failed to fetch external comments for case %s: %s", case_id, exc)
        return
    for comment in comments:
        match = _COMMENT.match(comment.strip())
        author, text = (match.group("author"), match.group("text").strip()) if match else ("Team member", comment)
        facts.add(f"Ticket comment by {author}: {text}", "ticket_comment", f"Ticket comment, {author}", text, material=True)


def _add_similar(facts: CaseFacts, db: Session, case_id: int, similarity: SimilarityService) -> None:
    try:
        similar = similarity.find_similar_cases(case_id, db, top_k=3)
    except Exception:  # noqa: BLE001 - similar cases are extra
        logger.warning("Similar cases for case %s failed", case_id, exc_info=True)
        return
    for match in similar.matches if similar else []:
        if not match.root_cause_summary:
            continue
        fixed = f", fixed by: {match.corrective_action}" if match.corrective_action else ""
        facts.add(
            f"Similar past case #{match.case_id} ({match.service}, {match.metric_name}): root cause was: {match.root_cause_summary}{fixed}",
            "similar_case",
            f"Similar case #{match.case_id}",
            match.root_cause_summary,
            material=True,
        )
        facts.similar_case_ids.append(match.case_id)


def _when(iso: str | None) -> str:
    """'Oct 19, 22:54 UTC', or '' for a missing or unreadable time."""
    if not iso:
        return ""
    marker = f"[[time:{iso}]]"
    text = utc_text(marker)
    return "" if text == marker else text


def _short(text: str | None) -> str | None:
    if not text:
        return None
    text = " ".join(text.split())
    return text if len(text) <= _DETAIL_CHARS else text[: _DETAIL_CHARS - 1].rstrip() + "…"
