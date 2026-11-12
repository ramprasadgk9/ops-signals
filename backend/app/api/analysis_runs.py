from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from backend.app.models.api_schema import AnalysisRunOut
from backend.app.models.db import get_db
from backend.app.models.entities import AnalysisRunEntity
from backend.app.services.point_retention import points_deleted, retention_days

router = APIRouter(prefix="/api/analysis-runs", tags=["analysis-runs"])


@router.get("", response_model=list[AnalysisRunOut])
def list_analysis_runs(
    db: Session = Depends(get_db),
    limit: int | None = Query(None, ge=1, le=1000, description="Newest runs only; all runs when omitted."),
    service: str | None = None,
    metric_name: str | None = None,
) -> list[AnalysisRunOut]:
    engine = db.get_bind()
    columns = {column["name"] for column in inspect(engine).get_columns("analysis_runs")}
    optional_columns = [
        "file_name",
        "router_version",
        "feature_extractor_version",
        "analyzer_registry_version",
        "series_profile_json",
        "router_decisions_json",
        "executed_analyzers_json",
        "generated_findings_json",
    ]
    select_columns = [
        "id",
        "source_type",
        "provider",
        "service",
        "metric_name",
        "start_time",
        "end_time",
        "sample_count",
        "status",
        "created_at",
    ]
    for column in optional_columns:
        if column in columns:
            select_columns.insert(2 if column == "file_name" else len(select_columns), column)
    # Each run carries its router/profile/findings JSON, so a long-lived install's full list runs to
    # gigabytes; callers that need only the latest runs pass limit (and service/metric_name).
    filters = []
    params: dict[str, object] = {}
    if service is not None:
        filters.append("service = :service")
        params["service"] = service
    if metric_name is not None:
        filters.append("metric_name = :metric_name")
        params["metric_name"] = metric_name
    where = f" WHERE {' AND '.join(filters)}" if filters else ""
    sql = f"SELECT {', '.join(select_columns)} FROM analysis_runs{where} ORDER BY created_at DESC"
    if limit is not None:
        sql += " LIMIT :limit"
        params["limit"] = limit
    rows = db.execute(text(sql), params).mappings().all()
    return [
        AnalysisRunOut(
            id=row["id"],
            source_type=row["source_type"],
            file_name=row.get("file_name"),
            provider=row["provider"] or "generic",
            service=row["service"],
            metric_name=row["metric_name"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            sample_count=row["sample_count"],
            status=row["status"],
            router_version=row.get("router_version"),
            feature_extractor_version=row.get("feature_extractor_version"),
            analyzer_registry_version=row.get("analyzer_registry_version"),
            series_profile_json=row.get("series_profile_json"),
            router_decisions_json=row.get("router_decisions_json"),
            executed_analyzers_json=row.get("executed_analyzers_json"),
            generated_findings_json=row.get("generated_findings_json"),
            created_at=row["created_at"],
        )
        for row in rows
    ]


@router.get("/{run_id}", response_model=AnalysisRunOut)
def get_analysis_run(run_id: str, db: Session = Depends(get_db)) -> AnalysisRunOut:
    engine = db.get_bind()
    columns = {column["name"] for column in inspect(engine).get_columns("analysis_runs")}
    optional_columns = [
        "file_name",
        "router_version",
        "feature_extractor_version",
        "analyzer_registry_version",
        "series_profile_json",
        "router_decisions_json",
        "executed_analyzers_json",
        "generated_findings_json",
        "connection_id",
        "promql",
    ]
    select_columns = [
        "id",
        "source_type",
        "provider",
        "service",
        "metric_name",
        "start_time",
        "end_time",
        "sample_count",
        "status",
        "created_at",
    ]
    for column in optional_columns:
        if column in columns:
            select_columns.insert(2 if column == "file_name" else len(select_columns), column)
    sql = text(f"SELECT {', '.join(select_columns)} FROM analysis_runs WHERE id = :run_id")
    run = db.execute(sql, {"run_id": run_id}).mappings().one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="analysis run not found")
    return AnalysisRunOut(
        id=run["id"],
        source_type=run["source_type"],
        file_name=run.get("file_name"),
        provider=run["provider"] or "generic",
        service=run["service"],
        metric_name=run["metric_name"],
        start_time=run["start_time"],
        end_time=run["end_time"],
        sample_count=run["sample_count"],
        status=run["status"],
        router_version=run.get("router_version"),
        feature_extractor_version=run.get("feature_extractor_version"),
        analyzer_registry_version=run.get("analyzer_registry_version"),
        series_profile_json=run.get("series_profile_json"),
        router_decisions_json=run.get("router_decisions_json"),
        executed_analyzers_json=run.get("executed_analyzers_json"),
        generated_findings_json=run.get("generated_findings_json"),
        created_at=run["created_at"],
        connection_id=run.get("connection_id"),
        promql=run.get("promql"),
        points_deleted=points_deleted(run["end_time"]),
        points_retention_days=retention_days() or None,
    )
