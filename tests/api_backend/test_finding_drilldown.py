from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.api.autonomous import get_prometheus_query_service
from backend.app.autonomous import execution as autonomous_execution
from backend.app.autonomous.drilldown import drill_down_findings
from backend.app.autonomous.metric_executor import MetricAnalysisExecutionResult
from backend.app.config import DEFAULT_SPLIT_LABELS, DrillDownConfig
from backend.app.main import create_app
from backend.app.models.entities import FindingEntity
from backend.app.models.prometheus import PrometheusPreviewOut, PrometheusSeriesOut, PrometheusSeriesSample
from intelligence.findings.schema import OperationalFinding
from intelligence.signals.schema import OperationalSignal

from tests.api_backend.test_autonomous_preview import FakeMetadataProvider, FakeMetricAnalysisExecutor, metric

START = datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc)
CHANGE = START + timedelta(minutes=60)
END = START + timedelta(minutes=120)
PROMQL = 'sum by (service) (rate(http_errors_total{service="checkout"}[5m]))'
ENABLED = DrillDownConfig(enabled=True)
RUN_ID = "run-1"


def _pod_levels(bad_pod: str | None) -> dict[str, tuple[float, float]]:
    levels = {pod: (0.2, 0.2) for pod in ["a1", "x2", "k4", "m8", "p3", "z6"]}
    if bad_pod:
        levels[bad_pod] = (0.2, 3.6)
    return levels


class FakePrometheus:
    """Answers drill-down queries with one series per value of the grouped label."""

    def __init__(self, by_label: dict[str, dict[str, tuple[float, float]]] | None = None, error: Exception | None = None):
        self.by_label = by_label if by_label is not None else {"pod": _pod_levels("x2")}
        self.error = error
        self.queries: list[str] = []

    def preview(self, query: str, start, end, step: str) -> PrometheusPreviewOut:
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        label = next(name for name in DEFAULT_SPLIT_LABELS if f", {name})" in query)
        series = []
        for part, (before, after) in self.by_label.get(label, {"only": (1.0, 2.0)}).items():
            samples = [
                PrometheusSeriesSample(timestamp=timestamp, value=before if timestamp < CHANGE else after)
                for timestamp in pd.date_range(start, end, freq="1min")
            ]
            series.append(PrometheusSeriesOut(labels={"service": "checkout", label: part}, samples=samples))
        return PrometheusPreviewOut(
            query=query, start=start, end=end, step=step, step_seconds=60,
            series_count=len(series), sample_count=sum(len(item.samples) for item in series), series=series, warnings=[],
        )


def _signal(signal_type: str = "ruptures", **evidence) -> OperationalSignal:
    return OperationalSignal(
        signal_type=signal_type, analyzer_id=signal_type, metric_name="http_errors", service="checkout", env="prod",
        severity="high", confidence=0.9, start_time=START, end_time=END, summary="",
        evidence=evidence or {"change_point_time": CHANGE.isoformat()},
    )


def _result(db_session, signals: list[OperationalSignal]) -> MetricAnalysisExecutionResult:
    finding = OperationalFinding(
        service="checkout", metric_name="http_errors", title="http_errors moved to a new baseline.",
        summary="Errors rose.", category="change", health_status="degraded", importance_score=0.71,
        investigation_priority=2, signal_ids=[signal.signal_id for signal in signals],
        comparison_json={"change_percent": 308.0}, analysis_run_id=RUN_ID,
    )
    db_session.add(FindingEntity(**{key: value for key, value in finding.to_record().items() if key != "id"}))
    db_session.commit()
    points = pd.DataFrame({"timestamp": pd.date_range(START, END, freq="1min"), "value": 1.0})
    return MetricAnalysisExecutionResult(
        analysis_run_id=RUN_ID, normalized_points=points, signals=signals, findings=[finding],
        analyzer_routing=[], executed_analyzers=[], analyzer_executions=[],
        signal_count=len(signals), findings_count=1, behavior_findings_count=0,
    )


def _stored(db_session) -> FindingEntity:
    db_session.expire_all()
    return db_session.query(FindingEntity).filter_by(analysis_run_id=RUN_ID).one()


def test_breakdown_is_stored_and_nothing_else_changes(db_session) -> None:
    prometheus = FakePrometheus()
    result = _result(db_session, [_signal()])

    annotated = drill_down_findings(db=db_session, prometheus=prometheus, promql=PROMQL, step="1m", result=result, config=ENABLED)

    stored = _stored(db_session)
    breakdown = stored.comparison_json["breakdown"]
    assert annotated == 1
    assert breakdown["status"] == "ok"
    assert breakdown["spread"] == "concentrated"
    assert breakdown["top"][0]["value"] == "x2"
    assert breakdown["query"] == 'sum by (service, pod) (rate(http_errors_total{service="checkout"}[5m]))'
    assert stored.comparison_json["change_percent"] == 308.0
    assert stored.title == "http_errors moved to a new baseline."
    assert stored.summary == "Errors rose."
    assert stored.importance_score == 0.71
    assert stored.investigation_priority == 2
    assert result.findings[0].comparison_json["breakdown"] == breakdown


def test_falls_back_to_instance_when_there_is_no_pod_label(db_session) -> None:
    prometheus = FakePrometheus(by_label={"instance": _pod_levels("k4")})
    result = _result(db_session, [_signal()])

    drill_down_findings(db=db_session, prometheus=prometheus, promql=PROMQL, step="1m", result=result, config=ENABLED)

    breakdown = _stored(db_session).comparison_json["breakdown"]
    # pod, pod_name and kubernetes_pod_name each come back as one part first.
    assert len(prometheus.queries) == 4
    assert breakdown["label"] == "instance"
    assert breakdown["top"][0]["value"] == "k4"


def test_finds_the_pod_under_another_collectors_label_name(db_session) -> None:
    prometheus = FakePrometheus(by_label={"kubernetes_pod_name": _pod_levels("x2")})
    result = _result(db_session, [_signal()])

    drill_down_findings(db=db_session, prometheus=prometheus, promql=PROMQL, step="1m", result=result, config=ENABLED)

    breakdown = _stored(db_session).comparison_json["breakdown"]
    assert breakdown["label"] == "kubernetes_pod_name"
    assert breakdown["top"][0]["value"] == "x2"


def test_too_many_parts_is_recorded_as_skipped(db_session) -> None:
    error = HTTPException(status_code=400, detail="query returned 80 series, which exceeds max_series 20")
    result = _result(db_session, [_signal()])

    drill_down_findings(db=db_session, prometheus=FakePrometheus(error=error), promql=PROMQL, step="1m", result=result, config=ENABLED)

    assert _stored(db_session).comparison_json["breakdown"] == {
        "status": "skipped", "reason": "too_many_parts", "labels_tried": list(DEFAULT_SPLIT_LABELS),
    }


def test_unexpected_error_marks_breakdown_failed_and_keeps_finding(db_session) -> None:
    result = _result(db_session, [_signal()])

    drill_down_findings(db=db_session, prometheus=FakePrometheus(error=RuntimeError("boom")), promql=PROMQL, step="1m", result=result, config=ENABLED)

    stored = _stored(db_session)
    assert stored.comparison_json["breakdown"] == {"status": "failed", "reason": "error"}
    assert stored.comparison_json["change_percent"] == 308.0


def test_unsupported_query_shape_makes_no_query(db_session) -> None:
    prometheus = FakePrometheus()
    result = _result(db_session, [_signal()])

    drill_down_findings(db=db_session, prometheus=prometheus, promql="rate(http_errors_total[5m])", step="1m", result=result, config=ENABLED)

    assert prometheus.queries == []
    assert _stored(db_session).comparison_json["breakdown"]["reason"] == "query_shape_not_supported"


def test_finding_without_change_time_makes_no_query(db_session) -> None:
    prometheus = FakePrometheus()
    result = _result(db_session, [_signal("trend", slope=0.4)])

    drill_down_findings(db=db_session, prometheus=prometheus, promql=PROMQL, step="1m", result=result, config=ENABLED)

    assert prometheus.queries == []
    assert _stored(db_session).comparison_json["breakdown"] == {"status": "skipped", "reason": "no_change_time"}


def test_data_health_finding_gets_no_breakdown(db_session) -> None:
    prometheus = FakePrometheus()
    result = _result(db_session, [_signal("data_gap")])

    assert drill_down_findings(db=db_session, prometheus=prometheus, promql=PROMQL, step="1m", result=result, config=ENABLED) == 0
    assert prometheus.queries == []
    assert "breakdown" not in _stored(db_session).comparison_json


def test_disabled_config_does_nothing(db_session) -> None:
    prometheus = FakePrometheus()
    result = _result(db_session, [_signal()])

    assert drill_down_findings(db=db_session, prometheus=prometheus, promql=PROMQL, step="1m", result=result, config=DrillDownConfig()) == 0
    assert prometheus.queries == []
    assert "breakdown" not in _stored(db_session).comparison_json


@pytest.mark.parametrize("flag, expected_calls", [(None, 0), ("false", 0), ("true", 1)])
def test_run_once_drills_down_only_when_enabled(monkeypatch, flag, expected_calls) -> None:
    if flag is None:
        monkeypatch.delenv("OPS_SIGNALS_DRILLDOWN_ENABLED", raising=False)
    else:
        monkeypatch.setenv("OPS_SIGNALS_DRILLDOWN_ENABLED", flag)
    calls = []
    monkeypatch.setattr(autonomous_execution, "MetricAnalysisExecutor", FakeMetricAnalysisExecutor)
    monkeypatch.setattr(autonomous_execution, "drill_down_findings", lambda **kwargs: calls.append(kwargs) or 0)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeMetadataProvider([metric("cpu_usage", "checkout")])
    with TestClient(app) as client:
        response = client.post(
            "/api/autonomous/run-once",
            json={
                "datasource": "prometheus",
                "backend": "grafana-stack",
                "scope": {"all_services": True, "all_namespaces": True},
                "monitoring_categories": ["capacity"],
                "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert len(calls) == expected_calls
