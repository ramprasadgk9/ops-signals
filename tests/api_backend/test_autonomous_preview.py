from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.autonomous import execution as autonomous_execution
from backend.app.api.autonomous import get_prometheus_query_service
from backend.app.autonomous.schemas import AnalysisScope, CustomMetricConstraints, DiscoveredMetric, ExecutionPolicy, MetricConcept, MonitoringCategory
from backend.app.autonomous.services import MetricClassificationService, MetricDiscoveryService, MetricPlanBuilder, build_label_matcher, build_scope_selector, validate_label_name
from backend.app.main import create_app
from backend.app.models.prometheus import PrometheusPreviewOut, PrometheusSeriesOut, PrometheusSeriesSample


class FakeMetadataProvider:
    def __init__(self, metrics: list[DiscoveredMetric]):
        self.metrics = metrics

    def discover_metric_metadata(self, **kwargs):
        return list(self.metrics)

    def label_values(self, label: str):
        values = sorted({metric.labels[label] for metric in self.metrics if label in metric.labels})
        return values

    def preview(self, query: str, start, end, step: str):
        samples = [
            PrometheusSeriesSample(timestamp=start + (end - start) * (idx / 30), value=float(idx))
            for idx in range(31)
        ]
        metric_name = "memory_usage" if "memory_usage" in query else "cpu_usage"
        service = "payments" if "payments" in query else "checkout"
        return PrometheusPreviewOut(
            query=query,
            start=start,
            end=end,
            step=step,
            step_seconds=600,
            series_count=1,
            sample_count=len(samples),
            series=[PrometheusSeriesOut(labels={"__name__": metric_name, "service": service}, samples=samples)],
            warnings=[],
        )


class FakeFailingProvider(FakeMetadataProvider):
    def __init__(self, metrics: list[DiscoveredMetric], fail_all: bool = False):
        super().__init__(metrics)
        self.fail_all = fail_all

    def preview(self, query: str, start, end, step: str):
        if self.fail_all or "memory_usage" in query:
            raise ValueError("synthetic prometheus failure")
        return super().preview(query, start, end, step)


class FakeMetricAnalysisExecutor:
    def __init__(self, config):
        self.config = config

    def execute_dataframe(self, dataframe, *, run_metadata=None, db=None):
        metric = str(run_metadata.get("promql", "metric")) if run_metadata else "metric"
        suffix = "memory" if "memory_usage" in metric else "cpu"
        return type(
            "Result",
            (),
            {
                "analysis_run_id": f"analysis-run-{suffix}",
                "signal_count": 1,
                "findings_count": 1 if suffix == "cpu" else 0,
                "behavior_findings_count": 0,
            },
        )()


def metric(name: str, service: str | None = "checkout", namespace: str | None = "commerce", env: str | None = "production", labels: dict | None = None):
    metric_labels = {"__name__": name}
    if service:
        metric_labels["service"] = service
    if namespace:
        metric_labels["namespace"] = namespace
    if env:
        metric_labels["env"] = env
    metric_labels.update(labels or {})
    return DiscoveredMetric(metric_name=name, labels=metric_labels, service=service, namespace=namespace, environment=env, source="prometheus")


def build_plan(metrics: list[DiscoveredMetric], scope: AnalysisScope | None = None, categories: list[MonitoringCategory] | None = None, max_metrics: int = 500, custom: CustomMetricConstraints | None = None):
    resolved, discovered = MetricDiscoveryService(FakeMetadataProvider(metrics)).discover(scope or AnalysisScope())
    return MetricPlanBuilder().build(
        resolved_scope=resolved,
        discovered_metrics=discovered,
        selected_categories=categories or [MonitoringCategory.performance, MonitoringCategory.capacity, MonitoringCategory.availability],
        execution=ExecutionPolicy(max_metrics_per_run=max_metrics),
        custom_constraints=custom or CustomMetricConstraints(),
        classifier=MetricClassificationService(),
    )


def test_all_services_scope_resolution() -> None:
    resolved, discovered = MetricDiscoveryService(FakeMetadataProvider([metric("cpu_usage", "checkout"), metric("memory_usage", "payments")])).discover(AnalysisScope(all_services=True))
    assert resolved.resolved_services == ["checkout", "payments"]
    assert len(discovered) == 2


def test_all_services_plan_builds_single_service_queries() -> None:
    plan = build_plan([metric("cpu_usage", "checkout"), metric("memory_usage", "payments")], AnalysisScope(all_services=True), categories=[MonitoringCategory.capacity])
    planned = {item.metric_name: item.promql for item in plan.items if item.planned}
    assert 'cpu_usage{' in planned["cpu_usage"]
    assert 'service="checkout"' in planned["cpu_usage"]
    assert 'env="production"' in planned["cpu_usage"]
    assert 'memory_usage{' in planned["memory_usage"]
    assert 'service="payments"' in planned["memory_usage"]
    assert 'env="production"' in planned["memory_usage"]


def test_selected_service_filtering() -> None:
    plan = build_plan([metric("cpu_usage", "checkout"), metric("memory_usage", "payments")], AnalysisScope(all_services=False, services=["payments"]))
    assert plan.total_metrics_discovered == 1
    assert plan.items[0].service == "payments"
    assert 'service="payments"' in plan.items[0].promql


def test_namespace_filtering() -> None:
    plan = build_plan([metric("cpu_usage", namespace="commerce"), metric("cpu_usage", namespace="platform")], AnalysisScope(all_namespaces=False, namespaces=["platform"]))
    assert plan.total_metrics_discovered == 1
    assert plan.items[0].namespace == "platform"


def test_missing_service_label_warns_without_failure() -> None:
    resolved, discovered = MetricDiscoveryService(FakeMetadataProvider([metric("cpu_usage", service=None)])).discover(AnalysisScope(service_label="app"))
    assert discovered
    assert any("No services were found" in warning for warning in resolved.warnings)


def test_empty_discovery_result() -> None:
    resolved, discovered = MetricDiscoveryService(FakeMetadataProvider([])).discover(AnalysisScope())
    assert discovered == []
    assert resolved.discovered_metric_count == 0


def test_category_to_concept_expansion() -> None:
    plan = build_plan([metric("cpu_usage")], categories=[MonitoringCategory.capacity])
    assert MetricConcept.cpu in plan.items[0].concepts
    assert "cpu" in plan.monitoring_summary["concepts"]


def test_exact_metric_classification() -> None:
    plan = build_plan([metric("container_cpu_usage_seconds_total")], categories=[MonitoringCategory.capacity])
    assert plan.items[0].planned is True
    assert plan.items[0].selection_reason == "exact_metric_mapping"
    assert plan.items[0].concept == MetricConcept.cpu


def test_regex_classification() -> None:
    plan = build_plan([metric("service_latency_seconds")], categories=[MonitoringCategory.performance])
    assert plan.items[0].planned is True
    assert plan.items[0].selection_reason == "metric_name_pattern"


def test_metadata_metric_exclusion() -> None:
    plan = build_plan([metric("build_info")], categories=[MonitoringCategory.infrastructure])
    assert plan.items[0].planned is False
    assert plan.items[0].exclusion_reason == "static_metadata_metric"


def test_created_metric_exclusion() -> None:
    plan = build_plan([metric("http_requests_created")], categories=[MonitoringCategory.performance])
    assert plan.items[0].planned is False
    assert plan.items[0].exclusion_reason == "created_timestamp"


def test_custom_include_and_exclude_behavior() -> None:
    custom = CustomMetricConstraints(include_patterns=["custom_.*"], exclude_patterns=["custom_ignore_.*"])
    plan = build_plan([metric("custom_latency"), metric("custom_ignore_latency")], categories=[MonitoringCategory.custom], custom=custom)
    assert plan.items[0].planned is True
    assert plan.items[0].selection_reason == "custom_include_pattern"
    assert plan.items[1].planned is False
    assert plan.items[1].exclusion_reason == "custom_exclude_pattern"


def test_multi_category_classification() -> None:
    plan = build_plan([metric("container_cpu_usage_seconds_total")], categories=[MonitoringCategory.capacity, MonitoringCategory.infrastructure])
    assert plan.items[0].planned is True
    assert plan.items[0].category in {MonitoringCategory.capacity, MonitoringCategory.infrastructure}


def test_budget_enforcement() -> None:
    plan = build_plan([metric("cpu_usage", "a"), metric("memory_usage", "b")], categories=[MonitoringCategory.capacity], max_metrics=1)
    assert plan.planned_jobs == 1
    assert plan.budget_limited_jobs == 1


def test_small_budget_prefers_demo_signal_services() -> None:
    plan = build_plan(
        [
            metric("cpu_usage", "checkout"),
            metric("cpu_usage", "spike-lab"),
            metric("memory_usage", "payments"),
        ],
        scope=AnalysisScope(all_services=True),
        categories=[MonitoringCategory.capacity],
        max_metrics=1,
    )
    planned = [item for item in plan.items if item.planned]
    assert len(planned) == 1
    assert planned[0].service == "spike-lab"
    assert 'service="spike-lab"' in planned[0].promql
    assert plan.items[0].planned is True
    assert plan.items[0].service == "spike-lab"


def test_duplicate_metric_removal_and_service_grouping() -> None:
    plan = build_plan([metric("cpu_usage", "checkout"), metric("cpu_usage", "checkout")], categories=[MonitoringCategory.capacity])
    assert plan.total_metrics_discovered == 1
    assert plan.items[0].estimated_series_count == 2
    assert plan.items[0].aggregation_strategy == "avg_by_service"


def test_invalid_label_key_rejection() -> None:
    try:
        validate_label_name("bad-label", "service_label")
    except ValueError as exc:
        assert "valid Prometheus label name" in str(exc)
    else:
        raise AssertionError("invalid label was accepted")


def test_single_value_selector_generation() -> None:
    assert build_label_matcher("service", ["payments"]) == 'service="payments"'


def test_multi_value_regex_selector_generation() -> None:
    assert build_label_matcher("service", ["payments", "checkout"]) == 'service=~"checkout|payments"'


def test_all_services_and_namespaces_selector_behavior() -> None:
    selector = build_scope_selector(AnalysisScope(environment="production", services=["payments"], all_services=True, namespaces=["commerce"], all_namespaces=True))
    assert selector == '{env="production"}'


def test_counter_rate_query() -> None:
    plan = build_plan([metric("container_cpu_usage_seconds_total")], categories=[MonitoringCategory.capacity])
    assert "rate(container_cpu_usage_seconds_total" in plan.items[0].promql
    assert plan.items[0].transformation == "rate"


def test_gauge_aggregation_query() -> None:
    plan = build_plan([metric("container_memory_working_set_bytes")], categories=[MonitoringCategory.capacity])
    assert plan.items[0].promql.startswith("avg by (service)")
    assert "rate(" not in plan.items[0].promql


def test_histogram_p95_query() -> None:
    plan = build_plan([metric("http_request_duration_seconds_bucket", labels={"le": "0.5"})], categories=[MonitoringCategory.performance])
    assert "histogram_quantile(0.95" in plan.items[0].promql
    assert "sum by (le, service)" in plan.items[0].promql


def test_duplicate_concept_ranking() -> None:
    plan = build_plan([metric("cpu_usage", "checkout"), metric("process_cpu_seconds_total", "checkout")], categories=[MonitoringCategory.capacity])
    planned = [item for item in plan.items if item.planned]
    excluded = [item for item in plan.items if item.exclusion_reason == "duplicate_lower_rank"]
    assert len(planned) == 1
    assert len(excluded) == 1


def test_preview_api_validation_and_response() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeMetadataProvider([metric("http_request_duration_seconds")])
    with TestClient(app) as client:
        response = client.post(
            "/api/autonomous/preview",
            json={
                "datasource": "prometheus",
                "backend": "grafana-stack",
                "scope": {"all_services": True, "all_namespaces": True},
                "monitoring_categories": ["performance"],
                "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
            },
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["planned_jobs"] == 1
    assert payload["monitoring_summary"]["concepts"]
    assert payload["items"][0]["promql"]


def test_run_once_dry_run_returns_planned_jobs_without_execution() -> None:
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
                "dry_run": True,
            },
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "dry_run"
    assert payload["policy_run_id"]
    assert payload["planned_jobs"] == 1
    assert payload["executed_jobs"] == 0
    assert payload["results"][0]["status"] == "skipped"
    assert payload["results"][0]["job_id"]


def test_preview_api_requires_category() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        response = client.post("/api/autonomous/preview", json={"monitoring_categories": []})
    assert response.status_code == 422


def test_scope_options_api_returns_backend_metadata() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeMetadataProvider([metric("cpu_usage", "checkout", "commerce"), metric("memory_usage", "payments", "billing")])
    with TestClient(app) as client:
        response = client.get("/api/autonomous/scope-options")
    assert response.status_code == 200
    assert response.json()["services"] == ["checkout", "payments"]
    assert response.json()["namespaces"] == ["billing", "commerce"]


def test_run_once_creates_policy_run_and_completed_job(monkeypatch) -> None:
    monkeypatch.setattr(autonomous_execution, "MetricAnalysisExecutor", FakeMetricAnalysisExecutor)
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
        payload = response.json()
        run_response = client.get(f"/api/autonomous/policy-runs/{payload['policy_run_id']}")
        jobs_response = client.get(f"/api/autonomous/policy-runs/{payload['policy_run_id']}/jobs")
    assert response.status_code == 200
    assert payload["status"] == "completed"
    assert payload["summary"]["jobs_completed"] == 1
    assert run_response.json()["status"] == "completed"
    assert jobs_response.json()[0]["analysis_run_id"] == "analysis-run-cpu"
    assert jobs_response.json()[0]["status"] == "completed"


def test_multiple_planned_metrics_create_multiple_jobs(monkeypatch) -> None:
    monkeypatch.setattr(autonomous_execution, "MetricAnalysisExecutor", FakeMetricAnalysisExecutor)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeMetadataProvider([metric("cpu_usage", "checkout"), metric("memory_usage", "payments")])
    with TestClient(app) as client:
        response = client.post(
            "/api/autonomous/run-once",
            json={
                "scope": {"all_services": True, "all_namespaces": True},
                "monitoring_categories": ["capacity"],
                "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
            },
        )
        jobs = client.get(f"/api/autonomous/policy-runs/{response.json()['policy_run_id']}/jobs").json()
    assert response.status_code == 200
    assert response.json()["planned_jobs"] == 2
    assert len(jobs) == 2
    assert {job["metric_name"] for job in jobs} == {"cpu_usage", "memory_usage"}


def test_skipped_job_persists_skip_reason(monkeypatch) -> None:
    monkeypatch.setattr(autonomous_execution, "MetricAnalysisExecutor", FakeMetricAnalysisExecutor)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeMetadataProvider([metric("cpu_usage", "checkout"), metric("request_latency_p95", "checkout")])
    with TestClient(app) as client:
        response = client.post(
            "/api/autonomous/run-once",
            json={
                "scope": {"all_services": True, "all_namespaces": True},
                "monitoring_categories": ["capacity"],
                "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
            },
        )
        jobs = client.get(f"/api/autonomous/policy-runs/{response.json()['policy_run_id']}/jobs").json()
    skipped = [job for job in jobs if job["status"] == "screened_out"]
    assert skipped
    assert skipped[0]["skip_reason_code"] == "category_not_selected"
    assert skipped[0]["skip_reason_detail"]


def test_one_job_failure_keeps_success_and_marks_run_partial(monkeypatch) -> None:
    monkeypatch.setattr(autonomous_execution, "MetricAnalysisExecutor", FakeMetricAnalysisExecutor)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeFailingProvider([metric("cpu_usage", "checkout"), metric("memory_usage", "payments")])
    with TestClient(app) as client:
        response = client.post(
            "/api/autonomous/run-once",
            json={
                "scope": {"all_services": True, "all_namespaces": True},
                "monitoring_categories": ["capacity"],
                "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
            },
        )
        payload = response.json()
        jobs = client.get(f"/api/autonomous/policy-runs/{payload['policy_run_id']}/jobs").json()
    assert payload["status"] == "partial"
    assert payload["executed_jobs"] == 1
    assert payload["failed_jobs"] == 1
    assert any(job["status"] == "completed" and job["analysis_run_id"] == "analysis-run-cpu" for job in jobs)
    assert any(job["status"] == "failed" and job["error_type"] == "ValueError" for job in jobs)


def test_all_failed_jobs_mark_policy_run_failed(monkeypatch) -> None:
    monkeypatch.setattr(autonomous_execution, "MetricAnalysisExecutor", FakeMetricAnalysisExecutor)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeFailingProvider([metric("cpu_usage", "checkout")], fail_all=True)
    with TestClient(app) as client:
        response = client.post(
            "/api/autonomous/run-once",
            json={
                "scope": {"all_services": True, "all_namespaces": True},
                "monitoring_categories": ["capacity"],
                "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
            },
        )
        run = client.get(f"/api/autonomous/policy-runs/{response.json()['policy_run_id']}").json()
    assert response.json()["status"] == "failed"
    assert run["status"] == "failed"
    assert run["jobs_failed"] == 1


def test_policy_snapshot_is_historical_copy(monkeypatch) -> None:
    monkeypatch.setattr(autonomous_execution, "MetricAnalysisExecutor", FakeMetricAnalysisExecutor)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeMetadataProvider([metric("cpu_usage", "checkout")])
    request_payload = {
        "scope": {"all_services": True, "all_namespaces": True},
        "monitoring_categories": ["capacity"],
        "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
    }
    with TestClient(app) as client:
        response = client.post("/api/autonomous/run-once", json=request_payload)
        request_payload["execution"]["analysis_window"] = "7d"
        run = client.get(f"/api/autonomous/policy-runs/{response.json()['policy_run_id']}").json()
    assert run["policy_snapshot"]["execution_policy"]["analysis_window"] == "24h"


def test_autonomous_policy_run_history_endpoint_returns_runs(monkeypatch) -> None:
    monkeypatch.setattr(autonomous_execution, "MetricAnalysisExecutor", FakeMetricAnalysisExecutor)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeMetadataProvider([metric("cpu_usage", "checkout")])
    with TestClient(app) as client:
        run_response = client.post(
            "/api/autonomous/run-once",
            json={
                "scope": {"all_services": True, "all_namespaces": True},
                "monitoring_categories": ["capacity"],
                "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
            },
        )
        history = client.get("/api/autonomous/policy-runs").json()
    assert any(row["policy_run_id"] == run_response.json()["policy_run_id"] for row in history)


def test_autonomous_jobs_endpoint_returns_only_requested_policy_run(monkeypatch) -> None:
    monkeypatch.setattr(autonomous_execution, "MetricAnalysisExecutor", FakeMetricAnalysisExecutor)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeMetadataProvider([metric("cpu_usage", "checkout")])
    with TestClient(app) as client:
        first = client.post(
            "/api/autonomous/run-once",
            json={
                "scope": {"all_services": True, "all_namespaces": True},
                "monitoring_categories": ["capacity"],
                "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
            },
        ).json()
        second = client.post(
            "/api/autonomous/run-once",
            json={
                "scope": {"all_services": True, "all_namespaces": True},
                "monitoring_categories": ["capacity"],
                "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
            },
        ).json()
        first_jobs = client.get(f"/api/autonomous/policy-runs/{first['policy_run_id']}/jobs").json()
        second_jobs = client.get(f"/api/autonomous/policy-runs/{second['policy_run_id']}/jobs").json()
    assert first_jobs
    assert second_jobs
    assert {job["policy_run_id"] for job in first_jobs} == {first["policy_run_id"]}
    assert {job["policy_run_id"] for job in second_jobs} == {second["policy_run_id"]}


def test_autonomous_code_does_not_import_signal_pipeline() -> None:
    autonomous_files = [
        path
        for path in Path(__file__).resolve().parents[2].joinpath("backend", "app", "autonomous").glob("*.py")
    ]
    for path in autonomous_files:
        source = path.read_text()
        assert "from intelligence.pipeline import SignalPipeline" not in source
        assert "import SignalPipeline" not in source
        assert "SignalPipeline(" not in source
