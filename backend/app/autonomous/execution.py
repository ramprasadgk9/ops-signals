from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from time import perf_counter
from uuid import uuid4

import pandas as pd
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.app.autonomous.drilldown import drill_down_findings
from backend.app.behavior_intelligence.service import evaluate_runs_together
from backend.app.autonomous.metric_executor import MetricAnalysisExecutor
from backend.app.autonomous.repository import AutonomousJobRepository, AutonomousPolicyRunRepository, utc_now
from backend.app.autonomous.schemas import AutonomousJobRunResult, AutonomousPreviewResponse, AutonomousRunResponse, MetricPlanItem
from backend.app.config import DrillDownConfig, PrometheusConnectionConfig, get_drilldown_config
from backend.app.models.entities import AutonomousMetricJobEntity
from backend.app.services.prometheus_service import PrometheusQueryService, configured_connection
from backend.app.services.run_points import series_key
from backend.app.services.timeseries_routing_service import build_csv_routing_config


def execute_autonomous_plan_once(
    *,
    preview: AutonomousPreviewResponse,
    prometheus: PrometheusQueryService,
    db: Session,
    config: PrometheusConnectionConfig,
    analysis_window: str,
    step: str,
    dry_run: bool = False,
    policy_id: str | None = None,
    trigger: str | None = None,
    drilldown: DrillDownConfig | None = None,
) -> AutonomousRunResponse:
    drilldown = drilldown if drilldown is not None else get_drilldown_config()
    end = datetime.now(timezone.utc)
    start = end - _parse_duration(analysis_window)
    planned_items = [item for item in preview.items if item.planned]
    skipped_items = [item for item in preview.items if not item.planned]
    budget_limited_jobs = preview.budget_limited_jobs
    budget_excluded_metrics = preview.budget_excluded_metrics or sorted(
        list({item.metric_name for item in skipped_items if item.exclusion_reason == "budget_limit"})
    )
    budget_excluded_metrics_count = preview.budget_excluded_metrics_count or len(budget_excluded_metrics)
    warnings = list(preview.warnings)
    run_repo = AutonomousPolicyRunRepository(db)
    job_repo = AutonomousJobRepository(db)
    policy_snapshot = _policy_snapshot(
        preview,
        analysis_window=analysis_window,
        step=step,
        dry_run=dry_run,
        budget_excluded_metrics=budget_excluded_metrics,
    )
    policy_run = run_repo.create_run(
        policy_id=policy_id,
        trigger=trigger or ("test" if dry_run else "run_once"),
        policy_snapshot=policy_snapshot,
        metrics_discovered=preview.metrics_discovered,
        metrics_selected=preview.metrics_selected,
        jobs_planned=len(planned_items),
    )
    run_repo.mark_running(policy_run.id)
    jobs_by_metric = _create_jobs(
        job_repo,
        policy_run_id=policy_run.id,
        items=preview.items,
        datasource=policy_snapshot["datasource"],
        analysis_window=analysis_window,
    )

    if not planned_items:
        warnings.append("No planned autonomous jobs were available to execute.")

    if dry_run:
        results = []
        for item in planned_items:
            job = jobs_by_metric[id(item)]
            job_repo.mark_skipped(job.id, reason_code="dry_run", reason_detail="Dry run only; no analysis was executed.")
            results.append(
                AutonomousJobRunResult(
                    job_id=job.id,
                    metric_name=item.metric_name,
                    service=item.service,
                    namespace=item.namespace,
                    category=item.category,
                    concept=item.concept,
                    promql=item.promql,
                    status="skipped",
                    skip_reason_code="dry_run",
                    skip_reason="Dry run only; no analysis was executed.",
                    warnings=["Dry run only; no analysis was executed."],
                )
            )
        for item in skipped_items:
            job = jobs_by_metric[id(item)]
            code = _skip_reason_code(item)
            job_repo.mark_skipped(job.id, reason_code=code, reason_detail=item.exclusion_reason)
        run_repo.mark_completed(
            policy_run.id,
            status="completed",
            jobs_completed=0,
            jobs_skipped=len(planned_items),
            jobs_failed=0,
            findings_created=0,
        )
        return AutonomousRunResponse(
            policy_run_id=policy_run.id,
            status="dry_run",
            planned_jobs=len(planned_items),
            executed_jobs=0,
            skipped_jobs=len(planned_items),
            excluded_jobs=len(skipped_items),
            failed_jobs=0,
            budget_limited_jobs=budget_limited_jobs,
            budget_excluded_metrics_count=budget_excluded_metrics_count,
            budget_excluded_metrics=budget_excluded_metrics,
            summary=_summary(
                preview,
                len(planned_items),
                0,
                len(planned_items),
                0,
                0,
                policy_run.started_at,
                utc_now(),
                excluded_jobs=len(skipped_items),
                budget_limited_jobs=budget_limited_jobs,
                budget_excluded_metrics=budget_excluded_metrics,
            ),
            analysis_window=analysis_window,
            requested_start=start,
            requested_end=end,
            step=step,
            preview=preview,
            warnings=warnings,
            results=results,
        )

    for item in skipped_items:
        job = jobs_by_metric[id(item)]
        code = _skip_reason_code(item)
        job_repo.mark_skipped(job.id, reason_code=code, reason_detail=item.exclusion_reason)

    # Note on max_parallel_jobs: Execution currently runs sequentially to guarantee
    # transactional safety and deterministic order across SQLite and PostgreSQL sessions.
    # The max_parallel_jobs configuration is reserved for future distributed worker pools.
    results = [
        _execute_plan_item(
            item=item,
            job=jobs_by_metric[id(item)],
            job_repo=job_repo,
            prometheus=prometheus,
            db=db,
            config=config,
            start=start,
            end=end,
            step=step,
            drilldown=drilldown,
        )
        for item in planned_items
    ]
    executed = sum(1 for result in results if result.status == "completed")
    failed = sum(1 for result in results if result.status == "failed")
    # Metrics screened out before planning (budget, filters) are counted apart from planned jobs that
    # were skipped, so planned = executed + skipped + failed. Mixed together, a run read "planned 4,
    # executed 4, skipped 3".
    skipped = sum(1 for result in results if result.status == "skipped")
    excluded = len(skipped_items)
    status = "completed" if executed and not failed else "partial" if executed else "failed"
    # Each metric ran on its own, so rules over several metrics of a service are checked here.
    patterns_across_metrics = evaluate_runs_together(
        db, [result.analysis_run_id for result in results if result.status == "completed" and result.analysis_run_id]
    )
    findings_created = sum(result.findings_count + result.behavior_findings_count for result in results) + patterns_across_metrics
    error_summary = "; ".join(result.error for result in results if result.error) or None
    completed_run = run_repo.mark_completed(
        policy_run.id,
        status=status,
        jobs_completed=executed,
        jobs_skipped=skipped,
        jobs_failed=failed,
        findings_created=findings_created,
        error_summary=error_summary,
    )
    return AutonomousRunResponse(
        policy_run_id=policy_run.id,
        status=status,
        planned_jobs=len(planned_items),
        executed_jobs=executed,
        skipped_jobs=skipped,
        excluded_jobs=excluded,
        failed_jobs=failed,
        budget_limited_jobs=budget_limited_jobs,
        budget_excluded_metrics_count=budget_excluded_metrics_count,
        budget_excluded_metrics=budget_excluded_metrics,
        summary=_summary(
            preview,
            len(planned_items),
            executed,
            skipped,
            failed,
            findings_created,
            completed_run.started_at,
            completed_run.completed_at,
            excluded_jobs=excluded,
            budget_limited_jobs=budget_limited_jobs,
            budget_excluded_metrics=budget_excluded_metrics,
        ),
        analysis_window=analysis_window,
        requested_start=start,
        requested_end=end,
        step=step,
        preview=preview,
        results=results,
        warnings=warnings,
    )


def _execute_plan_item(
    *,
    item: MetricPlanItem,
    job: AutonomousMetricJobEntity,
    job_repo: AutonomousJobRepository,
    prometheus: PrometheusQueryService,
    db: Session,
    config: PrometheusConnectionConfig,
    start: datetime,
    end: datetime,
    step: str,
    drilldown: DrillDownConfig | None = None,
) -> AutonomousJobRunResult:
    if not item.promql:
        return _failed(item, "Planned job did not include PromQL.", job=job, job_repo=job_repo, error_type="invalid_query_plan")
    started = perf_counter()
    job_repo.mark_running(job.id)
    try:
        preview = prometheus.preview(item.promql, start, end, step)
        if preview.sample_count == 0:
            return _failed(item, "Prometheus returned no samples for the planned query.", warnings=preview.warnings, job=job, job_repo=job_repo, error_type="query_returned_empty", started=started)
        if preview.series_count != 1:
            return _failed(item, f"Planned query returned {preview.series_count} series; expected exactly one.", warnings=preview.warnings, job=job, job_repo=job_repo, error_type="invalid_query_plan", started=started)

        series = preview.series[0]
        labels = series.labels
        service = labels.get("service") or labels.get("service_name") or labels.get("job") or labels.get("app") or item.service or "unknown"
        records = [
            {
                "timestamp": sample.timestamp,
                "metric_name": labels.get("__name__") or item.metric_name,
                "value": sample.value,
                "service": service,
                "source": "prometheus",
                "host": labels.get("instance"),
                "namespace": labels.get("namespace") or item.namespace,
                "pod": labels.get("pod"),
                "env": labels.get("env") or labels.get("environment") or item.environment,
                "cluster": (labels.get(config.cluster_label) if config.cluster_label else None) or item.cluster,
                "series_id": ",".join(f"{key}={value}" for key, value in sorted(labels.items())),
                **{f"label_{key}": value for key, value in labels.items()},
            }
            for sample in series.samples
        ]

        pipeline_config = build_csv_routing_config(
            provider="prometheus",
            service=service,
            metric_name=item.metric_name,
            interval=f"{max(int(preview.step_seconds / 60), 1)}m" if preview.step_seconds >= 60 else f"{preview.step_seconds}s",
            analyzer_id="all",
            preview=False,
        )
        pipeline_config.input.source_type = "prometheus"
        pipeline_config.input.required_columns = ["timestamp", "metric_name", "value"]
        pipeline_config.input.provider_mappings = {}

        result = MetricAnalysisExecutor(pipeline_config).execute_dataframe(
            pd.DataFrame.from_records(records),
            run_metadata={
                "trigger": "autonomous_run_once",
                "datasource_uid": config.id,
                "connection_id": config.id,
                "datasource_name": configured_connection(config).name,
                "promql": item.promql,
                "from": preview.start.isoformat(),
                "to": preview.end.isoformat(),
                "step_seconds": preview.step_seconds,
                "series_count": preview.series_count,
                "sample_count": preview.sample_count,
                "category": item.category.value if item.category else None,
                "concept": item.concept.value if item.concept else None,
                "selection_reason": item.selection_reason,
            },
            db=db,
            series_key=series_key(config.id, item.promql),
        )
        if drilldown is not None and drilldown.enabled:
            drill_down_findings(db=db, prometheus=prometheus, promql=item.promql, step=step, result=result, config=drilldown)
        duration_ms = _duration_ms(started)
        job_repo.mark_completed(job.id, analysis_run_id=result.analysis_run_id, duration_ms=duration_ms)
        return AutonomousJobRunResult(
            job_id=job.id,
            metric_name=item.metric_name,
            service=service,
            namespace=item.namespace,
            category=item.category,
            concept=item.concept,
            promql=item.promql,
            status="completed",
            analysis_run_id=result.analysis_run_id,
            duration_ms=duration_ms,
            sample_count=preview.sample_count,
            series_count=preview.series_count,
            signal_count=result.signal_count,
            findings_count=result.findings_count,
            behavior_findings_count=result.behavior_findings_count,
            warnings=preview.warnings,
        )
    except HTTPException as exc:
        return _failed(item, str(exc.detail), job=job, job_repo=job_repo, error_type=type(exc).__name__, started=started)
    except ValueError as exc:
        return _failed(item, str(exc), job=job, job_repo=job_repo, error_type=type(exc).__name__, started=started)
    except Exception as exc:  # pragma: no cover
        return _failed(item, f"analysis failed: {exc}", job=job, job_repo=job_repo, error_type=type(exc).__name__, started=started)


def _failed(
    item: MetricPlanItem,
    error: str,
    warnings: list[str] | None = None,
    *,
    job: AutonomousMetricJobEntity | None = None,
    job_repo: AutonomousJobRepository | None = None,
    error_type: str = "analysis_failed",
    started: float | None = None,
) -> AutonomousJobRunResult:
    duration_ms = _duration_ms(started) if started is not None else None
    if job is not None and job_repo is not None:
        job_repo.mark_failed(job.id, error_type=error_type, error_message=error, duration_ms=duration_ms, error_code=error_type)
    return AutonomousJobRunResult(
        job_id=job.id if job is not None else None,
        metric_name=item.metric_name,
        service=item.service,
        namespace=item.namespace,
        category=item.category,
        concept=item.concept,
        promql=item.promql,
        status="failed",
        duration_ms=duration_ms,
        error=error,
        warnings=warnings or [],
    )


def _create_jobs(
    job_repo: AutonomousJobRepository,
    *,
    policy_run_id: str,
    items: list[MetricPlanItem],
    datasource: str,
    analysis_window: str,
) -> dict[int, AutonomousMetricJobEntity]:
    now = utc_now()
    jobs = [
        AutonomousMetricJobEntity(
            id=uuid4().hex,
            policy_run_id=policy_run_id,
            status="planned" if item.planned else "screened_out",
            datasource=datasource,
            environment=item.environment,
            namespace=item.namespace,
            service=item.service,
            metric_name=item.metric_name,
            logical_metric_name=item.metric_name,
            category=item.category.value if item.category else None,
            concept=item.concept.value if item.concept else None,
            promql=item.promql,
            analysis_window=analysis_window,
            aggregation_strategy=item.aggregation_strategy or item.aggregation,
            transformation=item.transformation,
            classification_confidence=item.confidence,
            selection_reason=item.selection_reason,
            skip_reason_code=_skip_reason_code(item) if not item.planned else None,
            skip_reason_detail=item.exclusion_reason if not item.planned else None,
            created_at=now,
            updated_at=now,
        )
        for item in items
    ]
    persisted = job_repo.create_jobs(jobs)
    return {id(item): job for item, job in zip(items, persisted, strict=True)}


def _policy_snapshot(
    preview: AutonomousPreviewResponse,
    *,
    analysis_window: str,
    step: str,
    dry_run: bool,
    budget_excluded_metrics: list[str] | None = None,
) -> dict:
    excluded = budget_excluded_metrics if budget_excluded_metrics is not None else preview.budget_excluded_metrics
    return {
        "datasource": "prometheus",
        "backend": "grafana-stack",
        "scope_summary": preview.scope_summary,
        "monitoring_summary": preview.monitoring_summary,
        "execution_policy": {"analysis_window": analysis_window, "interval": step, "dry_run": dry_run},
        "metrics_discovered": preview.metrics_discovered,
        "metrics_selected": preview.metrics_selected,
        "planned_jobs": preview.planned_jobs,
        "budget_limited_jobs": preview.budget_limited_jobs,
        "budget_excluded_metrics_count": preview.budget_excluded_metrics_count or len(excluded),
        "budget_excluded_metrics": excluded[:50],
        "warnings": preview.warnings,
    }


def _skip_reason_code(item: MetricPlanItem) -> str:
    reason = (item.exclusion_reason or "").lower()
    if reason == "duplicate_lower_rank":
        return "higher_ranked_metric_selected"
    if "budget" in reason:
        return "budget_limit"
    if "label" in reason:
        return "missing_required_label"
    if "unsupported" in reason or "metadata" in reason or "timestamp" in reason:
        return "unsupported_metric_type"
    if not item.category:
        return "category_not_selected"
    return "screened_unchanged" if reason == "screened_unchanged" else "category_not_selected"


def _duration_ms(started: float) -> int:
    return max(int((perf_counter() - started) * 1000), 0)


def _summary(
    preview: AutonomousPreviewResponse,
    planned: int,
    completed: int,
    skipped: int,
    failed: int,
    findings: int,
    started_at: datetime | None,
    completed_at: datetime | None,
    excluded_jobs: int = 0,
    budget_limited_jobs: int = 0,
    budget_excluded_metrics: list[str] | None = None,
) -> dict:
    duration_ms = None
    if started_at and completed_at:
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        if completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=timezone.utc)
        duration_ms = max(int((completed_at - started_at).total_seconds() * 1000), 0)
    excluded = budget_excluded_metrics if budget_excluded_metrics is not None else preview.budget_excluded_metrics
    return {
        "metrics_discovered": preview.metrics_discovered,
        "metrics_selected": preview.metrics_selected,
        "jobs_planned": planned,
        "jobs_completed": completed,
        "jobs_skipped": skipped,
        "jobs_excluded": excluded_jobs,
        "jobs_failed": failed,
        "budget_limited_jobs": budget_limited_jobs,
        "budget_excluded_metrics_count": len(excluded),
        "budget_excluded_metrics": excluded[:50],
        "findings_created": findings,
        "duration_ms": duration_ms,
    }


def _parse_duration(value: str) -> timedelta:
    raw = value.strip().lower()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([smhd])", raw)
    if not match:
        raise ValueError("analysis_window must be a duration like 6h, 24h, or 7d")
    number = float(match.group(1))
    unit = match.group(2)
    if unit == "s":
        return timedelta(seconds=number)
    if unit == "m":
        return timedelta(minutes=number)
    if unit == "h":
        return timedelta(hours=number)
    return timedelta(days=number)
