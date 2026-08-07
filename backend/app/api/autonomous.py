from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from sqlalchemy.orm import Session

from backend.app.autonomous.execution import execute_autonomous_plan_once
from backend.app.autonomous.schemas import AutonomousPreviewRequest, AutonomousPreviewResponse, AutonomousRunRequest, AutonomousRunResponse
from backend.app.autonomous.services import MetricClassificationService, MetricDiscoveryService, MetricPlanBuilder
from backend.app.config import PrometheusConnectionConfig, get_prometheus_config
from backend.app.models.db import get_db
from backend.app.services.prometheus_service import PrometheusQueryService

router = APIRouter(prefix="/api/autonomous", tags=["autonomous"])


def get_prometheus_query_service(
    config: PrometheusConnectionConfig = Depends(get_prometheus_config),
) -> PrometheusQueryService:
    return PrometheusQueryService(config)


@router.post("/preview", response_model=AutonomousPreviewResponse)
def preview_autonomous_plan(
    payload: AutonomousPreviewRequest,
    prometheus: PrometheusQueryService = Depends(get_prometheus_query_service),
) -> AutonomousPreviewResponse:
    if not payload.selected_categories:
        raise HTTPException(status_code=422, detail="At least one monitoring category is required.")

    try:
        discovery = MetricDiscoveryService(prometheus)
        resolved_scope, discovered_metrics = discovery.discover(payload.scope)
        classifier = MetricClassificationService()
        plan = MetricPlanBuilder().build(
            resolved_scope=resolved_scope,
            discovered_metrics=discovered_metrics,
            selected_categories=payload.selected_categories,
            execution=payload.execution,
            custom_constraints=payload.selected_custom_constraints,
            classifier=classifier,
            datasource=payload.datasource,
            backend=payload.backend,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AutonomousPreviewResponse(
        scope_summary=plan.scope_summary,
        monitoring_summary=plan.monitoring_summary,
        metrics_discovered=plan.total_metrics_discovered,
        metrics_classified=plan.total_metrics_classified,
        metrics_selected=plan.total_metrics_selected,
        metrics_matched=plan.total_metrics_selected,
        metrics_excluded=plan.total_metrics_excluded,
        planned_jobs=plan.planned_jobs,
        budget_limited_jobs=plan.budget_limited_jobs,
        budget_limited=plan.budget_limited_jobs,
        warnings=plan.warnings,
        items=plan.items,
    )


@router.post("/run-once", response_model=AutonomousRunResponse)
def run_autonomous_once(
    payload: AutonomousRunRequest,
    prometheus: PrometheusQueryService = Depends(get_prometheus_query_service),
    db: Session = Depends(get_db),
    config: PrometheusConnectionConfig = Depends(get_prometheus_config),
) -> AutonomousRunResponse:
    preview = preview_autonomous_plan(payload, prometheus)
    try:
        return execute_autonomous_plan_once(
            preview=preview,
            prometheus=prometheus,
            db=db,
            config=config,
            analysis_window=payload.execution.analysis_window,
            step=payload.execution.interval,
            dry_run=payload.dry_run,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/scope-options")
def autonomous_scope_options(
    service_label: str = Query(default="service"),
    namespace_label: str = Query(default="namespace"),
    environment_label: str = Query(default="env"),
    prometheus: PrometheusQueryService = Depends(get_prometheus_query_service),
) -> dict[str, list[str]]:
    return {
        "services": prometheus.label_values(service_label),
        "namespaces": prometheus.label_values(namespace_label),
        "environments": prometheus.label_values(environment_label),
    }
