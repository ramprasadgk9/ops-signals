"""End-to-end receiver tests: real receiver, dedupe, classifier, correlation, alert-context and
message builder; Prometheus, the analysis pipeline, and Slack are fakes (the pipeline needs real
Postgres, and nothing here should make a network call)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.alerts.enrichment import AlertEnrichmentService
from backend.app.api.alerts import get_alert_enrichment_service
from backend.app.config import AlertEnrichmentConfig, PrometheusConnectionConfig, get_alert_enrichment_config
from backend.app.models.db import get_session_local
from backend.app.models.entities import AlertEnrichmentEntity, FindingEntity, SignalEntity
from backend.app.models.prometheus import PrometheusPreviewOut, PrometheusSeriesOut, PrometheusSeriesSample
from intelligence.findings.schema import OperationalFinding
from intelligence.storage import postgres_store

NOW = datetime(2026, 9, 23, 14, 13, 30, tzinfo=timezone.utc)
STARTS_AT = datetime(2026, 9, 23, 14, 13, tzinfo=timezone.utc)
CHANGE_AT = datetime(2026, 9, 23, 14, 8, tzinfo=timezone.utc)
EXPR = 'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{service="checkout-api"}[5m]))) > 0.3'
METRIC_KEY = "http_request_duration_seconds_bucket"


class FakeQueryService:
    def __init__(self, series_end: datetime = NOW, error: Exception | None = None, series_count: int = 1):
        self.series_end = series_end
        self.error = error
        self.series_count = series_count
        self.calls: list[tuple[str, datetime, datetime, str]] = []

    def preview(self, query: str, start: datetime, end: datetime, step: str) -> PrometheusPreviewOut:
        self.calls.append((query, start, end, step))
        if self.error:
            raise self.error
        samples = []
        ts = start
        while ts <= min(end, self.series_end):
            samples.append(PrometheusSeriesSample(timestamp=ts, value=0.42 if ts >= CHANGE_AT else 0.18 + (ts.minute % 3) * 0.001))
            ts += timedelta(seconds=30)
        series = [
            PrometheusSeriesOut(labels={"pod": f"p{i}"} if self.series_count > 1 else {}, samples=samples)
            for i in range(self.series_count)
        ]
        return PrometheusPreviewOut(
            query=query, start=start, end=end, step=step, step_seconds=30,
            series_count=len(series), sample_count=len(samples) * len(series), series=series,
        )


class FakePipeline:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, normalized, app_config, run_metadata):
        self.calls.append(
            {
                "rows": len(normalized),
                "metric_name": normalized["metric_name"].iloc[0],
                "prophet_enabled": app_config.analysis.analyzers["prophet"].enabled,
                "hook_suppressed": postgres_store._findings_hook_suppressed.get(),
                "run_metadata": run_metadata,
            }
        )
        finding = OperationalFinding(
            service="checkout-api",
            metric_name=METRIC_KEY,
            title="Sustained latency baseline shift on checkout-api",
            summary="p95 moved from ~180ms to ~420ms.",
            category="baseline_shift",
            health_status="significant",
            importance_score=0.82,
            analysis_run_id="run-1",
        )
        with get_session_local()() as db:
            db.add(FindingEntity(**{k: v for k, v in finding.to_record().items() if k != "signal_ids"}, signal_ids=[]))
            db.commit()
        signal = SimpleNamespace(analyzer_id="baseline_shift", evidence={"change_point_time": CHANGE_AT.isoformat()})
        return SimpleNamespace(analysis_run_id="run-1", findings=[finding], signals=[signal])


@pytest.fixture()
def harness(client: TestClient):
    def build(query_service: FakeQueryService | None = None, **config_overrides):
        config = AlertEnrichmentConfig(
            **{
                "enabled": True,
                "slack_webhook_url": "http://slack.example/hook",
                "ui_base_url": "http://ops.local",
                **config_overrides,
            }
        )
        posted: list[dict] = []
        sleeps: list[float] = []
        pipeline = FakePipeline()
        queries = query_service or FakeQueryService()
        service = AlertEnrichmentService(
            config,
            PrometheusConnectionConfig(base_url="http://prometheus:9090"),
            session_factory=lambda: get_session_local()(),
            query_service=queries,
            pipeline_runner=pipeline,
            poster=posted.append,
            sleep=sleeps.append,
            clock=lambda: NOW,
        )
        client.app.dependency_overrides[get_alert_enrichment_config] = lambda: config
        client.app.dependency_overrides[get_alert_enrichment_service] = lambda: service
        return SimpleNamespace(client=client, posted=posted, pipeline=pipeline, queries=queries, sleeps=sleeps)

    yield build
    client.app.dependency_overrides.clear()


def _payload(status: str = "firing", expr: str = EXPR, fingerprint: str = "fp-1", **annotations: str) -> dict:
    return {
        "version": "4",
        "status": status,
        "receiver": "ops-signals",
        "externalURL": "http://alertmanager:9093",
        "alerts": [
            {
                "status": status,
                "labels": {"alertname": "CheckoutHighLatency", "service": "checkout-api", "severity": "warning"},
                "annotations": {"summary": "checkout-api p95 latency above 300ms", **annotations},
                "startsAt": STARTS_AT.isoformat(),
                "endsAt": (STARTS_AT + timedelta(minutes=22)).isoformat() if status == "resolved" else "0001-01-01T00:00:00Z",
                "generatorURL": f"http://prometheus:9090/graph?g0.expr={quote(expr)}&g0.tab=1",
                "fingerprint": fingerprint,
            }
        ],
    }


def _rows() -> list[AlertEnrichmentEntity]:
    with get_session_local()() as db:
        return db.execute(select(AlertEnrichmentEntity).order_by(AlertEnrichmentEntity.id)).scalars().all()


def _message_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def test_firing_alert_is_analyzed_correlated_and_posted_once(harness) -> None:
    h = harness()
    h.client.post(
        "/api/events",
        json={"service": "checkout-api", "type": "deploy", "version": "v2.3.1", "author": "alice",
              "timestamp": (CHANGE_AT - timedelta(minutes=6)).isoformat()},
    )

    response = h.client.post("/api/integrations/alertmanager", json=_payload())

    assert response.status_code == 202
    assert response.json()["accepted"] == 1
    assert len(h.posted) == 1
    text = _message_text(h.posted[0])
    assert "[FIRING] CheckoutHighLatency · checkout-api" in text
    assert "*Alertmanager alert*" in text
    assert "Sustained latency baseline shift" in text
    assert "around *14:08 UTC*" in text
    assert "Started *6 min after*" in text and "v2.3.1" in text
    assert "First time Ops Signals has seen this alert." in text  # context ran before our own finding existed

    [call] = h.pipeline.calls
    assert call["hook_suppressed"] is True
    assert call["prophet_enabled"] is False
    assert call["metric_name"] == METRIC_KEY
    assert call["run_metadata"]["trigger"] == "alert"
    query, start, end, step = h.queries.calls[0]
    assert query.endswith("[5m])))") and "> 0.3" not in query
    assert (end - start) == timedelta(hours=6) and step == "30s"

    [row] = _rows()
    assert row.analysis_status == "analyzed"
    assert row.notify_status == "posted"
    assert row.finding_id is not None
    assert len(row.change_event_ids) == 1
    assert row.enrichment_json["analysis"]["change_point_time"] == CHANGE_AT.isoformat()
    assert row.message_json == h.posted[0]


def test_repeat_notification_is_deduplicated_and_resolve_posts_follow_up(harness) -> None:
    h = harness()
    h.client.post("/api/integrations/alertmanager", json=_payload())
    repeat = h.client.post("/api/integrations/alertmanager", json=_payload())
    assert repeat.json()["duplicates"] == 1
    assert len(h.posted) == 1

    resolved = h.client.post("/api/integrations/alertmanager", json=_payload(status="resolved"))
    assert resolved.json()["resolved"] == 1
    assert len(h.posted) == 2
    assert "[RESOLVED] CheckoutHighLatency" in _message_text(h.posted[1])
    assert "resolved after 22 min" in _message_text(h.posted[1])

    # A new firing after resolve is a new occurrence.
    again = h.client.post("/api/integrations/alertmanager", json=_payload())
    assert again.json()["accepted"] == 1
    assert len(_rows()) == 2


def test_runbook_url_annotation_is_linked_in_the_slack_message(harness) -> None:
    h = harness()
    h.client.post(
        "/api/integrations/alertmanager",
        json=_payload(runbook_url="https://wiki.example.com/runbooks/checkout-latency"),
    )
    assert len(h.posted) == 1
    assert (
        "📘 *Runbook:* <https://wiki.example.com/runbooks/checkout-latency|Open the runbook>"
        in _message_text(h.posted[0])
    )


@pytest.mark.parametrize(
    ("overrides", "annotations", "expected"),
    [
        ({"notify": "none"}, {}, "suppressed:notify_none"),
        ({}, {"ops_signals_notify": "false"}, "suppressed:annotation"),
        ({"notify_severities": ["critical"]}, {}, "suppressed:severity"),
        ({"slack_webhook_url": None}, {}, "suppressed:no_webhook"),
    ],
)
def test_suppressed_notifications_are_still_enriched_and_stored(harness, overrides, annotations, expected) -> None:
    h = harness(**overrides)
    h.client.post("/api/integrations/alertmanager", json=_payload(**annotations))
    assert h.posted == []
    [row] = _rows()
    assert row.notify_status == expected
    assert row.analysis_status == "analyzed"
    assert row.message_json is not None

    # No resolve follow-up for a message nobody saw.
    h.client.post("/api/integrations/alertmanager", json=_payload(status="resolved"))
    assert h.posted == []


def test_disabled_feature_accepts_nothing(harness) -> None:
    h = harness()
    h.client.app.dependency_overrides[get_alert_enrichment_config] = lambda: AlertEnrichmentConfig(enabled=False)
    response = h.client.post("/api/integrations/alertmanager", json=_payload())
    assert response.status_code == 202
    assert response.json()["disabled"] is True
    assert _rows() == []


def test_receiver_token(harness) -> None:
    h = harness(receiver_token="s3cret")
    assert h.client.post("/api/integrations/alertmanager", json=_payload()).status_code == 401
    ok = h.client.post("/api/integrations/alertmanager", json=_payload(), headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 202


def test_status_alert_skips_analysis_but_still_posts_changes_and_history(harness) -> None:
    h = harness()
    h.client.post("/api/integrations/alertmanager", json=_payload(expr='up{job="checkout"} == 0'))
    assert h.pipeline.calls == [] and h.queries.calls == []
    text = _message_text(h.posted[0])
    assert "Not analyzed: status/health alert" in text
    assert "What changed" in text and "Seen before" in text
    assert _rows()[0].analysis_status == "skipped:status_alert"


def test_prometheus_outage_degrades_to_changes_and_history(harness) -> None:
    h = harness(FakeQueryService(error=HTTPException(status_code=503, detail="Prometheus connection failed")))
    h.client.post("/api/integrations/alertmanager", json=_payload())
    assert len(h.posted) == 1
    assert "Not analyzed: Prometheus could not be reached" in _message_text(h.posted[0])
    assert _rows()[0].analysis_status == "failed:prometheus_unreachable"


def test_ambiguous_multi_series_result_is_skipped(harness) -> None:
    h = harness(FakeQueryService(series_count=3))
    h.client.post("/api/integrations/alertmanager", json=_payload())
    assert _rows()[0].analysis_status == "skipped:ambiguous_series"
    assert h.pipeline.calls == []


def test_too_few_points_after_the_alert_retries_then_analyzes_as_early(harness) -> None:
    # Prometheus has nothing after 14:00, so "since the alert (-10m grace)" has no points.
    h = harness(FakeQueryService(series_end=datetime(2026, 9, 23, 14, 0, tzinfo=timezone.utc)))
    h.client.post("/api/integrations/alertmanager", json=_payload())
    assert h.sleeps == [180, 360]
    assert len(h.queries.calls) == 3
    row = _rows()[0]
    assert row.enrichment_json["analysis"]["early"] is True
    assert "Early analysis" in _message_text(h.posted[0])


def test_recent_autonomous_finding_is_reused_instead_of_rerunning(harness) -> None:
    h = harness()
    with get_session_local()() as db:
        db.add(FindingEntity(
            analysis_run_id="auto-1", service="checkout-api", metric_name=METRIC_KEY,
            title="Autonomous: latency shift", summary="found by the scheduler", category="baseline_shift",
            health_status="significant", importance_score=0.9, signal_ids=[], comparison_json={},
            created_at=STARTS_AT - timedelta(minutes=5),
        ))
        db.add(SignalEntity(
            signal_id="s-auto-1", signal_type="baseline_shift", analyzer_id="baseline_shift",
            metric_name=METRIC_KEY, service="checkout-api", analysis_run_id="auto-1",
            evidence_json={"change_point_time": CHANGE_AT.isoformat()},
        ))
        db.commit()

    h.client.post("/api/integrations/alertmanager", json=_payload())

    assert h.pipeline.calls == [] and h.queries.calls == []
    text = _message_text(h.posted[0])
    assert "Autonomous: latency shift" in text
    assert "detected this *5 min before* the alert fired" in text
    assert _rows()[0].analysis_status == "reused"


def test_finding_from_another_cluster_is_not_reused(harness) -> None:
    h = harness()
    with get_session_local()() as db:
        db.add(FindingEntity(
            analysis_run_id="auto-eu", service="checkout-api", metric_name=METRIC_KEY, cluster="eu",
            title="Autonomous: latency shift in eu", summary="found by the scheduler", category="baseline_shift",
            health_status="significant", importance_score=0.9, signal_ids=[], comparison_json={},
            created_at=STARTS_AT - timedelta(minutes=5),
        ))
        db.commit()
    payload = _payload()
    payload["alerts"][0]["labels"]["cluster"] = "us"

    h.client.post("/api/integrations/alertmanager", json=payload)

    assert len(h.pipeline.calls) == 1
    assert "Autonomous: latency shift in eu" not in _message_text(h.posted[0])


def test_finding_from_the_alerts_cluster_is_reused(harness) -> None:
    h = harness()
    with get_session_local()() as db:
        for cluster in ("eu", "us"):
            db.add(FindingEntity(
                analysis_run_id=f"auto-{cluster}", service="checkout-api", metric_name=METRIC_KEY, cluster=cluster,
                title=f"Autonomous: latency shift in {cluster}", summary="found by the scheduler", category="baseline_shift",
                health_status="significant", importance_score=0.95 if cluster == "eu" else 0.9, signal_ids=[], comparison_json={},
                created_at=STARTS_AT - timedelta(minutes=5),
            ))
        db.commit()
    payload = _payload()
    payload["alerts"][0]["labels"]["cluster"] = "us"

    h.client.post("/api/integrations/alertmanager", json=payload)

    assert h.pipeline.calls == []
    text = _message_text(h.posted[0])
    assert "Autonomous: latency shift in us" in text
    assert "latency shift in eu" not in text


def test_deploy_to_another_cluster_is_not_blamed_for_the_alert(harness) -> None:
    h = harness()
    deployed = (CHANGE_AT - timedelta(minutes=6)).isoformat()
    h.client.post(
        "/api/events",
        json=[
            {"service": "checkout-api", "type": "deploy", "version": "v2.3.1-eu", "cluster": "eu", "timestamp": deployed},
            {"service": "checkout-api", "type": "deploy", "version": "v2.3.1-us", "cluster": "us", "timestamp": deployed},
        ],
    )
    payload = _payload()
    payload["alerts"][0]["labels"]["cluster"] = "us"

    h.client.post("/api/integrations/alertmanager", json=payload)

    text = _message_text(h.posted[0])
    assert "v2.3.1-us" in text
    assert "v2.3.1-eu" not in text
    assert len(_rows()[0].change_event_ids) == 1


def test_generic_endpoint_is_labelled_external(harness) -> None:
    h = harness()
    response = h.client.post(
        "/api/alerts",
        json={"alert_name": "QueueBacklog", "service": "orders-worker", "starts_at": STARTS_AT.isoformat()},
    )
    assert response.status_code == 202
    text = _message_text(h.posted[0])
    assert "*External alert*" in text
    assert "could not derive a PromQL query" in text


def test_an_earlier_alerts_finding_is_not_reused(harness) -> None:
    # Reuse is for findings analysis produced on its own; an earlier alert's analysis isn't
    # "detected before the alert", so a re-fire is analyzed afresh.
    h = harness()
    h.client.post("/api/integrations/alertmanager", json=_payload(fingerprint="fp-first"))
    h.client.post("/api/integrations/alertmanager", json=_payload(fingerprint="fp-second"))

    assert len(h.pipeline.calls) == 2
    assert [row.analysis_status for row in _rows()] == ["analyzed", "analyzed"]
    assert "detected this" not in _message_text(h.posted[1])
