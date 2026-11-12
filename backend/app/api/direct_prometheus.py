from __future__ import annotations

import re

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.autonomous.drilldown import drill_down_findings
from backend.app.config import DrillDownConfig, PrometheusConnectionConfig, get_alert_enrichment_config, get_drilldown_config, get_prometheus_connections
from backend.app.models.db import get_db
from backend.app.models.entities import BehaviorFindingEntity, FindingEntity, SignalEntity
from backend.app.models.prometheus import (
    CombinedSeriesOut,
    DirectPrometheusAnalysisOut,
    DirectPrometheusAnalysisRequest,
    PrometheusConnectionTestOut,
    PrometheusConnectionTestRequest,
    PrometheusConnectionsOut,
    PrometheusConnectionOut,
    PrometheusLabelValuesOut,
    PrometheusPreviewOut,
    PrometheusQueryRequest,
    PrometheusSeriesOut,
    RecordingRulesOut,
)
from backend.app.services.prometheus_service import (
    PrometheusQueryService,
    _observed_interval,
    _prometheus_series_to_normalized,
    configured_connection,
    get_prometheus_connection,
)
from backend.app.services.alert_rules import alerts_for_findings
from backend.app.services.finding_plain import finding_plain
from backend.app.services.pod_split import find_pod_split
from backend.app.services.recording_rules import recording_rules
from backend.app.services.timeseries_routing_service import build_csv_routing_config
from backend.app.api.errors import internal_error
from intelligence.pipeline import SignalPipeline


router = APIRouter(prefix="/api/prometheus", tags=["prometheus"])
analysis_router = APIRouter(prefix="/api/analysis", tags=["analysis"])


def get_prometheus_query_service(
    config: PrometheusConnectionConfig = Depends(get_prometheus_connection),
) -> PrometheusQueryService:
    return PrometheusQueryService(config)


_SIMPLE_SELECTOR = re.compile(r"^\s*([a-zA-Z_:][a-zA-Z0-9_:]*)\s*(?:\{(.*)\})?\s*$", re.DOTALL)


def _multi_series_detail(query: str, series: list[PrometheusSeriesOut], cluster_label: str | None) -> str:
    """Says which label tells the returned series apart and how to pick one - for a plain selector,
    with the exact query - so "refine the filters" isn't left to guesswork."""
    values: dict[str, set[str]] = {}
    for item in series:
        for key, value in item.labels.items():
            if key != "__name__":
                values.setdefault(key, set()).add(value)
    differing = sorted(key for key, seen in values.items() if len(seen) > 1 or any(key not in item.labels for item in series))
    if not differing:
        return f"This query matched {len(series)} series. Refine the label filters to pick one."
    # The cluster label wins: it is the usual reason on Mimir/Thanos, and other labels (instance)
    # usually differ only because the clusters do.
    key = cluster_label if cluster_label in differing else differing[0]
    shown = sorted(values[key])
    listed = f"{', '.join(shown[:5])}{', ...' if len(shown) > 5 else ''}"
    what = f"{len(shown)} clusters" if key == cluster_label else f"{len(series)} series, which differ by {key}"
    pick = next(item.labels[key] for item in series if key in item.labels)
    message = f'This query matched {what} ({listed}). Add {key}="{pick}" to pick one'
    match = _SIMPLE_SELECTOR.match(query)
    if match:
        name, matchers = match.group(1), (match.group(2) or "").strip().rstrip(",")
        return f'{message}: {name}{{{matchers + "," if matchers else ""}{key}="{pick}"}}'
    return f"{message}, or aggregate {key} away."


@router.get("/connections", response_model=PrometheusConnectionsOut)
def list_prometheus_connections() -> PrometheusConnectionsOut:
    connections = get_prometheus_connections()
    return PrometheusConnectionsOut(
        connections=[
            PrometheusConnectionOut(
                id=profile.id,
                name=profile.name,
                base_url=profile.base_url,
                configured=profile.configured,
                is_default=connection.id == connections.default_id,
                match_labels=connection.match_labels,
                cluster_label=connection.cluster_label,
            )
            for connection in connections.connections
            for profile in [configured_connection(connection)]
        ]
    )


@router.post("/test-connection", response_model=PrometheusConnectionTestOut)
def test_prometheus_connection(
    payload: PrometheusConnectionTestRequest,
    service: PrometheusQueryService = Depends(get_prometheus_query_service),
) -> PrometheusConnectionTestOut:
    available, version, latency_ms, message = service.test_connection()
    return PrometheusConnectionTestOut(available=available, version=version, latency_ms=latency_ms, message=message)


@router.get("/label-values", response_model=PrometheusLabelValuesOut)
def get_prometheus_label_values(
    label: str,
    connection_id: str = "default",
    match: list[str] = Query(default=[], description="Only values on series these selectors match, e.g. up{service=\"checkout\"}."),
    start: datetime | None = None,
    end: datetime | None = None,
    service: PrometheusQueryService = Depends(get_prometheus_query_service),
    config: PrometheusConnectionConfig = Depends(get_prometheus_connection),
) -> PrometheusLabelValuesOut:
    values = service.label_values(label, matchers=match or None, start=start, end=end)
    return PrometheusLabelValuesOut(connection_id=config.id, label=label, values=values)


@router.get("/recording-rules", response_model=RecordingRulesOut)
def get_recording_rules(
    connection_id: str = "default",
    service: PrometheusQueryService = Depends(get_prometheus_query_service),
) -> RecordingRulesOut:
    """The connection's recording rules, so the Metrics list can mark their names and show the saved query."""
    return recording_rules(service)


@router.post("/preview", response_model=PrometheusPreviewOut)
def preview_prometheus_query(
    payload: PrometheusQueryRequest,
    service: PrometheusQueryService = Depends(get_prometheus_query_service),
    config: PrometheusConnectionConfig = Depends(get_prometheus_connection),
) -> PrometheusPreviewOut:
    preview = service.preview(payload.query, payload.start, payload.end, payload.step)
    preview.pods = _pod_split(payload.query, preview, None, config)
    return preview


def _pod_split(query: str, preview: PrometheusPreviewOut, metric: str | None, config: PrometheusConnectionConfig):
    return find_pod_split(query, preview.series, metric=metric, split_labels=get_drilldown_config().labels, cluster_label=config.cluster_label)


# How many series the label check may read when a query has more pods than max_series. Only the
# labels are kept, from about 50 points per series.
POD_LABELS_MAX_SERIES = 2000


def _too_many_series(exc: HTTPException) -> bool:
    return isinstance(exc.detail, str) and "exceeds max_series" in exc.detail


def _pod_split_from_labels(service: PrometheusQueryService, payload: DirectPrometheusAnalysisRequest, config: PrometheusConnectionConfig):
    span = max(int((payload.end - payload.start).total_seconds()), 1)
    try:
        rows = service.query_result(payload.query, start=payload.start, end=payload.end, step_seconds=max(span // 50, 1), max_series=POD_LABELS_MAX_SERIES)
    except HTTPException:
        return None
    series = [PrometheusSeriesOut(labels=row.get("metric") or {}, samples=[]) for row in rows]
    return find_pod_split(payload.query, series, metric=payload.metric, split_labels=get_drilldown_config().labels, cluster_label=config.cluster_label)


@analysis_router.post("/prometheus", response_model=DirectPrometheusAnalysisOut)
def run_direct_prometheus_analysis(
    payload: DirectPrometheusAnalysisRequest,
    db: Session = Depends(get_db),
    service: PrometheusQueryService = Depends(get_prometheus_query_service),
    config: PrometheusConnectionConfig = Depends(get_prometheus_connection),
) -> DirectPrometheusAnalysisOut:
    query = payload.query
    combined: CombinedSeriesOut | None = None
    try:
        preview = service.preview(query, payload.start, payload.end, payload.step)
    except HTTPException as exc:
        # More pods than max_series: tell them apart from their labels alone, then read only the
        # combined line. Too many to draw or to name the odd one, but one line is enough to analyze.
        pods = _pod_split_from_labels(service, payload, config) if payload.combine and _too_many_series(exc) else None
        if pods is None:
            raise
        preview = None
    else:
        if preview.sample_count == 0:
            raise HTTPException(status_code=400, detail="The query succeeded, but Prometheus returned no samples for the selected time range.")
        pods = _pod_split(query, preview, payload.metric, config) if preview.series_count > 1 and payload.combine else None
    if pods is not None:
        how = pods.suggested_combine if payload.combine == "auto" else payload.combine
        combined = CombinedSeriesOut(label=pods.label, count=len(pods.values), how=how, original_query=payload.query, odd=pods.odd)
        query = pods.queries[how]
        preview = service.preview(query, payload.start, payload.end, payload.step)
        if preview.sample_count == 0:
            raise HTTPException(status_code=400, detail="The query succeeded, but Prometheus returned no samples for the selected time range.")
    if preview.series_count != 1:
        raise HTTPException(status_code=400, detail=_multi_series_detail(query, preview.series, config.cluster_label))

    selected_series = preview.series[0]
    labels = selected_series.labels
    observed_interval = _observed_interval(selected_series.samples, preview.step_seconds)
    normalized = _prometheus_series_to_normalized(
        samples=selected_series.samples,
        labels=labels,
        service=payload.service,
        metric=payload.metric,
        cluster_label=config.cluster_label,
    )

    try:
        pipeline_config = build_csv_routing_config(
            provider="prometheus",
            service=payload.service,
            metric_name=payload.metric,
            interval=observed_interval,
            analyzer_id=payload.analyzer or "all",
            preview=False,
        )
        pipeline_config.input.source_type = "prometheus"
        pipeline_config.input.required_columns = ["timestamp", "metric_name", "value"]
        pipeline_config.input.provider_mappings = {}

        result = SignalPipeline(pipeline_config).run_normalized(
            normalized,
            run_metadata={
                "datasource_uid": config.id,
                "connection_id": config.id,
                "datasource_name": configured_connection(config).name,
                "promql": query,
                **({"combined": combined.model_dump()} if combined else {}),
                "from": preview.start.isoformat(),
                "to": preview.end.isoformat(),
                "step_seconds": preview.step_seconds,
                "series_count": preview.series_count,
                "sample_count": preview.sample_count,
                "requested_analyzer": payload.analyzer,
            },
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise internal_error("Analysis failed", exc) from exc

    if combined is not None:
        # The pods were combined, so say which of them the change came from - the drill-down
        # scheduled runs use, here always on. It never fails the run.
        try:
            drill_down_findings(
                db=db,
                prometheus=service,
                promql=query,
                step=payload.step,
                result=result,
                config=DrillDownConfig(labels=[combined.label], max_findings_per_job=get_drilldown_config().max_findings_per_job, enabled=True),
            )
        except Exception:  # noqa: BLE001
            db.rollback()

    finding_rows = db.execute(select(FindingEntity).where(FindingEntity.analysis_run_id == result.analysis_run_id)).scalars().all()
    signal_rows = db.execute(select(SignalEntity).where(SignalEntity.analysis_run_id == result.analysis_run_id)).scalars().all()
    service_labels = get_alert_enrichment_config().service_labels
    plain_wording = finding_plain(db, list(finding_rows), alerts=alerts_for_findings(db, list(finding_rows), service_labels), service_labels=service_labels)
    findings_count = len(finding_rows)
    signal_count = len(signal_rows)
    behavior_count = db.execute(select(func.count(BehaviorFindingEntity.id)).where(BehaviorFindingEntity.analysis_run_id == result.analysis_run_id)).scalar() or 0
    actual_start = min((sample.timestamp for sample in selected_series.samples), default=None)
    actual_end = max((sample.timestamp for sample in selected_series.samples), default=None)

    return DirectPrometheusAnalysisOut(
        analysis_run_id=result.analysis_run_id,
        connection_id=config.id,
        connection_name=configured_connection(config).name,
        service=payload.service,
        metric_name=payload.metric,
        query=query,
        requested_start=preview.start,
        requested_end=preview.end,
        actual_start=actual_start,
        actual_end=actual_end,
        step=preview.step,
        step_seconds=preview.step_seconds,
        sample_count=preview.sample_count,
        series_count=preview.series_count,
        findings_count=int(findings_count),
        signal_count=int(signal_count),
        behavior_findings_count=int(behavior_count),
        warnings=preview.warnings,
        analyzer_selection_mode=pipeline_config.analysis.selection_mode,
        analyzer_routing=result.analyzer_routing,
        executed_analyzers=result.executed_analyzers,
        analyzer_executions=result.analyzer_executions,
        series=preview.series,
        signals=[
            {
                "id": signal.signal_id,
                "signal_type": signal.signal_type,
                "analyzer_id": signal.analyzer_id,
                "metric_name": signal.metric_name,
                "service": signal.service,
                "severity": signal.severity,
                "confidence": signal.confidence,
                "importance_score": signal.importance_score,
                "start_time": signal.start_time,
                "end_time": signal.end_time,
                "summary": signal.summary,
                "evidence": signal.evidence_json or {},
            }
            for signal in signal_rows
        ],
        findings=[
            {
                "id": finding.id,
                "service": finding.service,
                "metric_name": finding.metric_name,
                "title": finding.title,
                "summary": finding.summary,
                "category": finding.category,
                "health_status": finding.health_status,
                "importance_score": finding.importance_score,
                "investigation_priority": finding.investigation_priority,
                "signal_ids": finding.signal_ids,
                "comparison_json": finding.comparison_json or {},
                "analysis_run_id": finding.analysis_run_id,
                "created_at": finding.created_at,
                "plain": plain_wording.get(finding.id),
            }
            for finding in finding_rows
        ],
        combined=combined,
    )
