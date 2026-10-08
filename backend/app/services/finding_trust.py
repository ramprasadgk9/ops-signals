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
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.entities import FindingEntity, FindingFeedbackEntity, SignalEntity

TRUST_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "finding_trust.yaml"

VERDICTS = ("real_problem", "expected_change", "not_a_problem")
# A service's own rate replaces the tested one once this many findings like it were answered.
SERVICE_MIN_ANSWERS = 5
# Moving a group between lists for one service, from that service's answers (see module docstring).
PROMOTE_RATE = 0.5
DEMOTE_RATE = 0.2

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


def finding_trust(db: Session, rows: list[FindingEntity]) -> dict[int, dict[str, Any]]:
    """Trust for each finding, keyed by finding id. Three queries, whatever the number of rows."""
    if not rows:
        return {}
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

    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        if row.id is None:
            continue
        group, checks = groups[row.id]
        real, answered = history.get((row.service, group), (0, 0))
        tier, badge, moved = placement(group, real, answered)
        result[row.id] = {
            "group": group,
            "tier": tier,
            "badge": badge,
            "moved": moved,
            "checks": checks,
            "tested": tested_evidence(group, row.metric_name, config),
            "service": {"real": real, "answered": answered, "min_answers": SERVICE_MIN_ANSWERS},
            "your_answer": answers.get(row.id),
        }
    return result


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


def record_feedback(db: Session, finding: FindingEntity, verdict: str) -> FindingFeedbackEntity:
    """Store (or change) the team's answer to "Was this real?" for one finding."""
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {', '.join(VERDICTS)}")
    group = finding_trust(db, [finding])[finding.id]["group"]
    row = db.execute(select(FindingFeedbackEntity).where(FindingFeedbackEntity.finding_id == finding.id)).scalar_one_or_none()
    if row is None:
        row = FindingFeedbackEntity(finding_id=finding.id, service=finding.service, metric_name=finding.metric_name, trust_group=group, verdict=verdict)
        db.add(row)
    else:
        row.verdict = verdict
        row.trust_group = group
    db.commit()
    return row


def _answers(db: Session, finding_ids: list[int]) -> dict[int, str]:
    answers: dict[int, str] = {}
    for start in range(0, len(finding_ids), _CHUNK):
        chunk = finding_ids[start : start + _CHUNK]
        answers.update(
            db.execute(select(FindingFeedbackEntity.finding_id, FindingFeedbackEntity.verdict).where(FindingFeedbackEntity.finding_id.in_(chunk))).all()
        )
    return answers


def _service_history(db: Session, services: set[str | None]) -> dict[tuple[str | None, str], tuple[int, int]]:
    """(real, answered) per (service, group). An expected change is neither: the change was real,
    but it wasn't a problem, so it counts for or against nothing."""
    named = [service for service in services if service is not None]
    query = (
        select(FindingFeedbackEntity.service, FindingFeedbackEntity.trust_group, FindingFeedbackEntity.verdict, func.count())
        .where(FindingFeedbackEntity.verdict.in_(("real_problem", "not_a_problem")))
        .group_by(FindingFeedbackEntity.service, FindingFeedbackEntity.trust_group, FindingFeedbackEntity.verdict)
    )
    if None in services:
        query = query.where((FindingFeedbackEntity.service.in_(named)) | (FindingFeedbackEntity.service.is_(None)))
    else:
        query = query.where(FindingFeedbackEntity.service.in_(named))
    history: dict[tuple[str | None, str], tuple[int, int]] = {}
    for service, group, verdict, count in db.execute(query).all():
        real, answered = history.get((service, group), (0, 0))
        history[(service, group)] = (real + (count if verdict == "real_problem" else 0), answered + count)
    return history
