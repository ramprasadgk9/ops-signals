"""Is this a new problem or a known one? Read straight off the past-case matches recall already found.

On-call triage changes with the answer: a first occurrence needs investigating from scratch, a
recurring one has a history (and usually a fix) to start from. No extra search runs - the matches
Seen before? and Similar Cases already return are counted.

Only matches above the possible-match floor count (similarity_service.POSSIBLE_MATCH_SCORE); those
are the ones shown, so the badge and the list never disagree.
"""

from __future__ import annotations

from typing import Iterable, Literal, Protocol

from pydantic import BaseModel

# Past cases on the same service that make a problem "recurring" rather than merely "seen before".
RECURRING_MIN_MATCHES = 3

NoveltyLevel = Literal["new", "new_on_service", "seen_before", "recurring"]


class _Match(Protocol):
    similarity_score: float
    same_service: bool


class Novelty(BaseModel):
    """How familiar a finding or case is, for the badge next to its past-case matches."""

    level: NoveltyLevel
    label: str
    explanation: str
    # Matches on the same service (all matches when the service is unknown), and on any service.
    matching_cases: int
    all_matching_cases: int
    best_score: float | None = None


def assess_novelty(matches: Iterable[_Match], service: str | None) -> Novelty:
    matches = list(matches)
    # Without a service there is nothing to compare against, so every match counts as relevant.
    relevant = [match for match in matches if match.same_service] if service else matches
    best = max((match.similarity_score for match in relevant), default=None)
    where = f"on {service}" if service else "in memory"
    common = dict(matching_cases=len(relevant), all_matching_cases=len(matches), best_score=best)

    if not matches:
        return Novelty(
            level="new",
            label="New pattern",
            explanation="Nothing in memory looks like this. Treat it as a first occurrence.",
            **common,
        )
    if not relevant:
        others = len(matches)
        return Novelty(
            level="new_on_service",
            label=f"First time on {service}",
            explanation=f"No past case on {service} looks like this, but {others} on other services "
                        f"{'does' if others == 1 else 'do'}. Their causes and fixes may still apply.",
            **common,
        )
    if len(relevant) >= RECURRING_MIN_MATCHES:
        return Novelty(
            level="recurring",
            label=f"Recurring · {len(relevant)} past cases",
            explanation=f"{len(relevant)} past cases {where} look like this. Start from their causes and "
                        "fixes, and consider whether the underlying problem needs a lasting fix.",
            **common,
        )
    return Novelty(
        level="seen_before",
        label="Seen before",
        explanation=f"{len(relevant)} past {'case' if len(relevant) == 1 else 'cases'} {where} "
                    f"{'looks' if len(relevant) == 1 else 'look'} like this.",
        **common,
    )
