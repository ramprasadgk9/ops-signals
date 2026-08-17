from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from sqlalchemy.orm import Session

from backend.app.autonomous.repository import AutonomousJobRepository, AutonomousPolicyRunRepository
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


@router.get("/policy-runs")
def list_autonomous_policy_runs(
    status: str | None = Query(default=None),
    policy_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[dict]:
    runs = AutonomousPolicyRunRepository(db).list_runs(status=status, policy_id=policy_id, limit=limit)
    return [_policy_run_to_dict(run) for run in runs]


@router.get("/policy-runs/{policy_run_id}")
def get_autonomous_policy_run(policy_run_id: str, db: Session = Depends(get_db)) -> dict:
    run = AutonomousPolicyRunRepository(db).get_run(policy_run_id)
    return _policy_run_to_dict(run)


@router.get("/policy-runs/{policy_run_id}/jobs")
def list_autonomous_policy_run_jobs(policy_run_id: str, db: Session = Depends(get_db)) -> list[dict]:
    AutonomousPolicyRunRepository(db).get_run(policy_run_id)
    jobs = AutonomousJobRepository(db).get_jobs_for_run(policy_run_id)
    return [_job_to_dict(job) for job in jobs]


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


def _policy_run_to_dict(run) -> dict:
    return {
        "policy_run_id": run.id,
        "id": run.id,
        "policy_id": run.policy_id,
        "trigger": run.trigger,
        "status": run.status,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "policy_snapshot": run.policy_snapshot_json,
        "metrics_discovered": run.metrics_discovered,
        "metrics_selected": run.metrics_selected,
        "jobs_planned": run.jobs_planned,
        "jobs_completed": run.jobs_completed,
        "jobs_skipped": run.jobs_skipped,
        "jobs_failed": run.jobs_failed,
        "findings_created": run.findings_created,
        "error_summary": run.error_summary,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


def _job_to_dict(job) -> dict:
    return {
        "job_id": job.id,
        "id": job.id,
        "policy_run_id": job.policy_run_id,
        "status": job.status,
        "datasource": job.datasource,
        "environment": job.environment,
        "namespace": job.namespace,
        "service": job.service,
        "metric_name": job.metric_name,
        "logical_metric_name": job.logical_metric_name,
        "category": job.category,
        "concept": job.concept,
        "promql": job.promql,
        "analysis_window": job.analysis_window,
        "aggregation_strategy": job.aggregation_strategy,
        "transformation": job.transformation,
        "classification_confidence": job.classification_confidence,
        "selection_reason": job.selection_reason,
        "skip_reason_code": job.skip_reason_code,
        "skip_reason_detail": job.skip_reason_detail,
        "retry_count": job.retry_count,
        "analysis_run_id": job.analysis_run_id,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "duration_ms": job.duration_ms,
        "error_type": job.error_type,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }
