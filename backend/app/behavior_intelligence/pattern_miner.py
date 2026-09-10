from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.entities import BehaviorPatternSuggestionEntity, SignalEntity

# How close two signals' windows need to be (gap between end of one and start of the other) to
# count as "the same occasion" for co-occurrence purposes — deliberately more generous than any
# single behavior definition's own correlation window, since this is exploratory discovery, not
# final matching (a promoted suggestion gets its own tunable correlation window, see
# _draft_definition_for).
CO_OCCURRENCE_GAP = timedelta(minutes=30)

# A candidate needs at least this many occasions for the rarer metric, and this much of the
# rarer metric's occasions to co-occur with the other, before it's worth surfacing — simple
# thresholds, not statistical significance testing, to start.
MIN_OCCASIONS = 3
MIN_CORRELATION_STRENGTH = 0.5

DEFAULT_LOOKBACK = timedelta(days=90)


@dataclass(slots=True)
class SignalWindow:
    start: datetime
    end: datetime
    analysis_run_id: str | None


@dataclass(slots=True)
class PatternCandidate:
    service: str | None
    metric_a: str
    metric_b: str
    co_occurrence_count: int
    metric_a_occasions: int
    metric_b_occasions: int
    correlation_strength: float
    sample_analysis_run_ids: list[str]


def _windows_overlap_or_close(a: SignalWindow, b: SignalWindow, gap: timedelta) -> bool:
    if a.end + gap < b.start or b.end + gap < a.start:
        return False
    return True


def _group_by_metric(signals: list[SignalEntity]) -> dict[str, list[SignalWindow]]:
    grouped: dict[str, list[SignalWindow]] = defaultdict(list)
    for signal in signals:
        if not signal.start_time or not signal.end_time:
            continue
        grouped[signal.metric_name].append(
            SignalWindow(start=signal.start_time, end=signal.end_time, analysis_run_id=signal.analysis_run_id)
        )
    return grouped


def _co_occurrences(windows_a: list[SignalWindow], windows_b: list[SignalWindow]) -> tuple[int, list[str]]:
    count = 0
    sample_run_ids: list[str] = []
    for wa in windows_a:
        for wb in windows_b:
            if _windows_overlap_or_close(wa, wb, CO_OCCURRENCE_GAP):
                count += 1
                for run_id in (wa.analysis_run_id, wb.analysis_run_id):
                    if run_id and run_id not in sample_run_ids and len(sample_run_ids) < 5:
                        sample_run_ids.append(run_id)
                break  # one match per wa is enough to count this occasion as co-occurring
    return count, sample_run_ids


def find_candidates(db: Session, lookback: timedelta = DEFAULT_LOOKBACK) -> list[PatternCandidate]:
    """Scans recent signals per service and looks for metric pairs whose signal windows keep
    landing close together in time — simple co-occurrence counting (not ML), meant as a starting
    point a human reviews and tunes, not an automatic answer. See docs on why: a behavior
    definition's conditions/thresholds still need domain judgment this can't supply on its own."""
    cutoff = datetime.utcnow() - lookback
    rows = db.execute(select(SignalEntity).where(SignalEntity.created_at >= cutoff)).scalars().all()

    by_service: dict[str | None, list[SignalEntity]] = defaultdict(list)
    for row in rows:
        by_service[row.service].append(row)

    candidates: list[PatternCandidate] = []
    for service, signals in by_service.items():
        by_metric = _group_by_metric(signals)
        metric_names = sorted(by_metric)
        for i, metric_a in enumerate(metric_names):
            for metric_b in metric_names[i + 1 :]:
                windows_a = by_metric[metric_a]
                windows_b = by_metric[metric_b]
                rarer_count = min(len(windows_a), len(windows_b))
                if rarer_count < MIN_OCCASIONS:
                    continue
                co_count, sample_run_ids = _co_occurrences(windows_a, windows_b)
                strength = co_count / rarer_count if rarer_count else 0.0
                if strength < MIN_CORRELATION_STRENGTH:
                    continue
                candidates.append(
                    PatternCandidate(
                        service=service,
                        metric_a=metric_a,
                        metric_b=metric_b,
                        co_occurrence_count=co_count,
                        metric_a_occasions=len(windows_a),
                        metric_b_occasions=len(windows_b),
                        correlation_strength=round(strength, 3),
                        sample_analysis_run_ids=sample_run_ids,
                    )
                )
    candidates.sort(key=lambda c: c.correlation_strength, reverse=True)
    return candidates


def _draft_definition_for(candidate: PatternCandidate) -> dict:
    definition_id = f"suggested_{candidate.metric_a}_{candidate.metric_b}".replace("-", "_").replace(".", "_")
    return {
        "id": definition_id,
        "enabled": False,  # suggestions are never auto-enabled — promotion is an explicit human action
        "version": 1,
        "title": f"Possible correlation: {candidate.metric_a} and {candidate.metric_b}",
        "description": (
            f"Mined from history: {candidate.metric_a} and {candidate.metric_b} showed signals within "
            f"{int(CO_OCCURRENCE_GAP.total_seconds() / 60)} minutes of each other in "
            f"{candidate.co_occurrence_count} of {min(candidate.metric_a_occasions, candidate.metric_b_occasions)} "
            f"occasions ({int(candidate.correlation_strength * 100)}%). Review and tune before enabling."
        ),
        "scope": {"service": candidate.service or "*"},
        "inputs": [
            {"alias": "a", "metric_name": candidate.metric_a, "analyzers": []},
            {"alias": "b", "metric_name": candidate.metric_b, "analyzers": []},
        ],
        "conditions": {
            "all": [
                {"fact": "a.signal.count", "operator": "greater_than", "value": 0},
                {"fact": "b.signal.count", "operator": "greater_than", "value": 0},
            ],
            "any": [],
        },
        "correlation": {
            "same_analysis_context": False,
            "max_time_gap": f"{int(CO_OCCURRENCE_GAP.total_seconds() / 60)}m",
            "minimum_overlap": "0m",
        },
        "output": {
            "category": "correlated_behavior",
            "severity": "medium",
            "title": f"Possible correlation between {candidate.metric_a} and {candidate.metric_b}",
            "summary": f"{candidate.metric_a} and {candidate.metric_b} tend to show activity together.",
            "evidence": ["a.signal.count", "b.signal.count"],
        },
    }


def mine_and_store(db: Session, lookback: timedelta = DEFAULT_LOOKBACK) -> list[BehaviorPatternSuggestionEntity]:
    """Finds candidates and upserts them as pending suggestions (re-running mining refreshes the
    evidence on an existing pending suggestion for the same service+metric pair instead of piling
    up duplicates, same dedup instinct as the finding-suppression fix in repository.py)."""
    candidates = find_candidates(db, lookback=lookback)
    stored: list[BehaviorPatternSuggestionEntity] = []
    for candidate in candidates:
        draft = _draft_definition_for(candidate)
        existing = db.execute(
            select(BehaviorPatternSuggestionEntity).where(
                BehaviorPatternSuggestionEntity.service == candidate.service,
                BehaviorPatternSuggestionEntity.metric_a == candidate.metric_a,
                BehaviorPatternSuggestionEntity.metric_b == candidate.metric_b,
                BehaviorPatternSuggestionEntity.status == "pending",
            )
        ).scalar_one_or_none()
        yaml_text = yaml.dump({"behavior_definitions": {draft["id"]: draft}}, sort_keys=False)
        if existing:
            existing.co_occurrence_count = candidate.co_occurrence_count
            existing.metric_a_occasions = candidate.metric_a_occasions
            existing.metric_b_occasions = candidate.metric_b_occasions
            existing.correlation_strength = candidate.correlation_strength
            existing.sample_analysis_run_ids = candidate.sample_analysis_run_ids
            existing.draft_definition_json = draft
            existing.draft_yaml_text = yaml_text
            db.add(existing)
            stored.append(existing)
            continue
        record = BehaviorPatternSuggestionEntity(
            service=candidate.service,
            metric_a=candidate.metric_a,
            metric_b=candidate.metric_b,
            co_occurrence_count=candidate.co_occurrence_count,
            metric_a_occasions=candidate.metric_a_occasions,
            metric_b_occasions=candidate.metric_b_occasions,
            correlation_strength=candidate.correlation_strength,
            sample_analysis_run_ids=candidate.sample_analysis_run_ids,
            draft_definition_json=draft,
            draft_yaml_text=yaml_text,
            status="pending",
        )
        db.add(record)
        stored.append(record)
    db.commit()
    for record in stored:
        db.refresh(record)
    return stored
