"""Pod breakdown on alert-triggered analysis: the receiver re-runs the alert's query by pod and the
message says where the change came from. Real receiver, drill-down math and message builder;
Prometheus, the analyzers and Slack are fakes."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.alerts.enrichment import AlertEnrichmentService
from backend.app.api.alerts import get_alert_enrichment_service
from backend.app.config import AlertEnrichmentConfig, DrillDownConfig, PrometheusConnectionConfig, get_alert_enrichment_config
from backend.app.models.db import get_session_local
from backend.app.models.entities import FindingEntity
from backend.app.models.prometheus import PrometheusPreviewOut, PrometheusSeriesOut, PrometheusSeriesSample
from intelligence.findings.schema import OperationalFinding
from tests.api_backend.test_alert_receiver_api import CHANGE_AT, NOW, STARTS_AT, _message_text, _payload, _rows

SERVICE = "checkout"
METRIC = "demo_request_latency_ms"
EXPR = f'avg by (service) ({METRIC}{{service="{SERVICE}"}}) > 300'
OLD_PODS = ["checkout-1", "checkout-2", "checkout-3", "checkout-4"]
NEW_PODS = ["checkout-5", "checkout-6"]


class PodQueryService:
    """Service-level query: 180ms, then 320ms from CHANGE_AT. By pod: four pods stay at 180ms, and
    two new pods appear at CHANGE_AT at 600ms - the average the alert sees."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def preview(self, query: str, start, end, step) -> PrometheusPreviewOut:
        self.queries.append(query)
        times = []
        ts = start
        while ts <= min(end, NOW):
            times.append(ts)
            ts += timedelta(seconds=30)
        if "pod" in query:
            series = [
                PrometheusSeriesOut(labels={"service": SERVICE, "pod": pod}, samples=[PrometheusSeriesSample(timestamp=t, value=180.0 + (i % 3)) for i, t in enumerate(times)])
                for pod in OLD_PODS
            ] + [
                PrometheusSeriesOut(labels={"service": SERVICE, "pod": pod}, samples=[PrometheusSeriesSample(timestamp=t, value=600.0) for t in times if t >= CHANGE_AT])
                for pod in NEW_PODS
            ]
        else:
            samples = [PrometheusSeriesSample(timestamp=t, value=320.0 if t >= CHANGE_AT else 180.0 + (i % 3)) for i, t in enumerate(times)]
            series = [PrometheusSeriesOut(labels={"service": SERVICE}, samples=samples)]
        return PrometheusPreviewOut(
            query=query, start=start, end=end, step=step, step_seconds=30,
            series_count=len(series), sample_count=sum(len(s.samples) for s in series), series=series,
        )


class StepPipeline:
    def __call__(self, normalized, app_config, run_metadata):
        signal = SimpleNamespace(
            signal_id="sig-step", analyzer_id="baseline_shift", signal_type="baseline_shift",
            start_time=STARTS_AT - timedelta(hours=6), end_time=NOW,
            evidence={"change_point_time": CHANGE_AT.isoformat()},
        )
        finding = OperationalFinding(
            service=SERVICE, metric_name=METRIC, title="Sustained latency baseline shift on checkout",
            summary="Latency moved from ~180ms to ~320ms.", category="behavior_change",
            health_status="significant", importance_score=0.8, analysis_run_id="run-pods", signal_ids=["sig-step"],
        )
        with get_session_local()() as db:
            db.add(FindingEntity(**{k: v for k, v in finding.to_record().items() if k != "signal_ids"}, signal_ids=["sig-step"]))
            db.commit()
        return SimpleNamespace(analysis_run_id="run-pods", findings=[finding], signals=[signal])


@pytest.fixture()
def receiver(client: TestClient):
    def build(drilldown_enabled: bool = True):
        config = AlertEnrichmentConfig(enabled=True, slack_webhook_url="http://slack.example/hook", ui_base_url="http://ops.local")
        posted: list[dict] = []
        queries = PodQueryService()
        service = AlertEnrichmentService(
            config,
            PrometheusConnectionConfig(base_url="http://prometheus:9090"),
            session_factory=lambda: get_session_local()(),
            query_service=queries,
            pipeline_runner=StepPipeline(),
            poster=posted.append,
            sleep=lambda _: None,
            clock=lambda: NOW,
            drilldown_config=DrillDownConfig(enabled=drilldown_enabled),
        )
        client.app.dependency_overrides[get_alert_enrichment_config] = lambda: config
        client.app.dependency_overrides[get_alert_enrichment_service] = lambda: service
        return SimpleNamespace(client=client, posted=posted, queries=queries)

    yield build
    client.app.dependency_overrides.clear()


def _fire(h) -> str:
    payload = _payload(expr=EXPR)
    payload["alerts"][0]["labels"].update({"alertname": "CheckoutLatencyHigh", "service": SERVICE})
    assert h.client.post("/api/integrations/alertmanager", json=payload).status_code == 202
    [message] = h.posted
    return _message_text(message)


def test_alert_message_says_which_pods_the_change_came_from(receiver) -> None:
    h = receiver()

    text = _fire(h)

    assert f'avg by (service, pod) ({METRIC}{{service="{SERVICE}"}})' in h.queries.queries
    assert "📍 *Where:* 2 of 6 pods rose: checkout-5, checkout-6." in text
    assert "first appeared after the change started, which looks like a rollout in progress" in text
    [row] = _rows()
    breakdown = row.enrichment_json["analysis"]["finding"]["breakdown"]
    assert (breakdown["status"], breakdown["parts_total"], breakdown["parts_changed"], breakdown["new_parts"]) == ("ok", 6, 2, 2)
    with get_session_local()() as db:
        stored = db.execute(select(FindingEntity).where(FindingEntity.analysis_run_id == "run-pods")).scalars().one()
    assert stored.comparison_json["breakdown"]["spread"] == "partial"  # the UI shows the same chip


def test_drilldown_off_leaves_the_message_unchanged(receiver) -> None:
    h = receiver(drilldown_enabled=False)

    text = _fire(h)

    assert "Where:" not in text
    assert not any("pod" in query for query in h.queries.queries)
