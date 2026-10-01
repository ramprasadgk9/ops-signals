"""Finding drill-down for autonomous Prometheus runs (see intelligence/drilldown.py for the math).

Runs after a job's findings are saved: for each of the job's top findings, re-run the job's PromQL
grouped by pod (or the next configured label) over the finding's before/after window, and store the
result in the finding's comparison_json["breakdown"]. Additive only - title, summary, score and
priority are never touched - and a drill-down that fails leaves the finding exactly as it was saved.
"""

from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.autonomous.metric_executor import MetricAnalysisExecutionResult
from backend.app.config import DrillDownConfig
from backend.app.models.entities import FindingEntity
from backend.app.services.prometheus_service import PrometheusQueryService
from intelligence.drilldown import breakdown_window, compute_breakdown, rewrite_for_breakdown
from intelligence.finding_aggregator import DATA_HEALTH_SIGNAL_TYPES
from intelligence.findings.schema import OperationalFinding

logger = logging.getLogger(__name__)


def drill_down_findings(
    *,
    db: Session,
    prometheus: PrometheusQueryService,
    promql: str,
    step: str,
    result: MetricAnalysisExecutionResult,
    config: DrillDownConfig,
) -> int:
    """Attach a breakdown to the job's top findings; returns how many findings got one."""
    if not config.enabled or not result.findings or result.normalized_points.empty:
        return 0
    timestamps = pd.to_datetime(result.normalized_points["timestamp"], utc=True, errors="coerce").dropna()
    if timestamps.empty:
        return 0
    series_start = timestamps.min().to_pydatetime()
    series_end = timestamps.max().to_pydatetime()
    signals_by_id = {signal.signal_id: signal for signal in result.signals}

    annotated = 0
    for finding in _candidate_findings(result.findings, signals_by_id)[: config.max_findings_per_job]:
        signals = [signals_by_id[signal_id] for signal_id in finding.signal_ids if signal_id in signals_by_id]
        try:
            breakdown = finding_breakdown(
                prometheus=prometheus,
                promql=promql,
                step=step,
                signals=signals,
                series_start=series_start,
                series_end=series_end,
                labels=config.labels,
            )
        except Exception:  # noqa: BLE001 - a drill-down must never fail the job that found the finding
            logger.warning("Drill-down failed for finding %s / %s", finding.service, finding.metric_name, exc_info=True)
            breakdown = {"status": "failed", "reason": "error"}
        try:
            _store(db, result.analysis_run_id, finding, breakdown)
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.warning("Could not store drill-down for finding %s / %s", finding.service, finding.metric_name, exc_info=True)
            continue
        finding.comparison_json = {**(finding.comparison_json or {}), "breakdown": breakdown}
        annotated += 1
    return annotated


def _candidate_findings(findings: list[OperationalFinding], signals_by_id: dict) -> list[OperationalFinding]:
    """Behavior findings, most important first. A data-health finding ("stopped reporting") is about
    the data, not the service's behavior, so there is no change to attribute to a pod."""
    candidates = []
    for finding in findings:
        types = {signals_by_id[signal_id].signal_type for signal_id in finding.signal_ids if signal_id in signals_by_id}
        if types and types <= DATA_HEALTH_SIGNAL_TYPES:
            continue
        candidates.append(finding)
    return sorted(candidates, key=lambda finding: finding.importance_score, reverse=True)


def finding_breakdown(
    *,
    prometheus: PrometheusQueryService,
    promql: str,
    step: str,
    signals: list,
    series_start: datetime,
    series_end: datetime,
    labels: list[str],
) -> dict[str, object]:
    """Split one finding's change by pod (or the next label that gives 2+ parts). Also used for
    alert-triggered analysis (backend/app/alerts/enrichment.py)."""
    window = breakdown_window(signals, series_start, series_end)
    if window is None:
        return {"status": "skipped", "reason": "no_change_time"}

    reason = "query_shape_not_supported"
    for label in labels:
        query = rewrite_for_breakdown(promql, label)
        if query is None:
            continue
        try:
            preview = prometheus.preview(query.query, window.before_start, window.change_end, step)
        except HTTPException as exc:
            reason = "too_many_parts" if "max_series" in str(exc.detail) or "max total samples" in str(exc.detail) else "query_failed"
            continue
        rows = [
            {"part": series.labels[label], "timestamp": sample.timestamp, "value": sample.value}
            for series in preview.series
            if series.labels.get(label)
            for sample in series.samples
        ]
        if len({row["part"] for row in rows}) < 2:
            reason = "single_part"
            continue
        breakdown = compute_breakdown(pd.DataFrame(rows), label=label, window=window, mode=query.mode)
        breakdown["query"] = query.query
        return breakdown
    return {"status": "skipped", "reason": reason, "labels_tried": list(labels)}


def _store(db: Session, analysis_run_id: str, finding: OperationalFinding, breakdown: dict[str, object]) -> None:
    statement = select(FindingEntity).where(
        FindingEntity.analysis_run_id == analysis_run_id,
        FindingEntity.metric_name == finding.metric_name,
        FindingEntity.title == finding.title,
        FindingEntity.service.is_(None) if finding.service is None else FindingEntity.service == finding.service,
    )
    for row in db.execute(statement).scalars():
        row.comparison_json = {**(row.comparison_json or {}), "breakdown": breakdown}
    db.commit()
