"""How much to trust a finding: its trust group, whether it needs attention, the tested numbers
behind it, and what this service's own team answered on findings like it.

The groups and tiers follow the finding-trust benchmark (benchmark/finding_trust, numbers in
config/finding_trust.yaml):

| Group | Needs attention? | Badge | Why |
| --- | --- | --- | --- |
| data_problem | yes | data_problem | The data stopped or froze: a fact, not a guess, so no tested rate |
| level_change_agree | yes | strong | A lasting level change plus a second, different check; clearly better than chance |
| level_change_single | yes | moderate | A lasting level change from the change check alone; somewhat better than chance |
| spike | no (context) | - | Unusual values without a level change; about as often real as a random alert |
| pattern | no (context) | - | Trends, forecasts and repeating patterns; not tested as problems |

Checks, not analyzers, are counted: ruptures and baseline_shift run the same change-point detector,
so together they are one check. A finding whose signals aren't stored falls back to its category.

A service's own answers move a group between the lists, for that service only, once it has
SERVICE_MIN_ANSWERS of them: a context group whose findings were real at least PROMOTE_RATE of the
time moves up to needs attention; a needs-attention group real less than DEMOTE_RATE of the time
moves down to context. Data problems never move down: a metric that stopped reporting is a fact.

A problem that is over (its newest finding says the data went on after its last bad reading, see
services/active_findings.py problem_ends) leaves Needs attention OVER_GRACE after it ended, with
the "over" badge: it needs no action now. Its findings, answers and any case on it stay as they are.
Only data problems and spikes (OVER_GROUPS) move: a level change or trend runs to the last reading,
so a finding with one isn't over even when a spike on top of it ended.

A finding with no service label (stored as "unknown", or none at all) has no service to learn for:
its answers are counted per metric instead, so a CPU gap and a latency gap don't share one bucket.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.entities import FindingEntity, FindingFeedbackEntity, SignalEntity
from backend.app.services.active_findings import problem_ends

TRUST_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "finding_trust.yaml"

VERDICTS = ("real_problem", "expected_change", "not_a_problem")
# A service's own rate replaces the tested one once this many findings like it were answered.
SERVICE_MIN_ANSWERS = 5
# Moving a group between lists for one service, from that service's answers (see module docstring).
PROMOTE_RATE = 0.5
DEMOTE_RATE = 0.2
# A problem that needed attention and is over stays in Needs attention this long after it ended,
# so the people on shift still see it, then moves to Context with the "over" badge.
OVER_GRACE = timedelta(hours=1)
# The groups whose checks stop when the problem stops. A level change or a trend runs to the last
# reading, so a finding with one is still going even when a spike riding on it ended (a finding's
# `ongoing` follows its most recent event, which can be that spike).
OVER_GROUPS = {"data_problem", "spike"}

DATA_SIGNAL_TYPES = {"data_gap", "flatline"}
CHANGE_IDS = {"ruptures", "baseline_shift"}
# The metrics the tested data covered: a service's CPU, memory and latency.
_TESTED_METRIC = re.compile(r"cpu|mem|latency|duration|response_time", re.IGNORECASE)

TIERS = {
    "data_problem": ("needs_attention", "data_problem"),
    "level_change_agree": ("needs_attention", "strong"),
    "level_change_single": ("needs_attention", "moderate"),
    "spike": ("context", None),
    "pattern": ("context", None),
}

_CHUNK = 500
# What the pipeline stores for a series with no service label.
UNLABELED_SERVICES = frozenset({"unknown", "none", "null", "n/a", "-", ""})


@dataclass(frozen=True, slots=True)
class SignalFacts:
    analyzer_id: str | None
    signal_type: str


def check_of(signal: SignalFacts) -> str:
    """The kind of check a signal comes from."""
    if signal.signal_type in DATA_SIGNAL_TYPES or signal.analyzer_id == "data_health":
        return "data"
    if signal.signal_type in CHANGE_IDS or signal.analyzer_id in CHANGE_IDS:
        return "change"
    return signal.analyzer_id or signal.signal_type


def trust_group(category: str, signals: Iterable[SignalFacts]) -> tuple[str, list[str]]:
    """(group, checks) for a finding from its category and the signals behind it."""
    checks = sorted({check_of(signal) for signal in signals})
    if category == "data_quality" or "data" in checks:
        return "data_problem", checks
    if "change" in checks:
        others = [check for check in checks if check not in ("change", "data")]
        return ("level_change_agree" if others else "level_change_single"), checks
    if checks:
        return ("spike" if category == "unusual_activity" else "pattern"), checks
    # No stored signals: the category is all there is.
    fallback = {"behavior_change": "level_change_single", "unusual_activity": "spike"}
    return fallback.get(category, "pattern"), checks


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def load_trust_config(path: Path = TRUST_CONFIG_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _load(str(path), path.stat().st_mtime)


def tested_evidence(group: str, metric_name: str, config: dict[str, Any]) -> dict[str, Any] | None:
    """The tested numbers for a group, if there are enough of them to show."""
    entry = (config.get("groups") or {}).get(group) or {}
    tested = entry.get("tested")
    if not tested or tested.get("checked", 0) < int(config.get("min_checked", 30)):
        return None
    return {
        **tested,
        "fits_metric": bool(_TESTED_METRIC.search(metric_name or "")),
        "measured_at": (config.get("source") or {}).get("measured_at"),
    }


def finding_trust(db: Session, rows: list[FindingEntity], now: datetime | None = None) -> dict[int, dict[str, Any]]:
    """Trust for each finding, keyed by finding id. Four queries, whatever the number of rows."""
    if not rows:
        return {}
    now = now or datetime.now(timezone.utc)
    config = load_trust_config()
    signal_ids = sorted({signal_id for row in rows for signal_id in (row.signal_ids or [])})
    facts: dict[str, SignalFacts] = {}
    for start in range(0, len(signal_ids), _CHUNK):
        chunk = signal_ids[start : start + _CHUNK]
        for signal_id, analyzer_id, signal_type in db.execute(
            select(SignalEntity.signal_id, SignalEntity.analyzer_id, SignalEntity.signal_type).where(SignalEntity.signal_id.in_(chunk))
        ).all():
            facts[signal_id] = SignalFacts(analyzer_id, signal_type)

    groups = {
        row.id: trust_group(row.category, [facts[signal_id] for signal_id in (row.signal_ids or []) if signal_id in facts])
        for row in rows
        if row.id is not None
    }
    answers = _answers(db, [row.id for row in rows if row.id is not None])
    history = _service_history(db, {row.service for row in rows})
    ends = problem_ends(db, rows)

    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        if row.id is None:
            continue
        group, checks = groups[row.id]
        scope = "metric" if is_unlabeled(row.service) else "service"
        real, answered = history.get(_bucket(row.service, row.metric_name, group), (0, 0))
        tier, badge, moved = placement(group, real, answered)
        ended_at = ends.get(row.id)
        if tier == "needs_attention" and group in OVER_GROUPS and ended_at is not None and now - ended_at >= OVER_GRACE:
            tier, badge, moved = "context", "over", None
        result[row.id] = {
            "group": group,
            "tier": tier,
            "badge": badge,
            "moved": moved,
            "checks": checks,
            "tested": tested_evidence(group, row.metric_name, config),
            "service": {"real": real, "answered": answered, "min_answers": SERVICE_MIN_ANSWERS, "scope": scope},
            "your_answer": answer[0] if (answer := answers.get(row.id)) else None,
            "answered_by": answer[1] if answer else None,
            "answered_at": _iso(answer[2]) if answer else None,
            "ended_at": _iso(ended_at),
        }
    return result


def is_unlabeled(service: str | None) -> bool:
    return service is None or service.strip().lower() in UNLABELED_SERVICES


def _bucket(service: str | None, metric_name: str, group: str) -> tuple[str | None, str | None, str]:
    """Where a finding's answers are counted: per service and group, or per metric for no service."""
    return (None, metric_name, group) if is_unlabeled(service) else (service, None, group)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


def placement(group: str, real: int, answered: int) -> tuple[str, str | None, str | None]:
    """(tier, badge, moved) for a group, after this service's own answers. `moved` is "up" or "down"
    when the answers moved the group off its tested list, else None."""
    tier, badge = TIERS[group]
    if answered < SERVICE_MIN_ANSWERS:
        return tier, badge, None
    rate = real / answered
    if tier == "context" and rate >= PROMOTE_RATE:
        return "needs_attention", "team_confirmed", "up"
    if tier == "needs_attention" and group != "data_problem" and rate < DEMOTE_RATE:
        return "context", None, "down"
    return tier, badge, None


def record_feedback(db: Session, finding: FindingEntity, verdict: str, answered_by: str | None = None) -> FindingFeedbackEntity:
    """Store (or change) the team's answer to "Was this real?" for one finding. answered_by is the
    Grafana user who gave it; an answer from elsewhere clears it rather than keep someone else's name."""
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {', '.join(VERDICTS)}")
    group = finding_trust(db, [finding])[finding.id]["group"]
    row = db.execute(select(FindingFeedbackEntity).where(FindingFeedbackEntity.finding_id == finding.id)).scalar_one_or_none()
    if row is None:
        row = FindingFeedbackEntity(
            finding_id=finding.id, service=finding.service, metric_name=finding.metric_name, trust_group=group, verdict=verdict, answered_by=answered_by
        )
        db.add(row)
    else:
        row.verdict = verdict
        row.trust_group = group
        row.answered_by = answered_by
        # Set here too: onupdate doesn't fire when the same answer is given again by someone else.
        row.updated_at = datetime.utcnow()
    db.commit()
    return row


def _answers(db: Session, finding_ids: list[int]) -> dict[int, tuple[str, str | None, datetime | None]]:
    """finding id -> (verdict, who answered, when)."""
    answers: dict[int, tuple[str, str | None, datetime | None]] = {}
    for start in range(0, len(finding_ids), _CHUNK):
        chunk = finding_ids[start : start + _CHUNK]
        rows = db.execute(
            select(FindingFeedbackEntity.finding_id, FindingFeedbackEntity.verdict, FindingFeedbackEntity.answered_by, FindingFeedbackEntity.updated_at)
            .where(FindingFeedbackEntity.finding_id.in_(chunk))
        ).all()
        answers.update({finding_id: (verdict, by, at) for finding_id, verdict, by, at in rows})
    return answers


def _service_history(db: Session, services: set[str | None]) -> dict[tuple[str | None, str | None, str], tuple[int, int]]:
    """(real, answered) per bucket (see _bucket). An expected change is neither: the change was real,
    but it wasn't a problem, so it counts for or against nothing."""
    named = [service for service in services if service is not None]
    query = (
        select(FindingFeedbackEntity.service, FindingFeedbackEntity.metric_name, FindingFeedbackEntity.trust_group, FindingFeedbackEntity.verdict, func.count())
        .where(FindingFeedbackEntity.verdict.in_(("real_problem", "not_a_problem")))
        .group_by(FindingFeedbackEntity.service, FindingFeedbackEntity.metric_name, FindingFeedbackEntity.trust_group, FindingFeedbackEntity.verdict)
    )
    if None in services:
        query = query.where((FindingFeedbackEntity.service.in_(named)) | (FindingFeedbackEntity.service.is_(None)))
    else:
        query = query.where(FindingFeedbackEntity.service.in_(named))
    history: dict[tuple[str | None, str | None, str], tuple[int, int]] = {}
    for service, metric_name, group, verdict, count in db.execute(query).all():
        key = _bucket(service, metric_name, group)
        real, answered = history.get(key, (0, 0))
        history[key] = (real + (count if verdict == "real_problem" else 0), answered + count)
    return history
