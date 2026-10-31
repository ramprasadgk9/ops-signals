from datetime import datetime, timedelta, timezone

import pytest

from backend.app.config import DEFAULT_SPLIT_LABELS

from backend.app.models.prometheus import PrometheusSeriesOut, PrometheusSeriesSample
from backend.app.services.pod_split import find_pod_split, odd_series, suggested_combine

START = datetime(2026, 10, 30, 8, tzinfo=timezone.utc)
PODS = ["search-svc-0", "search-svc-1", "search-svc-2", "search-svc-3"]


def _pod_series(values_for, pods=PODS, extra=None, points=60) -> list[PrometheusSeriesOut]:
    return [
        PrometheusSeriesOut(
            labels={"__name__": "request_latency_p95", "service": "search-svc", "job": "demo", "pod": pod, **(extra(pod) if extra else {})},
            samples=[PrometheusSeriesSample(timestamp=START + timedelta(minutes=i), value=values_for(pod, i)) for i in range(points)],
        )
        for pod in pods
    ]


def _flapping(pod: str, i: int) -> float:
    """search-svc-2 above a second for 1 minute in every 5 after minute 30, like the demo."""
    if pod == "search-svc-2" and i >= 30 and (i - 30) % 5 == 0:
        return 1150.0
    return 90.0 + (i % 3) + PODS.index(pod)


def test_per_pod_series_get_combined_queries_that_keep_the_shared_labels() -> None:
    split = find_pod_split('request_latency_p95{service="search-svc"}', _pod_series(_flapping), metric="request_latency_p95", split_labels=["pod", "instance"], cluster_label="cluster")

    assert split is not None
    assert split.label == "pod"
    assert split.queries["max"] == 'max by (job, service) (request_latency_p95{service="search-svc"})'
    assert split.queries["sum"].startswith("sum by (job, service) (")
    assert split.one_queries["search-svc-2"] == 'request_latency_p95{service="search-svc",pod="search-svc-2"}'


def test_the_odd_pod_is_named_and_listed_first() -> None:
    split = find_pod_split('request_latency_p95{service="search-svc"}', _pod_series(_flapping), metric="request_latency_p95", split_labels=["pod"], cluster_label=None)

    assert split.values[0] == "search-svc-2"
    assert split.odd is not None
    assert split.odd.value == "search-svc-2"
    assert split.odd.message.startswith("search-svc-2 is behaving differently from the other 3 pods: it reaches 1,150 while the others stay near")


def test_a_pod_bad_for_part_of_the_window_is_named_with_its_peak() -> None:
    """Bad only in the last 10 of 120 minutes: a percentile of its values would look normal."""
    series = _pod_series(lambda pod, i: 2000.0 if pod == "search-svc-2" and i >= 110 and i % 2 == 0 else 90.0 + PODS.index(pod), points=120)

    odd = odd_series(series, "pod")

    assert odd is not None and "it reaches 2,000 while the others stay near" in odd.message


def test_a_pod_that_drops_is_named_with_its_low() -> None:
    series = _pod_series(lambda pod, i: 5.0 if pod == "search-svc-1" and i >= 30 else 90.0 + (i % 2), points=60)

    odd = odd_series(series, "pod")

    assert odd is not None and odd.value == "search-svc-1" and "it drops to 5 while the others stay near" in odd.message


def test_pods_that_agree_have_no_odd_one_out() -> None:
    series = _pod_series(lambda pod, i: 90.0 + (i % 4) + PODS.index(pod))

    assert odd_series(series, "pod") is None


def test_two_pods_cannot_tell_which_one_is_odd() -> None:
    series = _pod_series(_flapping, pods=["search-svc-1", "search-svc-2"])

    assert odd_series(series, "pod") is None


def test_series_that_also_differ_by_another_label_are_not_combined() -> None:
    """Two status codes per pod: combining would mix the status codes too, so keep the error."""
    series = [
        *_pod_series(_flapping, extra=lambda pod: {"code": "200"}),
        *_pod_series(_flapping, extra=lambda pod: {"code": "500"}),
    ]

    assert find_pod_split("request_latency_p95", series, metric=None, split_labels=["pod"], cluster_label=None) is None


def test_several_clusters_keep_the_cluster_choice() -> None:
    series = _pod_series(_flapping, extra=lambda pod: {"cluster": "eu" if pod < "search-svc-2" else "us"})

    assert find_pod_split("request_latency_p95", series, metric=None, split_labels=["pod"], cluster_label="cluster") is None


def test_instance_is_used_when_there_is_no_pod_label() -> None:
    series = [
        PrometheusSeriesOut(labels={"__name__": "up", "job": "node", "instance": name}, samples=[PrometheusSeriesSample(timestamp=START, value=1.0)])
        for name in ("a:9100", "b:9100")
    ]

    split = find_pod_split("up", series, metric=None, split_labels=["pod", "instance"], cluster_label=None)

    assert split.label == "instance"
    assert split.suggested_combine == "min"


@pytest.mark.parametrize("label", ["pod_name", "kubernetes_pod_name", "host"])
def test_pods_under_other_collectors_label_names_are_combined_by_default(label) -> None:
    series = [
        PrometheusSeriesOut(labels={"__name__": "request_latency_p95", "service": "checkout", label: name}, samples=[PrometheusSeriesSample(timestamp=START, value=90.0)])
        for name in ("a", "b", "c")
    ]

    split = find_pod_split('request_latency_p95{service="checkout"}', series, metric=None, split_labels=list(DEFAULT_SPLIT_LABELS), cluster_label="cluster")

    assert split is not None and split.label == label
    assert split.queries["avg"] == 'avg by (service) (request_latency_p95{service="checkout"})'


def test_hand_written_promql_is_wrapped_but_gets_no_one_pod_query() -> None:
    query = 'histogram_quantile(0.95, sum by (le, pod) (rate(http_request_duration_seconds_bucket{service="search-svc"}[5m])))'
    series = [
        PrometheusSeriesOut(labels={"pod": pod}, samples=[PrometheusSeriesSample(timestamp=START, value=0.1)])
        for pod in PODS
    ]

    split = find_pod_split(query, series, metric=None, split_labels=["pod"], cluster_label=None)

    assert split.queries["max"] == f"max by () ({query})"
    assert split.one_queries == {}


def test_combine_choice_matches_what_scheduled_runs_use() -> None:
    assert suggested_combine("request_latency_p95") == "avg"
    assert suggested_combine("http_requests_total") == "sum"
    assert suggested_combine("up") == "min"
    assert suggested_combine("kafka_consumergroup_lag") == "max"
    assert suggested_combine("something_unknown") == "avg"
    assert suggested_combine(None) == "avg"


def test_unknown_metrics_that_count_things_add_their_pods_up() -> None:
    # No rule knows them (scheduled runs don't watch them); the name says each pod counts its share.
    assert suggested_combine("http_requests_per_second") == "sum"
    assert suggested_combine("jobs_processed_count") == "sum"
    assert suggested_combine("orders_rps") == "sum"
    # A known rule still wins: error_rate is a ratio, averaged.
    assert suggested_combine("error_rate") == "avg"
    assert suggested_combine("queue_depth") == "avg"


def test_pods_are_told_apart_from_labels_alone() -> None:
    # More pods than are read as samples: only their labels are known.
    series = [PrometheusSeriesOut(labels={"service": "search-svc", "pod": f"search-svc-{i}"}, samples=[]) for i in range(30)]

    split = find_pod_split('request_latency_p95{service="search-svc"}', series, metric="request_latency_p95", split_labels=DEFAULT_SPLIT_LABELS, cluster_label=None)

    assert split is not None
    assert len(split.values) == 30
    assert split.odd is None
    assert split.queries["avg"] == 'avg by (service) (request_latency_p95{service="search-svc"})'
