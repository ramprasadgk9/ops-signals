"""Pattern-aware change timing through the real receiver: the start time comes from the signals the
analyzers produced (backend/app/alerts/timing.py), and "What changed" is worded to match. Prometheus,
the pipeline and Slack are fakes, as in test_alert_receiver_api.py."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app.alerts.enrichment import AlertEnrichmentService
from backend.app.api.alerts import get_alert_enrichment_service
from backend.app.config import AlertEnrichmentConfig, PrometheusConnectionConfig, get_alert_enrichment_config
from backend.app.models.db import get_session_local
from intelligence.findings.schema import OperationalFinding
from tests.api_backend.test_alert_receiver_api import NOW, STARTS_AT, FakeQueryService, _message_text, _payload, _rows

SERVICE = "orders-worker"
METRIC = "kafka_consumergroup_lag"
LAG_EXPR = 'sum(kafka_consumergroup_lag{service="orders-worker"}) > 10000'


def _trend() -> SimpleNamespace:
    return SimpleNamespace(analyzer_id="trend", signal_type="trend", start_time=STARTS_AT - timedelta(hours=6), evidence={"slope": 0.4})


def _spike(minutes_before_alert: float) -> SimpleNamespace:
    return SimpleNamespace(
        analyzer_id="anomaly_zscore", signal_type="anomaly",
        start_time=STARTS_AT - timedelta(minutes=minutes_before_alert), evidence={},
    )


def _step(minutes_before_alert: float) -> SimpleNamespace:
    at = STARTS_AT - timedelta(minutes=minutes_before_alert)
    return SimpleNamespace(analyzer_id="baseline_shift", signal_type="baseline_shift", start_time=STARTS_AT - timedelta(hours=6), evidence={"change_point_time": at.isoformat()})


class ShiftedQueryService(FakeQueryService):
    """FakeQueryService's series, but shifting at `change_at` instead of 5 minutes before the alert."""

    def __init__(self, change_at) -> None:
        super().__init__()
        self.change_at = change_at

    def preview(self, query, start, end, step):
        preview = super().preview(query, start, end, step)
        for series in preview.series:
            for sample in series.samples:
                sample.value = 0.42 if sample.timestamp >= self.change_at else 0.18 + (sample.timestamp.minute % 3) * 0.001
        return preview


class SignalsPipeline:
    """Returns one significant finding plus whichever signals the test scripts."""

    def __init__(self, signals: list[SimpleNamespace]) -> None:
        self.signals = signals

    def __call__(self, normalized, app_config, run_metadata):
        finding = OperationalFinding(
            service=SERVICE, metric_name=METRIC, title="Consumer lag rising on orders-worker",
            summary="Lag has risen steadily.", category="behavior_change", health_status="significant",
            importance_score=0.7, analysis_run_id="run-lag",
        )
        return SimpleNamespace(analysis_run_id="run-lag", findings=[finding], signals=self.signals)


@pytest.fixture()
def receiver(client: TestClient):
    def build(signals: list[SimpleNamespace], query_service: FakeQueryService | None = None, **config_overrides):
        config = AlertEnrichmentConfig(enabled=True, slack_webhook_url="http://slack.example/hook", ui_base_url="http://ops.local", **config_overrides)
        posted: list[dict] = []
        service = AlertEnrichmentService(
            config,
            PrometheusConnectionConfig(base_url="http://prometheus:9090"),
            session_factory=lambda: get_session_local()(),
            query_service=query_service or FakeQueryService(),
            pipeline_runner=SignalsPipeline(signals),
            poster=posted.append,
            sleep=lambda _: None,
            clock=lambda: NOW,
        )
        client.app.dependency_overrides[get_alert_enrichment_config] = lambda: config
        client.app.dependency_overrides[get_alert_enrichment_service] = lambda: service
        return SimpleNamespace(client=client, posted=posted)

    yield build
    client.app.dependency_overrides.clear()


def _deploy(client: TestClient, version: str, minutes_before_alert: float, env: str | None = None) -> None:
    event = {"service": SERVICE, "type": "deploy", "version": version, "author": "bob",
             "timestamp": (STARTS_AT - timedelta(minutes=minutes_before_alert)).isoformat()}
    if env:
        event["env"] = env
    assert client.post("/api/events", json=event).status_code == 201


def _fire(h, **labels: str) -> str:
    payload = _payload(expr=LAG_EXPR)
    payload["alerts"][0]["labels"].update({"alertname": "OrdersConsumerLag", "service": SERVICE, **labels})
    assert h.client.post("/api/integrations/alertmanager", json=payload).status_code == 202
    [message] = h.posted
    return _message_text(message)


def test_slow_rise_with_a_recent_deploy_does_not_claim_the_deploy_started_it(receiver) -> None:
    h = receiver([_trend()])
    _deploy(h.client, "v4.0", 10)

    text = _fire(h)

    assert "Gradual upward trend with no clear start time" in text
    assert "• deploy `v4.0` by bob, 10 min before the alert fired" in text
    assert "Started" not in text
    [row] = _rows()
    assert row.enrichment_json["analysis"]["timing"] == {"basis": "trend", "time": None, "analyzer_id": None, "trend_direction": "upward"}
    assert len(row.change_event_ids) == 1


def test_spike_on_a_slow_rise_is_matched_against_the_spike(receiver) -> None:
    h = receiver([_trend(), _spike(2)])
    _deploy(h.client, "v4.1", 4)

    text = _fire(h)

    assert "Spike started *2 min after* deploy `v4.1` by bob" in text
    assert "gradual upward trend, which these changes may not explain" in text


def test_spike_older_than_the_lookback_falls_back_to_the_trend(receiver) -> None:
    h = receiver([_trend(), _spike(5 * 60)])
    _deploy(h.client, "v4.0", 10)

    assert "Gradual upward trend with no clear start time" in _fire(h)


def test_spike_lookback_is_configurable(receiver) -> None:
    h = receiver([_trend(), _spike(5 * 60)], spike_lookback_seconds=6 * 3600)
    _deploy(h.client, "v3.9", 5 * 60 + 3)

    assert "Spike started *3 min after* deploy `v3.9` by bob" in _fire(h)


def test_step_change_hours_before_the_alert_is_still_its_start(receiver) -> None:
    h = receiver([_step(3 * 60)], ShiftedQueryService(STARTS_AT - timedelta(hours=3)))
    _deploy(h.client, "v4.0", 3 * 60 + 6)
    _deploy(h.client, "v4.2", 10)

    text = _fire(h)

    assert "• Started *6 min after* deploy `v4.0` by bob" in text
    assert "v4.2" not in text  # near the alert, but nowhere near when the change started


def test_production_alert_skips_staging_deploys(receiver) -> None:
    h = receiver([_step(6)])
    _deploy(h.client, "v4.1-rc", 8, env="staging")
    _deploy(h.client, "v4.0", 12, env="prod")
    _deploy(h.client, "v3.9-hotfix", 10)  # no env: still matches

    text = _fire(h, env="prod")

    assert "v4.0" in text and "v3.9-hotfix" in text
    assert "v4.1-rc" not in text


def test_env_matching_can_be_turned_off(receiver) -> None:
    h = receiver([_step(6)], match_env=False)
    _deploy(h.client, "v4.1-rc", 8, env="staging")

    assert "v4.1-rc" in _fire(h, env="prod")


def test_settings_are_read_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("OPS_SIGNALS_ALERT_STEP_LOOKBACK", "2h")
    monkeypatch.setenv("OPS_SIGNALS_ALERT_SPIKE_LOOKBACK", "45m")
    monkeypatch.setenv("OPS_SIGNALS_ALERT_CHANGE_WINDOW_BEFORE", "1h")
    monkeypatch.setenv("OPS_SIGNALS_ALERT_CHANGE_WINDOW_AFTER", "10m")
    monkeypatch.setenv("OPS_SIGNALS_ALERT_MATCH_ENV", "false")
    config = get_alert_enrichment_config()
    assert (config.step_lookback_seconds, config.spike_lookback_seconds) == (7200, 2700)
    assert (config.correlation_before_seconds, config.correlation_after_seconds) == (3600, 600)
    assert config.match_env is False

    monkeypatch.setenv("OPS_SIGNALS_ALERT_STEP_LOOKBACK", "window")
    for name in ("OPS_SIGNALS_ALERT_SPIKE_LOOKBACK", "OPS_SIGNALS_ALERT_CHANGE_WINDOW_BEFORE",
                 "OPS_SIGNALS_ALERT_CHANGE_WINDOW_AFTER", "OPS_SIGNALS_ALERT_MATCH_ENV"):
        monkeypatch.delenv(name)
    config = get_alert_enrichment_config()
    assert config.step_lookback_seconds is None
    assert (config.spike_lookback_seconds, config.correlation_before_seconds, config.correlation_after_seconds) == (3600, 1800, 300)
    assert config.match_env is True
