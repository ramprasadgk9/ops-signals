"""Multi-cluster Prometheus backends (Mimir, Thanos): HA replica copies count once, and autonomous
monitoring plans one job per cluster instead of summing clusters together."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.app.api.autonomous import get_prometheus_query_service
from backend.app.autonomous import execution as autonomous_execution
from backend.app.autonomous.schemas import AnalysisScope, CustomMetricConstraints, DiscoveredMetric, ExecutionPolicy, MonitoringCategory
from backend.app.autonomous.services import MetricClassificationService, MetricDiscoveryService, MetricPlanBuilder
from backend.app.config import PrometheusConnectionConfig, get_prometheus_config
from backend.app.main import create_app
from backend.app.models.prometheus import PrometheusPreviewOut, PrometheusSeriesOut, PrometheusSeriesSample
from backend.app.services.prometheus_service import PrometheusQueryService

START = datetime(2026, 10, 1, tzinfo=timezone.utc)
END = START + timedelta(hours=1)


def _matrix(*series: tuple[dict[str, str], list[float]]) -> dict:
    return {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [
                {"metric": labels, "values": [[START.timestamp() + 60 * index, str(value)] for index, value in enumerate(values)]}
                for labels, values in series
            ],
        },
    }


def _service(payload: dict, **config: object) -> PrometheusQueryService:
    service = PrometheusQueryService(PrometheusConnectionConfig(base_url="http://mimir.test", **config))
    service._get_json = lambda path, params: payload  # type: ignore[method-assign]
    return service


# --- HA replica dedup -------------------------------------------------------------------------


def test_ha_replica_pair_becomes_one_series_without_the_replica_label() -> None:
    labels = {"__name__": "up", "service": "checkout", "cluster": "eu"}
    payload = _matrix(({**labels, "prometheus_replica": "a"}, [1, 1, 1]), ({**labels, "prometheus_replica": "b"}, [1, 1, 1]))

    preview = _service(payload).preview("up", START, END, "60s")

    assert preview.series_count == 1
    assert preview.series[0].labels == labels
    assert preview.sample_count == 3
    assert any("replica" in warning for warning in preview.warnings)


def test_replica_with_more_samples_is_kept() -> None:
    labels = {"__name__": "up", "service": "checkout"}
    payload = _matrix(({**labels, "__replica__": "a"}, [1, 1]), ({**labels, "__replica__": "b"}, [2, 2, 2, 2]))

    preview = _service(payload).preview("up", START, END, "60s")

    assert preview.series_count == 1
    assert [sample.value for sample in preview.series[0].samples] == [2, 2, 2, 2]


def test_clusters_are_never_collapsed_as_replicas() -> None:
    payload = _matrix(
        ({"__name__": "up", "service": "checkout", "cluster": "eu", "prometheus_replica": "a"}, [1]),
        ({"__name__": "up", "service": "checkout", "cluster": "us", "prometheus_replica": "a"}, [1]),
    )

    preview = _service(payload).preview("up", START, END, "60s")

    assert sorted(series.labels["cluster"] for series in preview.series) == ["eu", "us"]


def test_replica_labels_are_configurable_and_can_be_turned_off() -> None:
    labels = {"__name__": "up", "service": "checkout"}
    payload = _matrix(({**labels, "replica": "0"}, [1]), ({**labels, "replica": "1"}, [1]))

    assert _service(payload).preview("up", START, END, "60s").series_count == 2
    assert _service(payload, replica_labels=["replica"]).preview("up", START, END, "60s").series_count == 1


def test_single_prometheus_without_replicas_is_unchanged() -> None:
    payload = _matrix(({"__name__": "up", "instance": "a"}, [1, 2]), ({"__name__": "up", "instance": "b"}, [3, 4]))

    preview = _service(payload).preview("up", START, END, "60s")

    assert preview.series_count == 2
    assert not preview.warnings


def test_cluster_and_replica_labels_come_from_env(monkeypatch) -> None:
    monkeypatch.setenv("OPS_SIGNALS_PROMETHEUS_CLUSTER_LABEL", "k8s_cluster")
    monkeypatch.setenv("OPS_SIGNALS_PROMETHEUS_REPLICA_LABELS", "replica, __replica__")

    config = get_prometheus_config()

    assert config.cluster_label == "k8s_cluster"
    assert config.replica_labels == ["replica", "__replica__"]


def test_cluster_label_defaults() -> None:
    config = PrometheusConnectionConfig()

    assert config.cluster_label == "cluster"
    assert config.replica_labels == ["__replica__", "prometheus_replica"]


# --- autonomous planning ------------------------------------------------------------------------


class FakeProvider:
    def __init__(self, metrics: list[DiscoveredMetric], config: PrometheusConnectionConfig | None = None):
        self.metrics = metrics
        self.config = config or PrometheusConnectionConfig(base_url="http://mimir.test")
        self.queries: list[str] = []

    def discover_metric_metadata(self, **kwargs):
        return list(self.metrics)

    def label_values(self, label: str, **kwargs):
        return sorted({metric.labels[label] for metric in self.metrics if label in metric.labels})

    def preview(self, query: str, start, end, step: str):
        self.queries.append(query)
        cluster = "us" if 'cluster="us"' in query else "eu"
        samples = [PrometheusSeriesSample(timestamp=start + (end - start) * (idx / 30), value=float(idx)) for idx in range(31)]
        return PrometheusPreviewOut(
            query=query,
            start=start,
            end=end,
            step=step,
            step_seconds=600,
            series_count=1,
            sample_count=len(samples),
            series=[PrometheusSeriesOut(labels={"service": "checkout", "cluster": cluster}, samples=samples)],
            warnings=[],
        )


def metric(name: str, cluster: str | None, **labels: str) -> DiscoveredMetric:
    metric_labels = {"__name__": name, "service": "checkout", "namespace": "commerce", "env": "production", **labels}
    if cluster:
        metric_labels["cluster"] = cluster
    return DiscoveredMetric(metric_name=name, labels=metric_labels, service="checkout", namespace="commerce", environment="production")


def build_plan(metrics: list[DiscoveredMetric], scope: AnalysisScope | None = None, config: PrometheusConnectionConfig | None = None):
    resolved, discovered = MetricDiscoveryService(FakeProvider(metrics, config)).discover(scope or AnalysisScope())
    return MetricPlanBuilder().build(
        resolved_scope=resolved,
        discovered_metrics=discovered,
        selected_categories=[MonitoringCategory.capacity],
        execution=ExecutionPolicy(max_metrics_per_run=500),
        custom_constraints=CustomMetricConstraints(),
        classifier=MetricClassificationService(),
    )


def test_same_service_in_two_clusters_plans_one_job_per_cluster() -> None:
    plan = build_plan([metric("container_memory_working_set_bytes", "eu"), metric("container_memory_working_set_bytes", "us")])

    planned = sorted((item for item in plan.items if item.planned), key=lambda item: item.cluster or "")
    assert [item.cluster for item in planned] == ["eu", "us"]
    assert 'cluster="eu"' in planned[0].promql
    assert 'cluster="us"' in planned[1].promql
    assert all(item.promql.startswith("avg by (service, cluster)") for item in planned)
    assert all("cluster" in item.group_by for item in planned)


def test_counter_in_two_clusters_is_summed_per_cluster() -> None:
    plan = build_plan([metric("container_cpu_usage_seconds_total", "eu"), metric("container_cpu_usage_seconds_total", "us")])

    planned = [item for item in plan.items if item.planned]
    assert len(planned) == 2
    assert all(" by (service, cluster) (rate(" in item.promql for item in planned)


def test_metrics_without_a_cluster_label_plan_exactly_as_before() -> None:
    plan = build_plan([metric("container_memory_working_set_bytes", None)])

    [item] = [item for item in plan.items if item.planned]
    assert item.cluster is None
    assert item.promql.startswith("avg by (service) (")
    assert "cluster" not in item.promql
    assert "without" not in item.promql


def test_replicated_series_are_deduped_inside_the_query() -> None:
    plan = build_plan([metric("container_cpu_usage_seconds_total", "eu", prometheus_replica="a")])

    [item] = [item for item in plan.items if item.planned]
    assert "max without (prometheus_replica) (rate(container_cpu_usage_seconds_total" in item.promql
    assert item.promql.startswith("sum by (service, cluster) (max without (prometheus_replica)") or item.promql.startswith(
        "avg by (service, cluster) (max without (prometheus_replica)"
    )


def test_replicated_histogram_dedups_buckets_before_summing() -> None:
    resolved, discovered = MetricDiscoveryService(
        FakeProvider([metric("http_request_duration_seconds_bucket", "eu", le="0.5", __replica__="r1")])
    ).discover(AnalysisScope())
    plan = MetricPlanBuilder().build(
        resolved_scope=resolved,
        discovered_metrics=discovered,
        selected_categories=[MonitoringCategory.performance],
        execution=ExecutionPolicy(max_metrics_per_run=500),
        custom_constraints=CustomMetricConstraints(),
        classifier=MetricClassificationService(),
    )

    [item] = [item for item in plan.items if item.planned]
    assert "sum by (le, service, cluster) (max without (__replica__) (rate(http_request_duration_seconds_bucket" in item.promql


def test_cluster_scope_filter_keeps_only_selected_clusters() -> None:
    plan = build_plan(
        [metric("container_memory_working_set_bytes", "eu"), metric("container_memory_working_set_bytes", "us")],
        AnalysisScope(all_clusters=False, clusters=["us"]),
    )

    planned = [item for item in plan.items if item.planned]
    assert [item.cluster for item in planned] == ["us"]
    assert plan.scope_summary["clusters_resolved"] == ["us"]


def test_cluster_label_comes_from_the_connection_and_scope_can_override_it() -> None:
    config = PrometheusConnectionConfig(base_url="http://mimir.test", cluster_label="k8s_cluster")
    metrics = [
        DiscoveredMetric(
            metric_name="container_memory_working_set_bytes",
            labels={"__name__": "container_memory_working_set_bytes", "service": "checkout", "k8s_cluster": name},
            service="checkout",
        )
        for name in ("eu", "us")
    ]

    from_connection = build_plan(metrics, config=config)
    overridden = build_plan(metrics, AnalysisScope(cluster_label="cluster"), config=config)

    assert sorted(item.cluster for item in from_connection.items if item.planned) == ["eu", "us"]
    assert all('k8s_cluster="' in item.promql for item in from_connection.items if item.planned)
    assert [item.cluster for item in overridden.items if item.planned] == [None]


def test_scope_options_list_clusters() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeProvider(
        [metric("container_memory_working_set_bytes", "eu"), metric("container_memory_working_set_bytes", "us")]
    )
    with TestClient(app) as client:
        response = client.get("/api/autonomous/scope-options")

    assert response.status_code == 200
    assert response.json()["clusters"] == ["eu", "us"]
    assert response.json()["cluster_label"] == "cluster"


class CapturingExecutor:
    frames: list = []
    metadata: list = []

    def __init__(self, config):
        self.config = config

    def execute_dataframe(self, dataframe, *, run_metadata=None, db=None, series_key=None):
        CapturingExecutor.frames.append(dataframe)
        CapturingExecutor.metadata.append(run_metadata or {})
        return type("Result", (), {"analysis_run_id": f"run-{len(CapturingExecutor.frames)}", "signal_count": 0, "findings_count": 0, "behavior_findings_count": 0})()


def test_run_once_sends_each_cluster_to_analysis_separately(monkeypatch) -> None:
    CapturingExecutor.frames = []
    CapturingExecutor.metadata = []
    monkeypatch.setattr(autonomous_execution, "MetricAnalysisExecutor", CapturingExecutor)
    provider = FakeProvider([metric("container_memory_working_set_bytes", "eu"), metric("container_memory_working_set_bytes", "us")])
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: provider
    with TestClient(app) as client:
        response = client.post(
            "/api/autonomous/run-once",
            json={
                "scope": {"all_services": True, "all_namespaces": True},
                "monitoring_categories": ["capacity"],
                "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
            },
        )

    assert response.status_code == 200
    assert response.json()["summary"]["jobs_completed"] == 2
    assert sorted(frame["cluster"].iloc[0] for frame in CapturingExecutor.frames) == ["eu", "us"]
