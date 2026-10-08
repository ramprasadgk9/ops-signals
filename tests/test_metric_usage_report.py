from __future__ import annotations

from backend.app.metric_usage.report import build_report
from backend.app.metric_usage.sources import MetricUsage, UsageScan


def _scan(*usages: tuple[str, str], recording_rules: dict[str, frozenset[str]] | None = None) -> UsageScan:
    return UsageScan(
        usages=[MetricUsage(metric, kind, f"{kind} for {metric}") for metric, kind in usages],
        recording_rules=recording_rules or {},
    )


def _statuses(report) -> dict[str, str]:
    return {item.metric: item.status for item in report.items}


def test_each_metric_lands_in_one_group() -> None:
    report = build_report(
        {"default": ["request_latency_p95", "error_rate", "up", "disk_free_bytes", "debug_cache_hits"]},
        _scan(("request_latency_p95", "dashboard"), ("error_rate", "dashboard"), ("error_rate", "alert_rule"), ("up", "alert_rule"), ("gone_metric", "dashboard")),
        problems={"disk_free_bytes": (3, 42), "error_rate": (1, 7)},
        analyzed={"disk_free_bytes", "error_rate"},
    )
    assert _statuses(report) == {
        "disk_free_bytes": "blind_spot",
        "gone_metric": "missing",
        "error_rate": "watched",
        "request_latency_p95": "watched",
        "up": "watched",
        "debug_cache_hits": "unwatched",
    }
    # Blind spots first, then missing, watched, unwatched.
    assert [item.metric for item in report.items][:2] == ["disk_free_bytes", "gone_metric"]
    assert report.totals == {"metrics": 5, "watched": 3, "blind_spots": 1, "unwatched": 1, "missing": 1, "series_total": None, "series_unwatched": None}

    blind = report.items[0]
    assert (blind.problem_findings, blind.latest_finding_id, blind.analyzed) == (3, 42, True)
    error_rate = next(item for item in report.items if item.metric == "error_rate")
    assert {usage.kind for usage in error_rate.usages} == {"dashboard", "alert_rule"}
    assert error_rate.problem_findings == 1


def test_recording_rule_sources_are_watched_only_when_the_rule_output_is() -> None:
    scan = _scan(
        ("job:http:rate5m", "dashboard"),
        ("http_requests_total", "recording_rule"),
        ("queue_depth", "recording_rule"),
        recording_rules={
            "job:http:rate5m": frozenset({"http_requests_total"}),
            "job:queue:max": frozenset({"queue_depth"}),  # nothing reads this rule's output
        },
    )
    report = build_report({"default": ["job:http:rate5m", "job:queue:max", "http_requests_total", "queue_depth"]}, scan)
    statuses = _statuses(report)
    assert statuses["http_requests_total"] == "watched"
    assert statuses["queue_depth"] == "unwatched"
    assert statuses["job:queue:max"] == "unwatched"
    http = next(item for item in report.items if item.metric == "http_requests_total")
    assert http.via_recording_rules == ("job:http:rate5m",)


def test_recording_rules_chain() -> None:
    scan = _scan(("level2", "alert_rule"), recording_rules={"level2": frozenset({"level1"}), "level1": frozenset({"raw_total"})})
    assert _statuses(build_report({"default": ["level2", "level1", "raw_total"]}, scan))["raw_total"] == "watched"


def test_ignored_metrics_are_left_out_everywhere() -> None:
    report = build_report(
        {"default": ["go_goroutines", "prometheus_tsdb_head_series", "app_metric"]},
        _scan(("go_gc_duration_seconds", "dashboard")),
        ignore_metrics=["go_*", "prometheus_*"],
    )
    assert _statuses(report) == {"app_metric": "unwatched"}


def test_metric_in_several_connections_is_one_row() -> None:
    report = build_report({"eu": ["cpu_usage"], "us": ["cpu_usage", "mem"]}, _scan(("cpu_usage", "dashboard")))
    cpu = next(item for item in report.items if item.metric == "cpu_usage")
    assert cpu.connections == ("eu", "us")
    assert report.totals["metrics"] == 2


def test_series_counts_add_up_across_connections_and_unused_ones_are_totalled() -> None:
    report = build_report(
        {"eu": ["cpu_usage", "debug_cache_hits"], "us": ["cpu_usage", "debug_cache_hits", "disk_free_bytes"]},
        _scan(("cpu_usage", "dashboard")),
        problems={"disk_free_bytes": (2, 9)},
        series_by_connection={"eu": {"cpu_usage": 10, "debug_cache_hits": 3000}, "us": {"cpu_usage": 12, "debug_cache_hits": 1000, "disk_free_bytes": 50}},
    )
    series = {item.metric: item.series for item in report.items}
    assert series == {"cpu_usage": 22, "debug_cache_hits": 4000, "disk_free_bytes": 50}
    # Blind spots and unwatched metrics are both unused storage.
    assert report.totals["series_total"] == 4072
    assert report.totals["series_unwatched"] == 4050


def test_unwatched_metrics_with_the_most_series_come_first() -> None:
    report = build_report(
        {"default": ["small", "big", "medium"]},
        _scan(),
        series_by_connection={"default": {"small": 1, "big": 900, "medium": 40}},
    )
    assert [item.metric for item in report.items] == ["big", "medium", "small"]


def test_without_series_counts_the_totals_say_so() -> None:
    report = build_report({"default": ["a"]}, _scan())
    assert report.items[0].series is None
    assert report.totals["series_total"] is None
    assert report.totals["series_unwatched"] is None


def test_a_connection_without_series_counts_leaves_its_metrics_partial() -> None:
    report = build_report({"eu": ["a"], "us": ["a", "b"]}, _scan(), series_by_connection={"eu": {"a": 5}})
    assert {item.metric: item.series for item in report.items} == {"a": 5, "b": None}
    assert report.totals["series_total"] == 5


def test_a_panel_counts_only_on_the_connections_its_datasource_reads() -> None:
    team_b = frozenset({"team-b"})
    scan = UsageScan(usages=[
        MetricUsage("billing_errors", "dashboard", "Team B / Billing / Errors", connections=team_b),
        MetricUsage("checkout_errors", "dashboard", "Team B / Billing / Checkout", connections=team_b),
        MetricUsage("checkout_latency", "alert_rule", "Team B / Checkout slow", connections=team_b),
        MetricUsage("cart_size", "dashboard", "Shared / Cart", connections=None),
    ])
    report = build_report(
        {"team-a": ["checkout_errors", "checkout_latency", "cart_size"], "team-b": ["billing_errors"]},
        scan,
        problems={"checkout_errors": (2, 5)},
    )
    assert _statuses(report) == {
        "billing_errors": "watched",
        # Only team-a has it, and team-b's panel can't show it: problems nobody sees come first...
        "checkout_errors": "blind_spot",
        # ...otherwise the team-b alert reads a metric its tenant doesn't have.
        "checkout_latency": "missing",
        # A datasource that could be any connection (a variable, or unknown) watches it wherever it is.
        "cart_size": "watched",
    }


def test_a_rule_from_one_tenant_does_not_watch_another_tenants_metric() -> None:
    scan = UsageScan(usages=[MetricUsage("errors_total", "alert_rule", "api / High", connections=frozenset({"team-a"}))])
    report = build_report({"team-a": [], "team-b": ["errors_total"]}, scan)
    assert _statuses(report) == {"errors_total": "missing"}
