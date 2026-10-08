from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import numpy as np
import pandas as pd
import pytest

from backend.app.alerts.alertmanager import expr_from_generator_url, from_alertmanager
from backend.app.alerts.classifier import classify, resolve_metric_key
from backend.app.alerts.query_builder import metric_names, query_window, strip_threshold
from backend.app.alerts.schemas import AlertmanagerWebhook, NormalizedAlert
from backend.app.config import AlertEnrichmentConfig
from intelligence.analyzers.baseline_shift import BaselineShiftAnalyzer
from intelligence.analyzers.ruptures import change_point_time

LATENCY = 'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{service="checkout-api"}[5m])))'


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        (f"{LATENCY} > 0.3", LATENCY),
        ("0.3 < rate(errors_total[5m])", "rate(errors_total[5m])"),
        ("rate(errors_total[5m]) > bool 0.1", "rate(errors_total[5m])"),
        ("node_memory_usage_ratio >= 9e-1", "node_memory_usage_ratio"),
        ('sum(rate(http_requests_total{code!="200"}[5m])) > 5', 'sum(rate(http_requests_total{code!="200"}[5m]))'),
        ('rate(x{path=~"/a>b"}[5m]) > 1', 'rate(x{path=~"/a>b"}[5m])'),
        ("(a / b) > 0.05", "(a / b)"),
        ("rate(x[5m])", "rate(x[5m])"),  # no comparison: used as-is
        ("sum(rate(x[5m])) > sum(rate(y[5m]))", None),  # vector vs vector
        ("a / b > 0.05 and on() hour() > 8", None),  # set operator
        ("a > 1 < 5", None),  # several comparisons
    ],
)
def test_strip_threshold(expr: str, expected: str | None) -> None:
    assert strip_threshold(expr) == expected


def test_metric_names_skip_functions_labels_ranges_and_grouping() -> None:
    assert metric_names(LATENCY) == ["http_request_duration_seconds_bucket"]
    assert metric_names("sum by (pod) (rate(a_total[5m])) / on(pod) group_left sum(b_total)") == ["a_total", "b_total"]
    assert metric_names('up{job="api"}') == ["up"]


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("rate(x_total[5m] offset 5m)", ["x_total"]),  # duration after offset is not a metric
        ("x > 1e3", ["x"]),  # exponent is not a metric
        ('$metric{service="a"}', []),  # dashboard variable, resolved by the caller
        ("x # comment y", ["x"]),
        ("job:http:rate5m", ["job:http:rate5m"]),
    ],
)
def test_metric_names_ignore_durations_numbers_variables_and_comments(expr: str, expected: list[str]) -> None:
    assert metric_names(expr) == expected


def test_query_window_defaults_to_6h_at_30s_and_respects_annotation_and_point_cap() -> None:
    now = datetime(2026, 9, 23, 14, 13, tzinfo=timezone.utc)
    config = AlertEnrichmentConfig()

    default = query_window(config, {}, now)
    assert default.end == now
    assert default.start == now - timedelta(hours=6)
    assert default.step_seconds == 30

    week = query_window(config, {"ops_signals_lookback": "7d"}, now)
    assert week.start == now - timedelta(days=7)
    assert (7 * 86400) / week.step_seconds <= config.max_points

    clamped = query_window(config, {"ops_signals_lookback": "5m"}, now)
    assert clamped.start == now - timedelta(hours=1)


def test_expr_from_generator_url() -> None:
    url = f"http://prometheus:9090/graph?g0.expr={quote(LATENCY + ' > 0.3')}&g0.tab=1"
    assert expr_from_generator_url(url) == LATENCY + " > 0.3"
    assert expr_from_generator_url("http://grafana:3000/alerting/grafana/abc123/view") is None
    assert expr_from_generator_url(None) is None


def test_from_alertmanager_normalizes_payload() -> None:
    payload = AlertmanagerWebhook.model_validate(
        {
            "version": "4",
            "status": "firing",
            "externalURL": "http://alertmanager:9093",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "CheckoutHighLatency", "job": "checkout", "service": "checkout-api", "severity": "warning"},
                    "annotations": {"summary": "p95 above 300ms"},
                    "startsAt": "2026-09-23T14:13:00Z",
                    "endsAt": "0001-01-01T00:00:00Z",
                    "generatorURL": f"http://prometheus:9090/graph?g0.expr={quote('up == 0')}",
                    "fingerprint": "a1b2c3",
                }
            ],
        }
    )
    [alert] = from_alertmanager(payload, ["service", "job"])
    assert alert.service == "checkout-api"  # first configured label wins
    assert alert.fingerprint == "a1b2c3"
    assert alert.ends_at is None  # zero time means "not resolved"
    assert alert.expr == "up == 0"
    assert alert.external_url == "http://alertmanager:9093"


def _alert(expr: str | None = None, **annotations: str) -> NormalizedAlert:
    return NormalizedAlert(
        source="alertmanager",
        fingerprint="f",
        status="firing",
        alert_name="SomeAlert",
        service="checkout-api",
        severity="warning",
        starts_at=datetime(2026, 9, 23, 14, 13, tzinfo=timezone.utc),
        ends_at=None,
        labels={"alertname": "SomeAlert", "service": "checkout-api"},
        annotations=dict(annotations),
        expr=expr,
    )


@pytest.mark.parametrize(
    ("alert", "prometheus", "analyze", "reason"),
    [
        (_alert(f"{LATENCY} > 0.3"), True, True, None),
        (_alert(f"{LATENCY} > 0.3", ops_signals_analyze="false"), True, False, "disabled_by_annotation"),
        (_alert(f"{LATENCY} > 0.3"), False, False, "no_prometheus"),
        (_alert(None), True, False, "no_query"),
        (_alert('sum(count_over_time({app="x"} |= "error" [5m])) > 10'), True, False, "log_alert"),
        (_alert('absent(up{job="api"})'), True, False, "absence_alert"),
        (_alert('up{job="api"} == 0'), True, False, "status_alert"),
        (_alert("increase(kube_pod_container_status_restarts_total[10m]) > 3"), True, False, "status_alert"),
        (_alert('up{job="api"} == 0', ops_signals_analyze="true"), True, True, None),
        (_alert("sum(rate(a[5m])) > sum(rate(b[5m]))"), True, False, "no_query"),
        (_alert("sum(rate(a[5m])) > sum(rate(b[5m]))", ops_signals_query="sum(rate(a[5m]))"), True, True, None),
    ],
)
def test_classify(alert: NormalizedAlert, prometheus: bool, analyze: bool, reason: str | None) -> None:
    decision = classify(alert, prometheus_configured=prometheus)
    assert decision.analyze is analyze
    assert decision.reason == reason


def test_classify_returns_the_stripped_query_and_metric_key() -> None:
    decision = classify(_alert(f"{LATENCY} > 0.3"), prometheus_configured=True)
    assert decision.query == LATENCY
    assert decision.metric_key == "http_request_duration_seconds_bucket"


def test_metric_key_prefers_annotation_then_expr_then_alertname() -> None:
    assert resolve_metric_key(_alert(LATENCY, ops_signals_metric="checkout_p95"), LATENCY) == "checkout_p95"
    assert resolve_metric_key(_alert(None), None) == "SomeAlert"


def test_change_point_time_maps_through_non_finite_values() -> None:
    timestamps = pd.Series(pd.date_range("2026-09-23T14:00:00Z", periods=4, freq="1min"))
    values = pd.Series([1.0, np.nan, 2.0, 3.0])
    # Index 1 among the finite values is the third row (14:02), not the NaN row.
    assert change_point_time(timestamps, values, 1) == "2026-09-23T14:02:00+00:00"
    assert change_point_time(timestamps, values, 10) is None


def test_baseline_shift_evidence_carries_change_point_time() -> None:
    timestamps = pd.date_range("2026-09-23T12:00:00Z", periods=60, freq="1min")
    values = [0.18] * 40 + [0.42] * 20
    frame = pd.DataFrame(
        {"timestamp": timestamps, "value": values, "metric_name": "latency", "service": "checkout-api", "env": None}
    )
    [signal] = BaselineShiftAnalyzer(threshold_percent=25.0, ruptures_jump=1).analyze(frame)
    assert signal.evidence["change_point_time"] == "2026-09-23T12:40:00+00:00"
