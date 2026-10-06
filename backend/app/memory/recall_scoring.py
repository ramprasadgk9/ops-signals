"""How recall ranks past cases beyond meaning: one Qdrant score formula shared by every recall.

Two past cases can look equally like the current problem, but one names the same error, is on the
same service, has a verified root cause and happened last month; the other doesn't and is from two
years ago. The first is the one an on-call engineer wants on top. The formula runs inside the Qdrant
query, so Similar Cases, Seen before?, alert context and the assistant all rank the same way.

    rank = similarity + keyword bonus + same-service bonus + verified-RCA bonus + recency bonus

Each bonus is a fixed number of similarity points, and together they are worth at most
MAX_TOTAL_BONUS. So they break ties between close matches, but a case more than that much more
similar always stays on top - which a rank-based fusion like RRF can't promise, because it forgets
how far apart the similarities were. Bonuses only change the order: the similarity people see, the
strong/possible tiers and every score threshold stay plain cosine similarity
(QdrantVectorStore.search).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from qdrant_client import models

# The query shares the past case's exact words (service, error, metric names). The keyword score
# (BM25) is unbounded, so it is squashed to 0..1 first: half the bonus at KEYWORD_SATURATION.
KEYWORD_BONUS = 0.08
KEYWORD_SATURATION = 3.0
# Case on the same service as the one being investigated (payload service_key, lowercased).
SAME_SERVICE_BONUS = 0.07
# Root cause someone confirmed, so the fix shown with it is worth trusting.
VERIFIED_RCA_BONUS = 0.05
# Recency: the full bonus for a case from today, halving every RECENCY_HALF_LIFE_DAYS. Old cases
# lose only the bonus, never part of their similarity.
RECENCY_BONUS = 0.05
RECENCY_HALF_LIFE_DAYS = 180

MAX_TOTAL_BONUS = KEYWORD_BONUS + SAME_SERVICE_BONUS + VERIFIED_RCA_BONUS + RECENCY_BONUS

# Prefetch order in QdrantVectorStore.search: meaning first, keywords second when present.
_SIMILARITY = "$score[0]"
_KEYWORDS = "$score[1]"


def service_key(service: str | None) -> str | None:
    """The form stored in the payload and matched by the same-service bonus (case-insensitive)."""
    cleaned = (service or "").strip().lower()
    return cleaned or None


@dataclass(frozen=True)
class RecallBoost:
    """Context for one recall: the service under investigation, if any, and "now" for recency."""

    service: str | None = None
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def recall_formula(boost: RecallBoost | None, *, keywords: bool) -> models.FormulaQuery:
    """The ranking formula. keywords: whether a keyword prefetch follows the meaning one."""
    terms: list[models.Expression] = [_SIMILARITY]
    defaults: dict = {}
    if keywords:
        terms.append(models.MultExpression(mult=[
            KEYWORD_BONUS,
            models.DivExpression(div=models.DivParams(
                left=_KEYWORDS,
                right=models.SumExpression(sum=[_KEYWORDS, KEYWORD_SATURATION]),
                by_zero_default=0.0,
            )),
        ]))
        # A case only the meaning search found has no keyword score.
        defaults[_KEYWORDS] = 0.0
    if boost is not None:
        now = _rfc3339(boost.now)
        terms.append(_bonus_if(VERIFIED_RCA_BONUS, "rca_verified", True))
        key = service_key(boost.service)
        if key:
            terms.append(_bonus_if(SAME_SERVICE_BONUS, "service_key", key))
        terms.append(models.MultExpression(mult=[
            RECENCY_BONUS,
            models.ExpDecayExpression(exp_decay=models.DecayParamsExpression(
                x=models.DatetimeKeyExpression(datetime_key="created_at"),
                target=models.DatetimeExpression(datetime=now),
                scale=RECENCY_HALF_LIFE_DAYS * 86400,
                midpoint=0.5,
            )),
        ]))
        # A point indexed without created_at counts as current rather than failing the query.
        defaults["created_at"] = now
    return models.FormulaQuery(formula=models.SumExpression(sum=terms), defaults=defaults)


def _bonus_if(bonus: float, key: str, value: bool | str) -> models.MultExpression:
    return models.MultExpression(mult=[bonus, models.FieldCondition(key=key, match=models.MatchValue(value=value))])


def _rfc3339(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
