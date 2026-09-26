"""AlertEnrichmentService: alert in -> one enriched Slack message out (docs/design/alert-enrichment-plan.md §E).

Never blocks, drops, or fails an alert: every step degrades to "unavailable" and the message is
still built and (if notification is on) posted with whatever sections succeeded.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.alerts.classifier import REASON_TEXT, AnalysisDecision, classify
from backend.app.alerts.correlation import ChangeCorrelation, as_utc, correlate_changes
from backend.app.alerts.query_builder import QueryWindow, query_window
from backend.app.alerts.schemas import AlertReceiptOut, NormalizedAlert
from backend.app.config import AlertEnrichmentConfig, PrometheusConnectionConfig
from backend.app.memory.alert_context import build_alert_context
from backend.app.memory.schemas import AlertContextResponse
from backend.app.models.entities import AlertEnrichmentEntity, FindingEntity, SignalEntity
from backend.app.models.prometheus import PrometheusSeriesOut
from backend.app.notifications.message_builder import build_alert_enrichment_blocks, build_alert_resolved_blocks
from backend.app.notifications.slack_client import post_to_slack_webhook
from backend.app.services.prometheus_service import (
    PrometheusQueryService,
    _observed_interval,
    _prometheus_series_to_normalized,
)
from backend.app.services.timeseries_routing_service import build_csv_routing_config
from intelligence.config import AnalyzerConfig
from intelligence.storage.postgres_store import suppress_findings_hook

logger = logging.getLogger(__name__)

# Analyzers whose evidence carries `change_point_time`, most specific first.
_CHANGE_POINT_ANALYZERS = ("baseline_shift", "ruptures")


class PipelineRunner(Protocol):
    def __call__(self, normalized: Any, app_config: Any, run_metadata: dict[str, object]) -> Any: ...


def _run_signal_pipeline(normalized: Any, app_config: Any, run_metadata: dict[str, object]) -> Any:
    from intelligence.pipeline import SignalPipeline

    return SignalPipeline(app_config).run_normalized(normalized, run_metadata=run_metadata)


def _default_context_builder(db: Session, metric_key: str, service: str | None, message: str) -> AlertContextResponse:
    # Same collaborators GET /api/alert-context gets injected, read from the containers main.py
    # populates at startup (None when memory/AI are disabled - build_alert_context handles that).
    from backend.app.api import assistant as assistant_module
    from backend.app.api import memory as memory_module

    return build_alert_context(
        db,
        metric_name=metric_key,
        service=service,
        message=message,
        similarity=memory_module._services.get("similarity_service"),
        embedder=memory_module._services.get("embedder"),
        assistant=assistant_module._services.get("assistant"),
    )


@dataclass
class _FetchedSeries:
    series: PrometheusSeriesOut
    window: QueryWindow
    post_change_points: int


class _AnalysisSkipped(Exception):
    def __init__(self, reason: str, detail: str | None = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class AlertEnrichmentService:
    def __init__(
        self,
        config: AlertEnrichmentConfig,
        prometheus_config: PrometheusConnectionConfig,
        session_factory: Callable[[], Session],
        *,
        query_service: PrometheusQueryService | None = None,
        pipeline_runner: PipelineRunner | None = None,
        poster: Callable[[dict], None] | None = None,
        context_builder: Callable[[Session, str, str | None, str], AlertContextResponse] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.prometheus_config = prometheus_config
        self.session_factory = session_factory
        self.query_service = query_service or PrometheusQueryService(prometheus_config)
        self.pipeline_runner = pipeline_runner or _run_signal_pipeline
        self.poster = poster or self._post_to_slack
        self.context_builder = context_builder or _default_context_builder
        self.sleep = sleep
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._analysis_slots = threading.BoundedSemaphore(max(1, config.max_concurrent_analyses))

    # --- receipt (synchronous, inside the request) -------------------------------------------

    def receive(self, alerts: list[NormalizedAlert]) -> tuple[AlertReceiptOut, list[tuple[str, int]]]:
        """Dedupe and record alerts. Returns the receipt plus the (kind, enrichment_id) work items
        to process in the background."""
        receipt = AlertReceiptOut(accepted=0)
        work: list[tuple[str, int]] = []
        with self.session_factory() as db:
            for alert in alerts:
                open_row = self._open_occurrence(db, alert.fingerprint)
                if alert.status == "firing":
                    if open_row is not None:
                        receipt.duplicates += 1
                        continue
                    row = self._new_row(alert)
                    db.add(row)
                    db.flush()
                    receipt.accepted += 1
                    receipt.enrichment_ids.append(row.id)
                    work.append(("firing", row.id))
                else:
                    if open_row is None:
                        receipt.duplicates += 1
                        continue
                    open_row.status = "resolved"
                    open_row.ends_at = alert.ends_at or self.clock()
                    receipt.resolved += 1
                    receipt.enrichment_ids.append(open_row.id)
                    work.append(("resolved", open_row.id))
            db.commit()
        return receipt, work

    def process(self, kind: str, enrichment_id: int) -> None:
        try:
            if kind == "firing":
                self.process_firing(enrichment_id)
            else:
                self.process_resolved(enrichment_id)
        except Exception:  # pragma: no cover - last-resort guard for a background task
            logger.exception("Alert enrichment %s for #%s failed unexpectedly", kind, enrichment_id)

    def _open_occurrence(self, db: Session, fingerprint: str) -> AlertEnrichmentEntity | None:
        cutoff = self.clock() - timedelta(seconds=self.config.dedupe_window_seconds)
        return db.execute(
            select(AlertEnrichmentEntity)
            .where(
                AlertEnrichmentEntity.fingerprint == fingerprint,
                AlertEnrichmentEntity.status == "firing",
                AlertEnrichmentEntity.created_at >= cutoff,
            )
            .order_by(AlertEnrichmentEntity.created_at.desc())
            .limit(1)
        ).scalars().first()

    def _new_row(self, alert: NormalizedAlert) -> AlertEnrichmentEntity:
        return AlertEnrichmentEntity(
            fingerprint=alert.fingerprint,
            source=alert.source,
            alert_name=alert.alert_name,
            service=alert.service,
            severity=alert.severity,
            status="firing",
            starts_at=alert.starts_at,
            labels_json=alert.labels,
            annotations_json=alert.annotations,
            generator_url=alert.generator_url,
            external_url=alert.external_url,
            promql=alert.expr,
            created_at=self.clock(),
        )

    # --- firing ---------------------------------------------------------------------------------

    def process_firing(self, enrichment_id: int) -> None:
        with self.session_factory() as db:
            row = db.get(AlertEnrichmentEntity, enrichment_id)
            if row is None:
                return
            alert = _alert_from_row(row)
            enrichment: dict[str, Any] = {"source": alert.source}
            try:
                decision = classify(alert, prometheus_configured=bool(self.prometheus_config.base_url))
                metric_key = decision.metric_key or alert.alert_name
                row.metric_key = metric_key
                row.promql = decision.query or alert.expr

                # History first: our own analysis below writes a finding for this service+metric,
                # which would otherwise show up in the lookup as "seen before".
                context, context_error = self._context(db, metric_key, alert)
                analysis = self._analysis(db, alert, decision, metric_key)
                anchor = _parse_iso(analysis.get("change_point_time")) or alert.starts_at
                changes = self._changes(db, alert.service, anchor)

                enrichment.update(
                    alert=_alert_dict(alert, metric_key),
                    analysis=analysis,
                    changes=_changes_dict(changes),
                    context=context.model_dump(mode="json") if context else None,
                    context_error=context_error,
                )
                row.analysis_status = analysis["status"] if analysis["status"] not in {"skipped", "failed"} else (
                    f"{analysis['status']}:{analysis.get('reason')}"
                )
                row.analysis_run_id = analysis.get("analysis_run_id")
                row.finding_id = (analysis.get("finding") or {}).get("id")
                row.change_event_ids = [match.id for match in changes.matches] if changes else []
                row.recommendation = context.recommendation if context else None
                message = build_alert_enrichment_blocks(enrichment, self.config.ui_base_url)
            except Exception as exc:
                logger.exception("Alert enrichment #%s failed; posting a minimal message", enrichment_id)
                row.error = f"enrichment failed: {exc}"
                enrichment.setdefault("alert", _alert_dict(alert, row.metric_key))
                enrichment["analysis"] = {"status": "failed", "reason": "analysis_failed", "reason_text": "enrichment failed"}
                message = build_alert_enrichment_blocks(enrichment, self.config.ui_base_url)

            row.enrichment_json = enrichment
            row.message_json = message
            suppressed = self._suppression_reason(alert)
            if suppressed:
                row.notify_status = f"suppressed:{suppressed}"
            else:
                try:
                    self.poster(message)
                    row.notify_status = "posted"
                    row.slack_posted_at = self.clock()
                except Exception as exc:
                    logger.warning("Slack post for alert enrichment #%s failed: %s", enrichment_id, exc)
                    row.notify_status = "failed"
                    row.error = f"slack: {exc}"
            db.commit()

    def _context(self, db: Session, metric_key: str, alert: NormalizedAlert) -> tuple[AlertContextResponse | None, str | None]:
        try:
            return self.context_builder(db, metric_key, alert.service, alert.summary), None
        except Exception as exc:
            logger.warning("Alert-context lookup failed for %s/%s: %s", alert.service, metric_key, exc)
            db.rollback()
            return None, str(exc)

    def _changes(self, db: Session, service: str | None, anchor: datetime) -> ChangeCorrelation | None:
        try:
            return correlate_changes(
                db,
                service,
                anchor,
                before=timedelta(seconds=self.config.correlation_before_seconds),
                after=timedelta(seconds=self.config.correlation_after_seconds),
            )
        except Exception as exc:
            logger.warning("Change correlation failed for %s: %s", service, exc)
            db.rollback()
            return None

    # --- analysis -------------------------------------------------------------------------------

    def _analysis(self, db: Session, alert: NormalizedAlert, decision: AnalysisDecision, metric_key: str) -> dict[str, Any]:
        base: dict[str, Any] = {"lookback_seconds": self._lookback_seconds(alert)}
        if not decision.analyze:
            return {**base, **_skipped(decision.reason or "no_query")}

        reused = self._recent_finding(db, alert, metric_key)
        if reused is not None:
            return {**base, **reused}

        with self._analysis_slots:
            try:
                fetched = self._fetch_series(alert, decision.query or "")
            except _AnalysisSkipped as skipped:
                return {**base, **_skipped(skipped.reason, skipped.detail)}
            try:
                return {**base, **self._run_pipeline(alert, decision, metric_key, fetched)}
            except Exception as exc:
                logger.warning("Analysis pipeline failed for alert %s: %s", alert.alert_name, exc)
                return {**base, **_skipped("analysis_failed", str(exc), status="failed")}

    def _lookback_seconds(self, alert: NormalizedAlert) -> int:
        window = query_window(self.config, alert.annotations, self.clock())
        return int((window.end - window.start).total_seconds())

    def _recent_finding(self, db: Session, alert: NormalizedAlert, metric_key: str) -> dict[str, Any] | None:
        """Reuse a finding autonomous analysis already produced for this series, instead of
        re-running the analyzers - and say how much earlier it was detected."""
        if not alert.service:
            return None
        cutoff = self.clock() - timedelta(seconds=self.config.reuse_window_seconds)
        finding = db.execute(
            select(FindingEntity)
            .where(
                FindingEntity.service == alert.service,
                FindingEntity.metric_name == metric_key,
                FindingEntity.health_status != "normal",
                FindingEntity.created_at >= cutoff,
            )
            .order_by(FindingEntity.importance_score.desc(), FindingEntity.created_at.desc())
            .limit(1)
        ).scalars().first()
        if finding is None:
            return None
        change_point = None
        if finding.analysis_run_id:
            signals = db.execute(
                select(SignalEntity).where(
                    SignalEntity.analysis_run_id == finding.analysis_run_id,
                    SignalEntity.analyzer_id.in_(_CHANGE_POINT_ANALYZERS),
                )
            ).scalars().all()
            change_point = _change_point_from_evidence([(s.analyzer_id, s.evidence_json or {}) for s in signals])
        # "Detected N min before the alert" means when Ops Signals produced the finding, not when
        # the change itself started (that's change_point_time, shown separately).
        detected_before = None
        if finding.created_at and as_utc(finding.created_at) < alert.starts_at:
            detected_before = (alert.starts_at - as_utc(finding.created_at)).total_seconds() / 60.0
        return {
            "status": "reused",
            "finding": _finding_dict(finding),
            "analysis_run_id": finding.analysis_run_id,
            "change_point_time": change_point,
            "detected_before_alert_minutes": detected_before,
        }

    def _fetch_series(self, alert: NormalizedAlert, query: str) -> _FetchedSeries:
        delays = [0, *self.config.retry_delays_seconds]
        fetched: _FetchedSeries | None = None
        for attempt, delay in enumerate(delays):
            if delay:
                self.sleep(delay)
            window = query_window(self.config, alert.annotations, self.clock())
            try:
                preview = self.query_service.preview(query, window.start, window.end, window.step)
            except HTTPException as exc:
                raise _AnalysisSkipped(_reason_for_http_error(exc), str(exc.detail)) from exc
            except Exception as exc:
                raise _AnalysisSkipped("prometheus_unreachable", str(exc)) from exc
            if preview.sample_count == 0 or not preview.series:
                raise _AnalysisSkipped("no_data")
            series = select_series(preview.series, alert.labels)
            if series is None:
                raise _AnalysisSkipped("ambiguous_series", f"{len(preview.series)} series returned")
            grace_start = alert.starts_at - timedelta(seconds=self.config.post_change_grace_seconds)
            post_change = sum(1 for sample in series.samples if as_utc(sample.timestamp) >= grace_start)
            fetched = _FetchedSeries(series=series, window=window, post_change_points=post_change)
            if post_change >= self.config.min_post_change_points or attempt == len(delays) - 1:
                break
        assert fetched is not None

        values = [sample.value for sample in fetched.series.samples]
        if len(values) < self.config.min_points:
            raise _AnalysisSkipped("insufficient_data", f"{len(values)} points")
        if len(set(values)) <= 2:
            raise _AnalysisSkipped("binary_series")
        return fetched

    def _run_pipeline(
        self,
        alert: NormalizedAlert,
        decision: AnalysisDecision,
        metric_key: str,
        fetched: _FetchedSeries,
    ) -> dict[str, Any]:
        samples = fetched.series.samples
        service = alert.service or "unknown-service"
        normalized = _prometheus_series_to_normalized(
            samples=samples, labels=fetched.series.labels, service=service, metric=metric_key
        )
        app_config = build_csv_routing_config(
            provider="prometheus",
            service=service,
            metric_name=metric_key,
            interval=_observed_interval(samples, fetched.window.step_seconds),
            analyzer_id="all",
            preview=False,
        )
        app_config.input.source_type = "prometheus"
        app_config.input.required_columns = ["timestamp", "metric_name", "value"]
        app_config.input.provider_mappings = {}
        for analyzer_id in self.config.excluded_analyzers:
            existing = app_config.analysis.analyzers.get(analyzer_id)
            if existing is not None:
                existing.enabled = False
            else:
                app_config.analysis.analyzers[analyzer_id] = AnalyzerConfig(enabled=False, params={})

        run_metadata: dict[str, object] = {
            "trigger": "alert",
            "alert_source": alert.source,
            "alert_name": alert.alert_name,
            "alert_fingerprint": alert.fingerprint,
            "datasource_uid": self.prometheus_config.id,
            "promql": decision.query,
            "from": fetched.window.start.isoformat(),
            "to": fetched.window.end.isoformat(),
            "step_seconds": fetched.window.step_seconds,
            "series_count": 1,
            "sample_count": len(samples),
        }
        with suppress_findings_hook():
            result = self.pipeline_runner(normalized, app_config, run_metadata)

        early = fetched.post_change_points < self.config.min_post_change_points
        change_point = _change_point_from_evidence(
            [(signal.analyzer_id, signal.evidence or {}) for signal in getattr(result, "signals", [])]
        )
        significant = [f for f in getattr(result, "findings", []) if f.health_status != "normal"]
        common = {
            "analysis_run_id": result.analysis_run_id,
            "points": len(samples),
            "post_change_points": fetched.post_change_points,
            "early": early,
            "step_seconds": fetched.window.step_seconds,
        }
        if not significant:
            return {"status": "no_significant_change", "finding": None, "change_point_time": None, **common}
        headline = max(significant, key=lambda f: f.importance_score)
        finding = _finding_dict(headline)
        finding["id"] = self._stored_finding_id(result.analysis_run_id, headline.title)
        return {"status": "analyzed", "finding": finding, "change_point_time": change_point, **common}

    def _stored_finding_id(self, analysis_run_id: str, title: str) -> int | None:
        try:
            with self.session_factory() as db:
                return db.execute(
                    select(FindingEntity.id)
                    .where(FindingEntity.analysis_run_id == analysis_run_id, FindingEntity.title == title)
                    .limit(1)
                ).scalar()
        except Exception:
            return None

    # --- resolved -------------------------------------------------------------------------------

    def process_resolved(self, enrichment_id: int) -> None:
        with self.session_factory() as db:
            row = db.get(AlertEnrichmentEntity, enrichment_id)
            if row is None or row.resolved_posted_at is not None:
                return
            alert = _alert_from_row(row)
            # Only follow up on a message people actually saw.
            if not self.config.notify_on_resolve or row.slack_posted_at is None or self._suppression_reason(alert):
                db.commit()
                return
            open_minutes = None
            if row.ends_at:
                open_minutes = (as_utc(row.ends_at) - as_utc(row.starts_at)).total_seconds() / 60.0
            enrichment = row.enrichment_json or {"source": row.source, "alert": _alert_dict(alert, row.metric_key)}
            try:
                self.poster(build_alert_resolved_blocks(enrichment, self.config.ui_base_url, open_minutes))
                row.resolved_posted_at = self.clock()
            except Exception as exc:
                logger.warning("Slack resolve post for alert enrichment #%s failed: %s", enrichment_id, exc)
                row.error = f"slack resolve: {exc}"
            db.commit()

    # --- notification ---------------------------------------------------------------------------

    def _suppression_reason(self, alert: NormalizedAlert) -> str | None:
        if self.config.notify == "none":
            return "notify_none"
        if (alert.annotations.get("ops_signals_notify") or "").strip().lower() == "false":
            return "annotation"
        if self.config.notify_severities and (alert.severity or "").lower() not in self.config.notify_severities:
            return "severity"
        if not self.config.slack_webhook_url:
            return "no_webhook"
        return None

    def _post_to_slack(self, payload: dict) -> None:
        assert self.config.slack_webhook_url
        post_to_slack_webhook(self.config.slack_webhook_url, payload, self.config.slack_timeout_seconds)


# --- helpers ------------------------------------------------------------------------------------


def select_series(series: list[PrometheusSeriesOut], alert_labels: dict[str, str]) -> PrometheusSeriesOut | None:
    """The firing series' labels are a subset of the alert's labels (the alert adds the rule's
    static labels on top), so match on that instead of rewriting the PromQL."""
    if len(series) == 1:
        return series[0]
    matches = [
        item
        for item in series
        if all(alert_labels.get(key) == value for key, value in item.labels.items() if key != "__name__")
    ]
    return matches[0] if len(matches) == 1 else None


def _reason_for_http_error(exc: HTTPException) -> str:
    detail = str(exc.detail or "").lower()
    if "not configured" in detail:
        return "no_prometheus"
    if "max_series" in detail:
        return "too_many_series"
    if exc.status_code in {503, 504}:
        return "prometheus_unreachable"
    return "query_failed"


def _skipped(reason: str, detail: str | None = None, status: str = "skipped") -> dict[str, Any]:
    if reason in {"prometheus_unreachable", "query_failed"}:
        status = "failed"
    return {
        "status": status,
        "reason": reason,
        "reason_text": REASON_TEXT.get(reason, reason),
        "detail": detail,
        "finding": None,
        "change_point_time": None,
    }


def _change_point_from_evidence(items: list[tuple[str | None, dict]]) -> str | None:
    for analyzer_id in _CHANGE_POINT_ANALYZERS:
        for item_analyzer, evidence in items:
            if item_analyzer == analyzer_id and evidence.get("change_point_time"):
                return str(evidence["change_point_time"])
    return None


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _finding_dict(finding: Any) -> dict[str, Any]:
    return {
        "id": getattr(finding, "id", None),
        "title": finding.title,
        "summary": finding.summary,
        "category": finding.category,
        "health_status": finding.health_status,
        "importance_score": round(float(finding.importance_score or 0.0), 4),
    }


def _alert_dict(alert: NormalizedAlert, metric_key: str | None) -> dict[str, Any]:
    return {
        "name": alert.alert_name,
        "status": alert.status,
        "service": alert.service,
        "severity": alert.severity,
        "summary": alert.summary,
        "starts_at": alert.starts_at.isoformat(),
        "fingerprint": alert.fingerprint,
        "generator_url": alert.generator_url,
        "external_url": alert.external_url,
        "metric_key": metric_key,
    }


def _changes_dict(changes: ChangeCorrelation | None) -> dict[str, Any] | None:
    if changes is None:
        return None
    return {
        "anchor": changes.anchor.isoformat(),
        "window_before_minutes": changes.window_before_minutes,
        "window_after_minutes": changes.window_after_minutes,
        "service_has_any_events": changes.service_has_any_events,
        "matches": [
            {
                "id": match.id,
                "event_type": match.event_type,
                "timestamp": match.timestamp.isoformat(),
                "version": match.version,
                "author": match.author,
                "url": match.url,
                "description": match.description,
                "minutes_before_anchor": round(match.minutes_before_anchor, 1),
            }
            for match in changes.matches
        ],
    }


def _alert_from_row(row: AlertEnrichmentEntity) -> NormalizedAlert:
    return NormalizedAlert(
        source=row.source,
        fingerprint=row.fingerprint,
        status=row.status,
        alert_name=row.alert_name,
        service=row.service,
        severity=row.severity,
        starts_at=as_utc(row.starts_at),
        ends_at=as_utc(row.ends_at) if row.ends_at else None,
        labels=dict(row.labels_json or {}),
        annotations=dict(row.annotations_json or {}),
        expr=row.promql,
        generator_url=row.generator_url,
        external_url=row.external_url,
    )
