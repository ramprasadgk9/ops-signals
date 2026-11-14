from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from sqlalchemy.orm import Session

from backend.app.identity import Actor, actor_name, current_actor
from backend.app.api.assistant import get_assistant
from backend.app.assistant.service import OperationalIntelligenceAssistant
from backend.app.autonomous.repository import (
    AutonomousJobRepository,
    AutonomousPolicyNotFoundError,
    AutonomousPolicyRepository,
    AutonomousPolicyRunRepository,
)
from backend.app.autonomous.execution import execute_autonomous_plan_once
from backend.app.autonomous.schemas import (
    AnalysisScope,
    AutonomousAnalysisPolicy,
    AutonomousPreviewRequest,
    AutonomousPreviewResponse,
    AutonomousRunRequest,
    AutonomousRunResponse,
    ExecutionPolicy,
    MonitoringSelection,
)
from backend.app.autonomous.services import MetricClassificationService, MetricDiscoveryService, MetricPlanBuilder
from backend.app.config import PrometheusConnectionConfig, parse_duration_seconds
from backend.app.models.db import get_db
from backend.app.models.entities import AutonomousPolicyEntity, FindingEntity, OperationalCaseEntity
from backend.app.services.prometheus_service import PrometheusQueryService, get_prometheus_connection, resolve_prometheus_connection

router = APIRouter(prefix="/api/autonomous", tags=["autonomous"])
AnswerWindow = Literal["1h", "6h", "24h", "7d"]


class AutonomousQuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    policy_run_id: str | None = None
    window: AnswerWindow = "24h"
    service: str | None = None
    metric_name: str | None = None


class AutonomousQuestionAnswer(BaseModel):
    headline: str
    answer: str
    ai_synthesis_used: bool = False
    priority: str
    confidence: float
    key_points: list[str]
    evidence: dict


def get_prometheus_query_service(
    config: PrometheusConnectionConfig = Depends(get_prometheus_connection),
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
        end = datetime.now(timezone.utc)
        start = end - timedelta(seconds=parse_duration_seconds(payload.execution.analysis_window))
        discovery = MetricDiscoveryService(prometheus)
        resolved_scope, discovered_metrics = discovery.discover(payload.scope, start=start, end=end)
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
        budget_excluded_metrics_count=plan.budget_excluded_metrics_count,
        budget_excluded_metrics=plan.budget_excluded_metrics,
        series_discovered=resolved_scope.series_discovered,
        series_available=resolved_scope.series_available,
        truncated=resolved_scope.truncated,
        starved_metrics_count=resolved_scope.starved_metrics_count,
        starved_metrics=resolved_scope.starved_metrics,
        warnings=plan.warnings,
        items=plan.items,
    )


@router.post("/run-once", response_model=AutonomousRunResponse)
def run_autonomous_once(
    payload: AutonomousRunRequest,
    prometheus: PrometheusQueryService = Depends(get_prometheus_query_service),
    db: Session = Depends(get_db),
    config: PrometheusConnectionConfig = Depends(get_prometheus_connection),
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


class AutonomousPolicySaveRequest(BaseModel):
    name: str = "Autonomous policy"
    datasource: str = "prometheus"
    backend: str = "grafana-stack"
    connection_id: str = "default"
    scope: AnalysisScope = Field(default_factory=AnalysisScope)
    monitoring_selection: MonitoringSelection
    execution: ExecutionPolicy = Field(default_factory=ExecutionPolicy)
    schedule_minutes: int | None = Field(default=None, ge=1)


class AutonomousPolicyStatusRequest(BaseModel):
    enabled: bool


def _policy_to_response(policy: AutonomousPolicyEntity) -> AutonomousAnalysisPolicy:
    return AutonomousAnalysisPolicy(
        id=policy.id,
        name=policy.name,
        datasource=policy.datasource,
        backend=policy.backend,
        connection_id=policy.connection_id,
        scope=AnalysisScope(**policy.scope_json),
        monitoring_selection=MonitoringSelection(**policy.monitoring_categories_json),
        execution=ExecutionPolicy(**policy.execution_policy_json),
        enabled=policy.enabled,
        schedule_minutes=policy.schedule_minutes,
        next_run_at=policy.next_run_at,
        last_run_status=policy.last_run_status,
        consecutive_failures=policy.consecutive_failures,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
        created_by=policy.created_by,
        edited_by=policy.edited_by,
        edited_at=policy.edited_at,
    )


@router.post("/policies", response_model=AutonomousAnalysisPolicy)
def create_autonomous_policy(
    payload: AutonomousPolicySaveRequest, db: Session = Depends(get_db), actor: Actor | None = Depends(current_actor)
) -> AutonomousAnalysisPolicy:
    resolve_prometheus_connection(payload.connection_id)
    policy = AutonomousPolicyRepository(db).create(
        name=payload.name,
        connection_id=payload.connection_id,
        datasource=payload.datasource,
        backend=payload.backend,
        scope=payload.scope.model_dump(),
        monitoring_categories=payload.monitoring_selection.model_dump(),
        execution_policy=payload.execution.model_dump(),
        schedule_minutes=payload.schedule_minutes,
        created_by=actor_name(actor),
    )
    return _policy_to_response(policy)


@router.get("/policies", response_model=list[AutonomousAnalysisPolicy])
def list_autonomous_policies(limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)) -> list[AutonomousAnalysisPolicy]:
    policies = AutonomousPolicyRepository(db).list(limit=limit)
    return [_policy_to_response(policy) for policy in policies]


@router.patch("/policies/{policy_id}", response_model=AutonomousAnalysisPolicy)
def update_autonomous_policy(
    policy_id: str, payload: AutonomousPolicySaveRequest, db: Session = Depends(get_db), actor: Actor | None = Depends(current_actor)
) -> AutonomousAnalysisPolicy:
    resolve_prometheus_connection(payload.connection_id)
    try:
        policy = AutonomousPolicyRepository(db).update_config(
            policy_id,
            connection_id=payload.connection_id,
            scope=payload.scope.model_dump(),
            monitoring_categories=payload.monitoring_selection.model_dump(),
            execution_policy=payload.execution.model_dump(),
            schedule_minutes=payload.schedule_minutes,
            edited_by=actor_name(actor),
        )
    except AutonomousPolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Policy not found.") from exc
    return _policy_to_response(policy)


@router.patch("/policies/{policy_id}/status", response_model=AutonomousAnalysisPolicy)
def set_autonomous_policy_status(
    policy_id: str, payload: AutonomousPolicyStatusRequest, db: Session = Depends(get_db), actor: Actor | None = Depends(current_actor)
) -> AutonomousAnalysisPolicy:
    """Backs the Configure screen's "Remove" (disable) and re-enable actions - the policy and its
    past runs/findings are kept, only the schedule pauses. See AutonomousPolicyRepository.set_enabled."""
    try:
        policy = AutonomousPolicyRepository(db).set_enabled(policy_id, enabled=payload.enabled, edited_by=actor_name(actor))
    except AutonomousPolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Policy not found.") from exc
    return _policy_to_response(policy)


@router.delete("/policies/{policy_id}")
def delete_autonomous_policy(policy_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        AutonomousPolicyRepository(db).delete(policy_id)
    except AutonomousPolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Policy not found.") from exc
    return {"deleted": True, "id": policy_id}


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


@router.post("/questions/answer", response_model=AutonomousQuestionAnswer)
def answer_autonomous_question(
    payload: AutonomousQuestionRequest,
    db: Session = Depends(get_db),
    assistant: OperationalIntelligenceAssistant | None = Depends(get_assistant),
) -> AutonomousQuestionAnswer:
    run_repo = AutonomousPolicyRunRepository(db)
    job_repo = AutonomousJobRepository(db)
    try:
        run = run_repo.get_run(payload.policy_run_id) if payload.policy_run_id else next(iter(run_repo.list_runs(limit=1)), None)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="autonomous policy run not found") from exc
    if run is None:
        return AutonomousQuestionAnswer(
            headline="No autonomous run data is available yet",
            answer="Run autonomous analysis once, then ask about the current run, skipped metrics, findings, or investigation priority.",
            priority="none",
            confidence=1.0,
            key_points=["No autonomous policy runs were found."],
            evidence={"policy_run_id": None, "finding_ids": [], "analysis_run_ids": [], "job_ids": []},
        )

    jobs = job_repo.get_jobs_for_run(run.id)
    service_filter = payload.service.strip() if payload.service else None
    metric_filter = payload.metric_name.strip() if payload.metric_name else None
    scoped_jobs = [
        job
        for job in jobs
        if (not service_filter or job.service == service_filter)
        and (not metric_filter or job.metric_name == metric_filter or job.logical_metric_name == metric_filter)
    ]
    analysis_run_ids = [job.analysis_run_id for job in scoped_jobs if job.analysis_run_id]

    findings_query = select(FindingEntity).where(FindingEntity.created_at >= _answer_window_start(payload.window))
    if analysis_run_ids:
        findings_query = findings_query.where(FindingEntity.analysis_run_id.in_(analysis_run_ids))
    if service_filter:
        findings_query = findings_query.where(FindingEntity.service == service_filter)
    if metric_filter:
        findings_query = findings_query.where(FindingEntity.metric_name == metric_filter)
    findings = list(
        db.execute(findings_query.order_by(FindingEntity.importance_score.desc(), FindingEntity.created_at.desc()).limit(20)).scalars().all()
    )
    cases = _cases_for_findings(db, [finding.id for finding in findings])
    question = payload.question.lower()

    if "skip" in question or "excluded" in question:
        answer = _answer_skipped_metrics(run, scoped_jobs or jobs, payload.window)
    elif "investigate" in question or "first" in question or "priority" in question:
        answer = _answer_investigation_priority(run, findings, scoped_jobs or jobs, cases)
    elif "changed" in question or "new" in question or "finding" in question:
        answer = _answer_what_changed(run, findings, scoped_jobs or jobs, cases, payload.window)
    elif "why" in question or "prioritized" in question:
        answer = _answer_prioritization(run, findings, scoped_jobs or jobs)
    else:
        answer = _answer_run_summary(run, findings, scoped_jobs or jobs, cases, payload.window)

    # Only ask the model to synthesize when it has something real to ground an answer in for the
    # *specific thing asked about*. An unscoped question ("summarize this run") is safe to
    # synthesize even with zero findings - "nothing happened this run" is itself a true, complete
    # answer. But a question scoped to a service/metric (service_filter/metric_filter set) with no
    # matching findings has nothing on-topic in the evidence at all - the generic run-wide stats
    # _evidence_text_for_llm always includes (metrics_discovered, job counts) are non-empty even
    # then, which let small local models fabricate answers about entities that were never actually
    # evidenced. Skip synthesis in that specific case; keep it everywhere else.
    has_unanswerable_scope = (service_filter or metric_filter) and not findings
    if assistant and not has_unanswerable_scope:
        evidence_text = _evidence_text_for_llm(run, findings, scoped_jobs or jobs, cases)
        synthesized = assistant.synthesize_from_evidence(payload.question, evidence_text)
        if synthesized:
            answer = answer.model_copy(update={"answer": synthesized, "ai_synthesis_used": True})

    return answer


@router.get("/scope-options")
def autonomous_scope_options(
    service_label: str = Query(default="service"),
    namespace_label: str = Query(default="namespace"),
    environment_label: str = Query(default="env"),
    cluster_label: str | None = Query(default=None, description="Defaults to the connection's cluster label."),
    window: str = Query(default="24h", description="Only list values seen in this recent window, e.g. 24h or 7d."),
    connection_id: str = Query(default="default", description="Which Prometheus connection to list values from."),
    prometheus: PrometheusQueryService = Depends(get_prometheus_query_service),
) -> dict[str, object]:
    try:
        window_seconds = parse_duration_seconds(window)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="window must be a duration like 24h or 7d") from exc
    end = datetime.now(timezone.utc)
    start = end - timedelta(seconds=window_seconds)
    connection = getattr(prometheus, "config", None)
    resolved_cluster_label = cluster_label or (connection.cluster_label if isinstance(connection, PrometheusConnectionConfig) else "cluster")
    return {
        "services": prometheus.label_values(service_label, start=start, end=end),
        "namespaces": prometheus.label_values(namespace_label, start=start, end=end),
        "environments": prometheus.label_values(environment_label, start=start, end=end),
        # [] for single-cluster data, which hides the cluster picker in the UI.
        "clusters": prometheus.label_values(resolved_cluster_label, start=start, end=end) if resolved_cluster_label else [],
        "cluster_label": resolved_cluster_label,
    }


def _answer_window_start(window: AnswerWindow) -> datetime:
    now = datetime.now(timezone.utc)
    if window == "1h":
        return now - timedelta(hours=1)
    if window == "6h":
        return now - timedelta(hours=6)
    if window == "7d":
        return now - timedelta(days=7)
    return now - timedelta(hours=24)


def _cases_for_findings(db: Session, finding_ids: list[int]) -> list[OperationalCaseEntity]:
    if not finding_ids:
        return []
    return list(
        db.execute(
            select(OperationalCaseEntity)
            .where(OperationalCaseEntity.finding_id.in_(finding_ids))
            .order_by(OperationalCaseEntity.updated_at.desc())
            .limit(20)
        ).scalars().all()
    )


def _job_label(job) -> str:
    service = job.service or "unknown service"
    metric = job.metric_name or job.logical_metric_name or "unknown metric"
    return f"{service} / {metric}"


def _finding_label(finding: FindingEntity) -> str:
    return f"{finding.service} / {finding.metric_name}: {finding.title}"


def _priority_from_findings(findings: list[FindingEntity], failed_count: int) -> str:
    top_importance = max((finding.importance_score for finding in findings), default=0.0)
    if top_importance >= 0.85 or failed_count > 0:
        return "high"
    if top_importance >= 0.6 or findings:
        return "medium"
    return "low"


def _evidence_text_for_llm(run, findings: list[FindingEntity], jobs, cases: list[OperationalCaseEntity]) -> str:
    lines = [f"Autonomous policy run {run.id}: status={run.status}, metrics_discovered={run.metrics_discovered or 0}, metrics_selected={run.metrics_selected or 0}."]
    failed_jobs = [job for job in jobs if job.status == "failed"]
    excluded_jobs = [job for job in jobs if job.status == "screened_out"]
    if failed_jobs or excluded_jobs:
        lines.append(f"{len(failed_jobs)} job(s) failed, {len(excluded_jobs)} metric(s) excluded before planning.")
    for finding in findings[:8]:
        lines.append(f"- Finding: {_finding_label(finding)} (importance {finding.importance_score:.2f}, health {finding.health_status}). {finding.summary}")
    for case in cases[:5]:
        rca = case.root_cause_summary or case.outcome_summary or "no RCA recorded yet"
        lines.append(f"- Case #{case.id}: {case.case_title} - {rca}")
    return "\n".join(lines)


def _answer_evidence(run, jobs, findings: list[FindingEntity], cases: list[OperationalCaseEntity] | None = None) -> dict:
    return {
        "policy_run_id": run.id,
        "analysis_run_ids": [job.analysis_run_id for job in jobs if job.analysis_run_id],
        "job_ids": [job.id for job in jobs],
        "finding_ids": [finding.id for finding in findings],
        "case_ids": [case.id for case in cases or []],
    }


def _answer_run_summary(run, findings: list[FindingEntity], jobs, cases: list[OperationalCaseEntity], window: AnswerWindow) -> AutonomousQuestionAnswer:
    completed = len([job for job in jobs if job.status == "completed"])
    skipped = len([job for job in jobs if job.status == "screened_out"])
    failed = len([job for job in jobs if job.status == "failed"])
    headline = f"Autonomous run {run.status} with {len(findings)} findings"
    key_points = [
        f"{run.metrics_discovered or 0} metrics discovered and {run.metrics_selected or 0} selected by policy.",
        f"{completed} jobs completed, {skipped} skipped, and {failed} failed.",
        f"{len(cases)} cases are linked to findings from the selected evidence.",
    ]
    budget_limited_jobs = (run.policy_snapshot_json or {}).get("budget_limited_jobs", 0)
    if budget_limited_jobs:
        key_points.append(
            f"Execution budget limited: {completed} executed of {run.metrics_selected or 0} selected "
            f"({budget_limited_jobs} excluded by max_metrics_per_run)."
        )
    if findings:
        key_points.append(f"Top finding: {_finding_label(findings[0])}.")
    else:
        key_points.append(f"No findings were found in the last {window}.")
    return AutonomousQuestionAnswer(
        headline=headline,
        answer="This answer is generated from stored autonomous run, job, finding, and case records. No external model is required.",
        priority=_priority_from_findings(findings, failed),
        confidence=0.9,
        key_points=key_points,
        evidence=_answer_evidence(run, jobs, findings, cases),
    )


def _answer_what_changed(run, findings: list[FindingEntity], jobs, cases: list[OperationalCaseEntity], window: AnswerWindow) -> AutonomousQuestionAnswer:
    failed = len([job for job in jobs if job.status == "failed"])
    if not findings:
        return AutonomousQuestionAnswer(
            headline=f"No stored findings were found in the last {window}",
            answer="The selected autonomous evidence does not contain a generated finding for this window. Review skipped or failed jobs if you expected broader coverage.",
            priority=_priority_from_findings([], failed),
            confidence=0.9,
            key_points=[f"{len(jobs)} jobs are in scope for this answer.", "No finding rows matched the selected run, service, metric, and time window."],
            evidence=_answer_evidence(run, jobs, [], cases),
        )
    grouped = {}
    for finding in findings:
        grouped.setdefault(finding.service, []).append(finding)
    key_points = [
        f"{service}: {len(items)} finding(s), highest importance {max(item.importance_score for item in items):.2f}."
        for service, items in list(grouped.items())[:5]
    ]
    key_points.insert(0, f"{len(findings)} finding(s) matched the selected evidence in the last {window}.")
    return AutonomousQuestionAnswer(
        headline=f"{len(grouped)} service(s) changed in the last {window}",
        answer=f"The strongest observed change is {_finding_label(findings[0])}.",
        priority=_priority_from_findings(findings, failed),
        confidence=0.88,
        key_points=key_points,
        evidence=_answer_evidence(run, jobs, findings, cases),
    )


def _answer_investigation_priority(run, findings: list[FindingEntity], jobs, cases: list[OperationalCaseEntity]) -> AutonomousQuestionAnswer:
    failed = len([job for job in jobs if job.status == "failed"])
    if not findings:
        return AutonomousQuestionAnswer(
            headline="No immediate investigation is recommended from stored findings",
            answer="No finding rows matched the selected autonomous run evidence. If this seems wrong, check whether the selected metrics produced enough samples and whether jobs were skipped or failed.",
            priority=_priority_from_findings([], failed),
            confidence=0.86,
            key_points=[f"{failed} job(s) failed.", f"{len([job for job in jobs if job.status == 'screened_out'])} job(s) were skipped by policy or filters."],
            evidence=_answer_evidence(run, jobs, [], cases),
        )
    top = findings[0]
    return AutonomousQuestionAnswer(
        headline=f"Investigate {top.service} / {top.metric_name} first",
        answer=f"It has the highest stored importance score ({top.importance_score:.2f}) among matching autonomous findings.",
        priority=_priority_from_findings(findings, failed),
        confidence=0.9,
        key_points=[
            top.title,
            top.summary,
            f"Health status: {top.health_status}; category: {top.category}.",
            f"{len(cases)} case(s) are already linked to matching findings.",
        ],
        evidence=_answer_evidence(run, jobs, findings, cases),
    )


def _answer_prioritization(run, findings: list[FindingEntity], jobs) -> AutonomousQuestionAnswer:
    failed = len([job for job in jobs if job.status == "failed"])
    if findings:
        top = findings[0]
        key_points = [
            f"{top.service} / {top.metric_name} has the highest importance score ({top.importance_score:.2f}).",
            f"The finding category is {top.category} and health status is {top.health_status}.",
            f"It is backed by signal ids: {', '.join(top.signal_ids or []) or 'none recorded'}.",
        ]
        headline = f"{top.service} is prioritized because its finding ranks highest"
    else:
        selected = len([job for job in jobs if job.status in {"completed", "running"}])
        key_points = [
            f"{selected} job(s) were selected/executed by the monitoring policy.",
            "No matching finding row was generated, so no service has a finding-backed priority.",
        ]
        headline = "No service has finding-backed priority for this evidence"
    return AutonomousQuestionAnswer(
        headline=headline,
        answer="Prioritization is derived from stored importance scores, job status, and finding metadata.",
        priority=_priority_from_findings(findings, failed),
        confidence=0.87,
        key_points=key_points,
        evidence=_answer_evidence(run, jobs, findings),
    )


def _answer_skipped_metrics(run, jobs, window: AnswerWindow) -> AutonomousQuestionAnswer:
    skipped = [job for job in jobs if job.status == "screened_out"]
    failed = [job for job in jobs if job.status == "failed"]
    examples = skipped[:5] or failed[:5]
    key_points = [
        f"{len(skipped)} metric job(s) were skipped and {len(failed)} failed in the selected run evidence.",
        *[
            f"{_job_label(job)}: {job.skip_reason_detail or job.skip_reason_code or job.error_message or 'No detail recorded'}"
            for job in examples
        ],
    ]
    return AutonomousQuestionAnswer(
        headline=f"{len(skipped)} skipped metric job(s) in the selected evidence",
        answer=f"Skipped and failed metrics are read from autonomous job rows for the latest selected run, filtered to the last {window} context.",
        priority="medium" if skipped or failed else "low",
        confidence=0.9,
        key_points=key_points,
        evidence=_answer_evidence(run, jobs, []),
    )


def _policy_run_to_dict(run) -> dict:
    snapshot = run.policy_snapshot_json or {}
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
        # None for runs saved before this count existed: unknown, not zero.
        "jobs_not_checked": snapshot.get("jobs_not_checked"),
        "budget_limited_jobs": snapshot.get("budget_limited_jobs", 0),
        "budget_excluded_metrics_count": snapshot.get("budget_excluded_metrics_count", 0),
        "budget_excluded_metrics": snapshot.get("budget_excluded_metrics", []),
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
