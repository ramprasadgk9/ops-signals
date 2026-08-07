from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pandas as pd
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.autonomous.schemas import AutonomousJobRunResult, AutonomousPreviewResponse, AutonomousRunResponse, MetricPlanItem
from backend.app.config import PrometheusConnectionConfig
from backend.app.models.entities import BehaviorFindingEntity, FindingEntity, SignalEntity
from backend.app.services.prometheus_service import PrometheusQueryService, configured_connection
from backend.app.services.timeseries_routing_service import build_csv_routing_config
from intelligence.pipeline import SignalPipeline


def execute_autonomous_plan_once(
    *,
    preview: AutonomousPreviewResponse,
    prometheus: PrometheusQueryService,
    db: Session,
    config: PrometheusConnectionConfig,
    analysis_window: str,
    step: str,
    dry_run: bool = False,
) -> AutonomousRunResponse:
    end = datetime.now(timezone.utc)
    start = end - _parse_duration(analysis_window)
    planned_items = [item for item in preview.items if item.planned]
    warnings = list(preview.warnings)

    if not planned_items:
        warnings.append("No planned autonomous jobs were available to execute.")

    if dry_run:
        return AutonomousRunResponse(
            status="dry_run",
            planned_jobs=len(planned_items),
            executed_jobs=0,
            skipped_jobs=len(planned_items),
            failed_jobs=0,
            analysis_window=analysis_window,
            requested_start=start,
            requested_end=end,
            step=step,
            preview=preview,
            warnings=warnings,
            results=[
                AutonomousJobRunResult(
                    metric_name=item.metric_name,
                    service=item.service,
                    category=item.category,
                    concept=item.concept,
                    promql=item.promql,
                    status="skipped",
                    warnings=["Dry run only; no analysis was executed."],
                )
                for item in planned_items
            ],
        )

    results = [
        _execute_plan_item(
            item=item,
            prometheus=prometheus,
            db=db,
            config=config,
            start=start,
            end=end,
            step=step,
        )
        for item in planned_items
    ]
    executed = sum(1 for result in results if result.status == "completed")
    failed = sum(1 for result in results if result.status == "failed")
    skipped = sum(1 for result in results if result.status == "skipped")
    status = "completed" if executed and not failed else "partial" if executed else "failed"
    return AutonomousRunResponse(
        status=status,
        planned_jobs=len(planned_items),
        executed_jobs=executed,
        skipped_jobs=skipped,
        failed_jobs=failed,
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
    prometheus: PrometheusQueryService,
    db: Session,
    config: PrometheusConnectionConfig,
    start: datetime,
    end: datetime,
    step: str,
) -> AutonomousJobRunResult:
    if not item.promql:
        return _failed(item, "Planned job did not include PromQL.")
    try:
        preview = prometheus.preview(item.promql, start, end, step)
        if preview.sample_count == 0:
            return _failed(item, "Prometheus returned no samples for the planned query.", warnings=preview.warnings)
        if preview.series_count != 1:
            return _failed(item, f"Planned query returned {preview.series_count} series; expected exactly one.", warnings=preview.warnings)

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

        result = SignalPipeline(pipeline_config).run_dataframe(
            pd.DataFrame.from_records(records),
            run_metadata={
                "trigger": "autonomous_run_once",
                "datasource_uid": "default",
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
        )
        findings_count = db.execute(select(func.count(FindingEntity.id)).where(FindingEntity.analysis_run_id == result.analysis_run_id)).scalar() or 0
        signal_count = db.execute(select(func.count(SignalEntity.id)).where(SignalEntity.analysis_run_id == result.analysis_run_id)).scalar() or 0
        behavior_count = db.execute(select(func.count(BehaviorFindingEntity.id)).where(BehaviorFindingEntity.analysis_run_id == result.analysis_run_id)).scalar() or 0
        return AutonomousJobRunResult(
            metric_name=item.metric_name,
            service=service,
            category=item.category,
            concept=item.concept,
            promql=item.promql,
            status="completed",
            analysis_run_id=result.analysis_run_id,
            sample_count=preview.sample_count,
            series_count=preview.series_count,
            signal_count=int(signal_count),
            findings_count=int(findings_count),
            behavior_findings_count=int(behavior_count),
            warnings=preview.warnings,
        )
    except HTTPException as exc:
        return _failed(item, str(exc.detail))
    except ValueError as exc:
        return _failed(item, str(exc))
    except Exception as exc:  # pragma: no cover
        return _failed(item, f"analysis failed: {exc}")


def _failed(item: MetricPlanItem, error: str, warnings: list[str] | None = None) -> AutonomousJobRunResult:
    return AutonomousJobRunResult(
        metric_name=item.metric_name,
        service=item.service,
        category=item.category,
        concept=item.concept,
        promql=item.promql,
        status="failed",
        error=error,
        warnings=warnings or [],
    )


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
