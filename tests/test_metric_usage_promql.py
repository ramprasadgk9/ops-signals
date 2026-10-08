from __future__ import annotations

import pytest

from backend.app.metric_usage.promql_metrics import extract_query_metrics


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ('avg by (service) (request_latency_p95{env="local"})', {"request_latency_p95"}),
        ("histogram_quantile(0.95, sum by (le) (rate(prometheus_http_request_duration_seconds_bucket[5m])))", {"prometheus_http_request_duration_seconds_bucket"}),
        (
            "sum(rate(prometheus_tsdb_head_samples_appended_total[5m])) / on() group_left() sum(prometheus_tsdb_head_series)",
            {"prometheus_tsdb_head_samples_appended_total", "prometheus_tsdb_head_series"},
        ),
        ("job:http_requests:rate5m", {"job:http_requests:rate5m"}),
        ('{__name__="ops_signal_lab_value", profile="seasonal"}', {"ops_signal_lab_value"}),
        ('count({__name__=~"cpu_usage|error_rate"})', {"cpu_usage", "error_rate"}),
        ('{__name__!="up"}', set()),  # a negative matcher names nothing as used
        ("rate(x_total[$__rate_interval])", {"x_total"}),  # Grafana built-in variable
        ("increase(x_total[$__range]) / $__range_s", {"x_total"}),
        ('label_replace(up, "dst", "$1", "src", "(.*)")', {"up"}),  # $1 inside a string is not a variable
        ("", set()),
    ],
)
def test_extracts_metric_names(expr: str, expected: set[str]) -> None:
    result = extract_query_metrics(expr)
    assert result.names == expected
    assert result.unresolved_variables == frozenset()


def test_label_variables_are_not_metrics() -> None:
    result = extract_query_metrics('error_rate{service=~"$service"}', {"service": ["checkout", "payments"]})
    assert result.names == {"error_rate"}
    assert result.unresolved_variables == frozenset()


@pytest.mark.parametrize("expr", ['$metric{service="checkout"}', "rate(${metric}[5m])", "[[metric]]", '{__name__="$metric"}'])
def test_metric_variable_expands_to_every_option(expr: str) -> None:
    result = extract_query_metrics(expr, {"metric": ["cpu_usage", "request_latency_p95"]})
    assert result.names == {"cpu_usage", "request_latency_p95"}
    assert result.unresolved_variables == frozenset()


def test_metric_variable_without_known_options_is_reported_unresolved() -> None:
    result = extract_query_metrics('$metric{service="checkout"} + up')
    assert result.names == {"up"}
    assert result.unresolved_variables == {"metric"}


def test_numeric_variable_is_not_a_metric() -> None:
    result = extract_query_metrics("topk($k, rate(x_total[5m]))", {"k": ["5", "10"]})
    assert result.names == {"x_total"}
    assert result.unresolved_variables == frozenset()


def test_name_regex_that_is_not_a_plain_list_is_kept_as_a_pattern() -> None:
    result = extract_query_metrics('sum({__name__=~"node_.*_bytes"})')
    assert result.names == frozenset()
    assert result.name_patterns == {"node_.*_bytes"}


def test_two_variables_each_expand() -> None:
    result = extract_query_metrics("$a / $b", {"a": ["x", "y"], "b": ["z"]})
    assert result.names == {"x", "y", "z"}
