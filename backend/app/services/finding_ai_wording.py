"""AI wording for a finding's details: "Why it matters", "What to check" and "Happened with" written
for this metric and service, instead of the one sentence its template gives every finding of that
kind (config/finding_templates.yaml, finding_plain.py).

Additive and optional, like ai_summary: the template wording is never changed, and a missing AI
provider, a failed call or a rejected line just means that line keeps the template. "Why" replaces
the template's sentence; "check" and "related" are one extra sentence after the template's, so the
template's facts (deploy window, the linked finding) always stay.

Each line the model writes is checked against the facts it was given before it is kept: no number,
name, time or statistics word that isn't in them. Saved once per finding (findings.ai_wording), so
the model runs on the first open only.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from pydantic import BaseModel, ValidationError

from backend.app.ai.exceptions import AIError
from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.interfaces import LLMMessage, LLMRequest
from backend.app.ai.models import StructuredLLMService
from backend.app.services.finding_plain import load_wording, metric_meaning, utc_text

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You write short, plain-language notes for an on-call engineer looking at one monitoring finding.

You get the finding's facts as JSON. Write up to three things:

1. "why": 1-2 sentences on why this matters for THIS metric and THIS service.
   Say what the metric most likely measures, judged from its name, unit and service,
   and what the change means for the people or systems that depend on it.
   If a stuck or unchanging value is normal for this kind of metric (a configured
   limit, a replica count, a version number), say so.

2. "check_extra": ONE extra thing to look at, beyond the template's check that is
   already shown. Make it specific to this metric. Do not repeat the template's check.

3. "related_extra": only if "related" is given. ONE sentence on what it often means
   when these two metrics change at the same moment. Never say one caused the other.

If "write_why" is false, return null for "why": the template already explains that kind of
metric. Never define a metric you are unsure of. p95 means 95 out of 100 requests were faster
than this value; it is not the slowest or the average.

Rules:
- "check_extra" must name something specific to look at for this metric or kind of finding.
  Never generic advice such as checking logs, dashboards, monitoring or network connectivity,
  and never something already in the template's check.
- Do not guess why the value changed or what the service is doing; say what it can mean.
- Use only the facts given. Do not add numbers, services, metrics, versions, people
  or tools that are not in the facts.
- Do not write times or dates; the page already shows them.
- You may name the metric by its plain name or its exact name, as given.
- Say "may", "often" or "can". Never "the cause is", "definitely" or "root cause".
- Everyday words. No statistics words such as baseline, z-score, anomaly, variance,
  deviation, sigma or confidence.
- If you have nothing more specific than the template, return null for that field.
  A null is better than a vague sentence.
- Each value is at most 2 sentences and 45 words.

Return only JSON: {"why": string|null, "check_extra": string|null, "related_extra": string|null}"""

MAX_WORDS = 45
MIN_WORDS = 4
# Close to the template it would replace or follow: adds nothing.
SAME_AS_TEMPLATE = 0.85
TIMEOUT_SECONDS = 20

_NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*")
# Names a model could invent: snake_case or dotted identifiers, and versions such as v1.4.2.
_IDENTIFIER = re.compile(r"\b(?:[A-Za-z]+[A-Za-z0-9]*(?:[_.][A-Za-z0-9]+)+|v\d+(?:\.\d+)+)\b")
_TIME = re.compile(r"\b\d{1,2}:\d{2}\b|\b(?:AM|PM|UTC)\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2}\b")
_BANNED = re.compile(
    r"\b(?:root cause|definitely|caused by|the cause is|baseline|z-?score|anomal\w*|variance|deviation|sigma|confidence|statistically)\b",
    re.IGNORECASE,
)
_WORD = re.compile(r"[A-Za-z]{2,}")
_ABBREVIATIONS = {"e.g", "i.e", "etc"}


class AIWordingReply(BaseModel):
    why: str | None = None
    check_extra: str | None = None
    related_extra: str | None = None


def wording_facts(metric_name: str, service: str | None, plain: dict[str, Any]) -> dict[str, Any]:
    """What the model is told about the finding: only what the card already says, plus what the
    metric is known to be. Time markers read as UTC so the model can follow the story."""
    wording = load_wording()
    meaning = metric_meaning(metric_name, wording) if wording else None
    related = plain.get("related") or []
    return {
        "kind": plain.get("kind"),
        "badge": plain.get("badge_label"),
        "headline": plain.get("headline"),
        "what": utc_text(plain.get("what") or ""),
        "metric_name": metric_name,
        "plain_name": meaning.plain_name if meaning else metric_name,
        "concept": meaning.concept if meaning else None,
        "unit": meaning.unit if meaning else None,
        "service": service,
        "service_about": plain.get("service_about"),
        "service_importance": plain.get("service_importance"),
        "target": utc_text(plain["target"]) if plain.get("target") else None,
        "template_why": utc_text(plain["why"]) if plain.get("why") else None,
        "template_check": utc_text(plain["check"]) if plain.get("check") else None,
        "related": utc_text(related[0]["text"]) if related and related[0].get("text") else None,
        # Small models rewrite a known metric's why worse than the template (tried on real
        # findings: wrong p95 meaning, guessed causes), so only a metric of unknown meaning gets one.
        "write_why": not (meaning and meaning.concept),
    }


def check_line(text: str | None, facts: dict[str, Any], template: str | None) -> str | None:
    """The line as written, or None when it fails a check (logged): it then keeps the template."""
    if not text or not text.strip():
        return None
    line = " ".join(text.split())
    allowed = " ".join(str(value) for value in facts.values() if value).lower()
    allowed_numbers = {_normal_number(number) for number in _NUMBER.findall(allowed)}
    words = len(_WORD.findall(line))
    problem = None
    if words < MIN_WORDS or words > MAX_WORDS:
        problem = f"{words} words"
    elif bad := [number for number in _NUMBER.findall(line) if _normal_number(number) not in allowed_numbers]:
        problem = f"numbers not in the facts: {bad}"
    elif bad := [name for name in _IDENTIFIER.findall(line) if name.lower() not in allowed and name.lower() not in _ABBREVIATIONS]:
        problem = f"names not in the facts: {bad}"
    elif match := _TIME.search(line):
        problem = f"a time: {match.group(0)!r}"
    elif match := _BANNED.search(line):
        problem = f"a banned phrase: {match.group(0)!r}"
    elif template and SequenceMatcher(None, line.lower(), template.lower()).ratio() >= SAME_AS_TEMPLATE:
        problem = "same as the template"
    if problem:
        logger.info("AI wording line dropped (%s): %r", problem, line[:160])
        return None
    return line


def _normal_number(number: str) -> str:
    return number.replace(",", "").rstrip("0").rstrip(".") if "." in number else number.replace(",", "")


def write_ai_wording(ai_services: OptionalAIServices, facts: dict[str, Any]) -> dict[str, Any] | None:
    """One model call for all three lines, each checked. None when the call fails or its reply
    isn't the JSON asked for; a dict (possibly with every line None) when the model answered."""
    request = LLMRequest(
        messages=[LLMMessage(role="system", content=SYSTEM_PROMPT), LLMMessage(role="user", content=json.dumps(facts, ensure_ascii=False, indent=2))],
        temperature=0.1,
        max_tokens=250,
        response_format="json",
        timeout_seconds=TIMEOUT_SECONDS,
    )
    try:
        structured = ai_services.structured or StructuredLLMService(ai_services.client)
        reply = structured.generate_structured(request, AIWordingReply)
    except (AIError, ValidationError) as exc:
        logger.warning("AI wording failed, the template stays: %s", exc)
        return None
    return {
        "why": check_line(reply.why, facts, facts.get("template_why")) if facts.get("write_why") else None,
        "check_extra": check_line(reply.check_extra, facts, facts.get("template_check")),
        "related_extra": check_line(reply.related_extra, facts, facts.get("related")) if facts.get("related") else None,
        "model": getattr(ai_services.client, "model", None),
        "written_at": datetime.now(timezone.utc).isoformat(),
    }
