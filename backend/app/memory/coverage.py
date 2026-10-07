"""Monitoring coverage: which past incidents (imported postmortems) Ops Signals caught, and which it
missed - the incidents your monitoring is blind to.

For each imported incident, in order:
- not watched: no analysis run covered that service during the incident. A coverage gap -
  connect the service or schedule it - not a detection failure.
- detected: an analysis of that service produced a finding during the incident (its anomaly
  overlapped the incident window) that reads like the incident's symptom (DETECTED_SIMILARITY).
- flagged something else: findings were raised during the incident, but none reads like it -
  shown by title, so a person can judge (an analyzer may have caught it under another metric).
- missed: the service was analysed during the incident and nothing was flagged. A detection gap.
- unknown: the postmortem has no service or start time to check against.

A missed or unwatched incident also says whether a similar problem was detected on that service at
another time (detected cases' symptom vectors), i.e. whether analyzers catch this kind of problem now.

Similarity is the finding's own text against the incident's symptom. Analyzer findings are worded
generically ("cpu_usage experienced a persistent baseline shift"), so on one service a different
problem can come close: measured, a matching finding scores 0.61-0.75 and a different one on the
same service up to 0.58. The same-service, same-time narrowing does most of the work; the threshold
only separates findings that already overlap the incident.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.memory.document_builder import CaseDocumentBuilder
from backend.app.memory.embedder import Embedder
from backend.app.memory.indexer import CaseMemoryIndexer
from backend.app.memory.recall_scoring import service_key
from backend.app.memory.seen_before import finding_query_text
from backend.app.memory.similarity_service import STRONG_MATCH_SCORE
from backend.app.memory.vector_names import SYMPTOM_VECTOR
from backend.app.memory.vector_store import VectorStore, cosine_similarity
from backend.app.models.entities import (
    AnalysisRunEntity,
    BehaviorFindingEntity,
    FindingEntity,
    OperationalCaseEntity,
    SignalEntity,
)

DETECTED_SIMILARITY = 0.60
# The incident window: from shortly before it started (an anomaly often leads the page) to when it
# was resolved, or DEFAULT_DURATION after the start when the postmortem gives no end.
LEAD = timedelta(hours=1)
DEFAULT_DURATION = timedelta(hours=6)
MAX_DURATION = timedelta(hours=48)
MAX_INCIDENTS = 200
MAX_EVIDENCE = 3

CoverageStatus = Literal["detected", "flagged_other", "missed", "not_watched", "unknown"]
STATUS_LABELS: dict[str, str] = {
    "detected": "Detected",
    "flagged_other": "Flagged something else",
    "missed": "Missed",
    "not_watched": "Not watched",
    "unknown": "Can't tell",
}
# Gaps first: they are what to act on.
STATUS_ORDER = ("missed", "not_watched", "flagged_other", "unknown", "detected")


class CoverageEvidence(BaseModel):
    kind: Literal["finding", "behavior"]
    id: int
    title: str
    similarity: float
    at: datetime | None = None


class CoverageIncident(BaseModel):
    case_id: int
    title: str
    service: str | None = None
    started_at: datetime | None = None
    status: CoverageStatus
    label: str
    explanation: str
    evidence: list[CoverageEvidence] = Field(default_factory=list)
    # Detected cases on the same service with this symptom (strong matches), at any time.
    seen_elsewhere: int = 0
    seen_elsewhere_case_id: int | None = None
    seen_elsewhere_at: datetime | None = None


class ServiceCoverage(BaseModel):
    service: str
    counts: dict[str, int]


class CoverageReport(BaseModel):
    available: bool
    reason: str | None = None
    window_days: int
    incidents_considered: int = 0
    counts: dict[str, int] = Field(default_factory=dict)
    services: list[ServiceCoverage] = Field(default_factory=list)
    incidents: list[CoverageIncident] = Field(default_factory=list)


def _naive(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment.astimezone(timezone.utc).replace(tzinfo=None) if moment.tzinfo else moment


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return _naive(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _overlaps(start: datetime | None, end: datetime | None, window: tuple[datetime, datetime]) -> bool:
    if start is None:
        return False
    return start <= window[1] and (end or start) >= window[0]


def build_coverage_report(
    db: Session,
    embedder: Embedder | None,
    store: VectorStore | None = None,
    *,
    days: int = 365,
    now: datetime | None = None,
) -> CoverageReport:
    report = CoverageReport(available=False, window_days=days)
    if embedder is None:
        report.reason = "Operational memory is not enabled, so incidents can't be compared with findings."
        return report
    since = _naive(now or datetime.now(timezone.utc)) - timedelta(days=days)
    imported = db.execute(
        select(OperationalCaseEntity)
        .where(OperationalCaseEntity.source != "detected", OperationalCaseEntity.created_at >= since)
        .order_by(OperationalCaseEntity.created_at.desc())
        .limit(MAX_INCIDENTS)
    ).scalars().all()
    report.available = True
    report.incidents_considered = len(imported)
    if not imported:
        report.reason = "No past incidents imported in this window. Import postmortems to see what your monitoring caught."
        return report

    plans = [_plan(case) for case in imported]
    keys = {key for plan in plans for key in plan["services"]}
    windows = [plan["window"] for plan in plans if plan["window"]]
    runs, findings, signals, behaviors = _load_activity(db, keys, windows)

    incidents = []
    symptom_cache: dict[int, list[float]] = {}
    text_cache: dict[tuple[str, int], list[float]] = {}
    for case, plan in zip(imported, plans):
        incident = _assess(case, plan, runs, findings, signals, behaviors, embedder, symptom_cache, text_cache)
        if incident.status in ("missed", "not_watched", "flagged_other") and store is not None:
            _add_seen_elsewhere(incident, plan, store, embedder, symptom_cache)
        incidents.append(incident)

    # Gaps first, most recent first within each.
    incidents.sort(key=lambda incident: (STATUS_ORDER.index(incident.status), -(incident.started_at.timestamp() if incident.started_at else 0)))
    report.incidents = incidents
    report.counts = {status: sum(1 for incident in incidents if incident.status == status) for status in STATUS_ORDER}
    by_service: dict[str, Counter] = {}
    for incident in incidents:
        by_service.setdefault(incident.service or "unknown", Counter())[incident.status] += 1
    report.services = sorted(
        (ServiceCoverage(service=service, counts={status: counts.get(status, 0) for status in STATUS_ORDER}) for service, counts in by_service.items()),
        key=lambda row: (-sum(row.counts.values()), row.service),
    )
    return report


def _plan(case: OperationalCaseEntity) -> dict:
    snapshot = case.finding_snapshot or {}
    services = [service for service in (snapshot.get("services") or [snapshot.get("service")]) if service]
    start = _parse(snapshot.get("started_at"))
    window = None
    if start is not None:
        end = _naive(case.resolved_at)
        if end is None or end <= start:
            end = start + DEFAULT_DURATION
        window = (start - LEAD, min(end, start + MAX_DURATION))
    return {"services": {service_key(service) for service in services if service_key(service)}, "service": services[0] if services else None, "start": start, "window": window}


def _load_activity(db: Session, keys: set[str], windows: list[tuple[datetime, datetime]]):
    """Runs, findings, their signals and behaviors on these services, across all the windows."""
    if not keys or not windows:
        return [], [], {}, []
    earliest, latest = min(window[0] for window in windows), max(window[1] for window in windows)
    runs = db.execute(
        select(AnalysisRunEntity).where(
            func.lower(AnalysisRunEntity.service).in_(keys),
            AnalysisRunEntity.start_time <= latest,
            AnalysisRunEntity.end_time >= earliest,
        )
    ).scalars().all()
    run_ids = [run.id for run in runs]
    findings = db.execute(
        select(FindingEntity).where(FindingEntity.analysis_run_id.in_(run_ids), func.lower(FindingEntity.service).in_(keys))
    ).scalars().all() if run_ids else []
    signal_ids = {signal_id for finding in findings for signal_id in (finding.signal_ids or [])}
    signals = {
        signal.signal_id: signal
        for signal in db.execute(select(SignalEntity).where(SignalEntity.signal_id.in_(signal_ids))).scalars()
    } if signal_ids else {}
    behaviors = db.execute(
        select(BehaviorFindingEntity).where(BehaviorFindingEntity.analysis_run_id.in_(run_ids), func.lower(BehaviorFindingEntity.service).in_(keys))
    ).scalars().all() if run_ids else []
    return runs, findings, signals, behaviors


def _assess(case, plan, runs, findings, signals, behaviors, embedder, symptom_cache, text_cache) -> CoverageIncident:
    base = dict(case_id=case.id, title=case.case_title, service=plan["service"], started_at=plan["start"])
    if not plan["services"] or plan["window"] is None:
        missing = "service" if not plan["services"] else "start time"
        return CoverageIncident(
            **base, status="unknown", label=STATUS_LABELS["unknown"],
            explanation=f"The postmortem has no {missing}, so it can't be checked against what was analysed.",
        )
    window = plan["window"]
    watched = [run for run in runs if (run.service or "").lower() in plan["services"] and _overlaps(_naive(run.start_time), _naive(run.end_time), window)]
    where = ", ".join(sorted(plan["services"]))
    if not watched:
        return CoverageIncident(
            **base, status="not_watched", label=STATUS_LABELS["not_watched"],
            explanation=f"Nothing analysed {where} while this happened. If the service has another name in your metrics, "
                        "add it as an alias when importing; otherwise connect or schedule it.",
        )
    run_ids = {run.id for run in watched}
    candidates: list[tuple[str, int, str, str, datetime | None]] = []
    for finding in findings:
        if finding.analysis_run_id not in run_ids or (finding.service or "").lower() not in plan["services"]:
            continue
        timed = [signals[signal_id] for signal_id in (finding.signal_ids or []) if signal_id in signals and signals[signal_id].start_time]
        # A finding counts when one of its anomalies overlaps the incident; one whose signals carry
        # no times counts by its run having covered the incident.
        if timed and not any(_overlaps(_naive(signal.start_time), _naive(signal.end_time), window) for signal in timed):
            continue
        at = min((_naive(signal.start_time) for signal in timed), default=None)
        candidates.append(("finding", finding.id, finding.title, finding_query_text(finding), at))
    for behavior in behaviors:
        if behavior.analysis_run_id in run_ids and (behavior.service or "").lower() in plan["services"]:
            candidates.append(("behavior", behavior.id, behavior.title, f"{behavior.service or ''}: {behavior.title}. {behavior.summary or ''}", None))

    if not candidates:
        return CoverageIncident(
            **base, status="missed", label=STATUS_LABELS["missed"],
            explanation=f"{where} was analysed while this happened, but nothing was flagged: an analyzer or threshold may be missing for this kind of problem.",
        )
    symptom = _symptom_vector(case, embedder, symptom_cache)
    scored = sorted(
        (
            CoverageEvidence(kind=kind, id=item_id, title=title, at=at, similarity=round(cosine_similarity(symptom, _text_vector(kind, item_id, text, embedder, text_cache)), 3))
            for kind, item_id, title, text, at in candidates
        ),
        key=lambda evidence: -evidence.similarity,
    )
    if scored[0].similarity >= DETECTED_SIMILARITY:
        best = scored[0]
        return CoverageIncident(
            **base, status="detected", label=STATUS_LABELS["detected"], evidence=scored[:MAX_EVIDENCE],
            explanation=f"Flagged while it happened: \"{best.title}\" ({round(best.similarity * 100)}% like the postmortem's symptom).",
        )
    return CoverageIncident(
        **base, status="flagged_other", label=STATUS_LABELS["flagged_other"], evidence=scored[:MAX_EVIDENCE],
        explanation=f"{len(scored)} {'thing was' if len(scored) == 1 else 'things were'} flagged on {where} while this happened, "
                    "but none reads like this incident. Check whether one of them was it.",
    )


def _symptom_vector(case, embedder, cache) -> list[float]:
    if case.id not in cache:
        cache[case.id] = embedder.encode(CaseDocumentBuilder.build_symptom(case))
    return cache[case.id]


def _text_vector(kind, item_id, text, embedder, cache) -> list[float]:
    if (kind, item_id) not in cache:
        cache[(kind, item_id)] = embedder.encode(text)
    return cache[(kind, item_id)]


def _add_seen_elsewhere(incident: CoverageIncident, plan: dict, store: VectorStore, embedder: Embedder, symptom_cache: dict) -> None:
    """Strong symptom matches among detected cases on the same service, at any time."""
    case_vector = store.get_vector(CaseMemoryIndexer._generate_point_id(incident.case_id), SYMPTOM_VECTOR)
    vector = case_vector or symptom_cache.get(incident.case_id)
    if vector is None:
        return
    try:
        hits = store.search(
            vector=vector,
            filters={
                "must": [{"key": "origin", "match": {"value": "detected"}}],
                "should": [{"key": "service_key", "match": {"value": key}} for key in sorted(plan["services"])],
            },
            limit=20,
            score_threshold=STRONG_MATCH_SCORE,
            using=SYMPTOM_VECTOR,
        )
    except Exception:
        return
    if not hits:
        return
    incident.seen_elsewhere = len(hits)
    latest = max(hits, key=lambda hit: hit["payload"].get("created_at") or "")
    incident.seen_elsewhere_case_id = latest["payload"].get("case_id")
    incident.seen_elsewhere_at = _parse(latest["payload"].get("created_at"))
    case_ref = f"case #{incident.seen_elsewhere_case_id}"
    incident.explanation += (
        f" A similar problem on this service was detected {incident.seen_elsewhere} other "
        f"{'time' if incident.seen_elsewhere == 1 else 'times'} (latest {case_ref}), so analyzers can catch it now."
    )
