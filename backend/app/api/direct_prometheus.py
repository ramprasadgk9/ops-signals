from __future__ import annotations

import copy
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.config import PrometheusConnectionConfig, get_prometheus_config
from backend.app.models.db import get_db
from backend.app.models.entities import BehaviorFindingEntity, FindingEntity, SignalEntity
from backend.app.models.prometheus import (
    DirectPrometheusAnalysisOut,
    DirectPrometheusAnalysisRequest,
    PrometheusConnectionTestOut,
    PrometheusConnectionTestRequest,
    PrometheusConnectionsOut,
    PrometheusConnectionOut,
    PrometheusLabelValuesOut,
    PrometheusPreviewOut,
    PrometheusQueryRequest,
)
from backend.app.services.prometheus_service import PrometheusQueryService, configured_connection
from intelligence.config import load_config
from intelligence.pipeline import SignalPipeline


router = APIRouter(prefix="/api/prometheus", tags=["prometheus"])
analysis_router = APIRouter(prefix="/api/analysis", tags=["analysis"])


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def get_prometheus_query_service(
    config: PrometheusConnectionConfig = Depends(get_prometheus_config),
) -> PrometheusQueryService:
    return PrometheusQueryService(config)


@router.get("/connections", response_model=PrometheusConnectionsOut)
def list_prometheus_connections(
    config: PrometheusConnectionConfig = Depends(get_prometheus_config),
) -> PrometheusConnectionsOut:
    connection = configured_connection(config)
    return PrometheusConnectionsOut(
        connections=[
            PrometheusConnectionOut(
                id=connection.id,
                name=connection.name,
                base_url=connection.base_url,
                configured=connection.configured,
            )
        ]
    )


@router.post("/test-connection", response_model=PrometheusConnectionTestOut)
def test_prometheus_connection(
    payload: PrometheusConnectionTestRequest,
    service: PrometheusQueryService = Depends(get_prometheus_query_service),
) -> PrometheusConnectionTestOut:
    if payload.connection_id != "default":
        raise HTTPException(status_code=404, detail="Prometheus connection not found")
    available, version, latency_ms, message = service.test_connection()
    return PrometheusConnectionTestOut(available=available, version=version, latency_ms=latency_ms, message=message)


@router.get("/label-values", response_model=PrometheusLabelValuesOut)
def get_prometheus_label_values(
    label: str,
    connection_id: str = "default",
    service: PrometheusQueryService = Depends(get_prometheus_query_service),
) -> PrometheusLabelValuesOut:
    if connection_id != "default":
        raise HTTPException(status_code=404, detail="Prometheus connection not found")
    return PrometheusLabelValuesOut(connection_id=connection_id, label=label, values=service.label_values(label))


@router.post("/preview", response_model=PrometheusPreviewOut)
def preview_prometheus_query(
    payload: PrometheusQueryRequest,
    service: PrometheusQueryService = Depends(get_prometheus_query_service),
) -> PrometheusPreviewOut:
    if payload.connection_id != "default":
        raise HTTPException(status_code=404, detail="Prometheus connection not found")
    return service.preview(payload.query, payload.start, payload.end, payload.step)


@analysis_router.post("/prometheus", response_model=DirectPrometheusAnalysisOut)
def run_direct_prometheus_analysis(
    payload: DirectPrometheusAnalysisRequest,
    db: Session = Depends(get_db),
    service: PrometheusQueryService = Depends(get_prometheus_query_service),
    config: PrometheusConnectionConfig = Depends(get_prometheus_config),
) -> DirectPrometheusAnalysisOut:
    if payload.connection_id != "default":
        raise HTTPException(status_code=404, detail="Prometheus connection not found")
    preview = service.preview(payload.query, payload.start, payload.end, payload.step)
    if preview.sample_count == 0:
        raise HTTPException(status_code=400, detail="The query succeeded, but Prometheus returned no samples for the selected time range.")
    if preview.series_count != 1:
        raise HTTPException(
            status_code=400,
            detail=f"The query returned {preview.series_count} series. Select one series or refine the label filters before running analysis.",
        )

    records: list[dict[str, object]] = []
    selected_series = preview.series[0]
    labels = selected_series.labels
    for sample in selected_series.samples:
        records.append(
            {
                "timestamp": sample.timestamp,
                "metric_name": labels.get("__name__") or payload.metric,
                "value": sample.value,
                "service": labels.get("service") or labels.get("service_name") or labels.get("job") or labels.get("app") or payload.service,
                "source": "prometheus",
                "host": labels.get("instance"),
                "namespace": labels.get("namespace"),
                "pod": labels.get("pod"),
                "env": labels.get("env") or labels.get("environment"),
                "series_id": ",".join(f"{key}={value}" for key, value in sorted(labels.items())),
                **{f"label_{key}": value for key, value in labels.items()},
            }
        )

    try:
        pipeline_config = copy.deepcopy(load_config(_repo_root() / "config" / "providers" / "prometheus.yaml"))
        pipeline_config.input.source_type = "prometheus"
        pipeline_config.input.provider = "prometheus"
        pipeline_config.input.interval = f"{max(int(preview.step_seconds / 60), 1)}m" if preview.step_seconds >= 60 else f"{preview.step_seconds}s"
        pipeline_config.input.service = payload.service
        pipeline_config.input.metric_name = payload.metric
        pipeline_config.input.timestamp_column = "timestamp"
        pipeline_config.input.value_column = "value"
        pipeline_config.input.metric_column = "metric_name"
        pipeline_config.input.required_columns = ["timestamp", "metric_name", "value"]
        pipeline_config.input.provider_mappings = {}
        pipeline_config.output.save_normalized_data = True
        pipeline_config.output.save_signals = True
        pipeline_config.output.save_question_answers = True
        pipeline_config.output.save_embeddings = False
        pipeline_config.embeddings.enabled = False
        if payload.analyzer:
            if payload.analyzer not in pipeline_config.analysis.analyzers:
                raise HTTPException(status_code=400, detail=f"analyzer '{payload.analyzer}' is not configured")
            pipeline_config.analysis.selection_mode = "manual_override"
            pipeline_config.analysis.selected_analyzers = [payload.analyzer]

        result = SignalPipeline(pipeline_config).run_dataframe(
            pd.DataFrame.from_records(records),
            run_metadata={
                "datasource_uid": payload.connection_id,
                "datasource_name": configured_connection(config).name,
                "promql": payload.query,
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
        raise HTTPException(status_code=500, detail=f"analysis failed: {exc}") from exc

    finding_rows = db.execute(select(FindingEntity).where(FindingEntity.analysis_run_id == result.analysis_run_id)).scalars().all()
    signal_rows = db.execute(select(SignalEntity).where(SignalEntity.analysis_run_id == result.analysis_run_id)).scalars().all()
    findings_count = len(finding_rows)
    signal_count = len(signal_rows)
    behavior_count = db.execute(select(func.count(BehaviorFindingEntity.id)).where(BehaviorFindingEntity.analysis_run_id == result.analysis_run_id)).scalar() or 0
    actual_start = min((sample.timestamp for sample in selected_series.samples), default=None)
    actual_end = max((sample.timestamp for sample in selected_series.samples), default=None)

    return DirectPrometheusAnalysisOut(
        analysis_run_id=result.analysis_run_id,
        connection_id=payload.connection_id,
        connection_name=configured_connection(config).name,
        service=payload.service,
        metric_name=payload.metric,
        query=payload.query,
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
            }
            for finding in finding_rows
        ],
    )
