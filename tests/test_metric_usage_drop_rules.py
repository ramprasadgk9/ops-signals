from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import yaml

from backend.app.metric_usage.drop_rules import DropCheck, build_drop_config, compile_patterns, drop_check, name_pattern_matches

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


def _check(metric: str = "orders_cache_evictions_total", **overrides: object) -> DropCheck:
    values = {
        "metric": metric, "status": "unwatched", "recording_rule": False, "jobs": {"prod": {"orders": 10}}, "first_seen": None,
        "analyzed": False, "pattern_locations": [], "now": NOW, **overrides,
    }
    return drop_check(**values)


def test_an_old_unwatched_scraped_metric_can_be_dropped() -> None:
    assert _check() == DropCheck(None, ())
    assert _check(first_seen=NOW - timedelta(days=30)).blocked is None


def test_drop_is_not_offered_for_metrics_that_are_read_or_have_problems() -> None:
    assert "Add it to Grafana" in _check(status="blind_spot").blocked
    assert "reads it" in _check(status="watched").blocked
    assert "reads it" in _check(status="missing").blocked


def test_recording_rule_outputs_and_prometheus_made_metrics_are_not_dropped_by_scrape_rules() -> None:
    assert "recording rule" in _check(recording_rule=True).blocked
    for name in ("up", "scrape_duration_seconds", "scrape_series_added", "ALERTS", "ALERTS_FOR_STATE"):
        assert "Prometheus makes it" in _check(name).blocked


def test_new_metrics_wait_a_week() -> None:
    blocked = _check(first_seen=NOW - timedelta(days=2)).blocked
    assert blocked.startswith("First seen 2 days ago. Drop is offered in 5 days")
    assert "in 1 day," in _check(first_seen=NOW - timedelta(days=6, hours=20)).blocked
    assert _check(first_seen=NOW - timedelta(hours=3)).blocked.startswith("First seen today")
    # Stored without a time zone (SQLite): read as UTC.
    assert _check(first_seen=(NOW - timedelta(days=1)).replace(tzinfo=None)).blocked.startswith("First seen yesterday")


def test_an_unknown_scrape_job_blocks_drop() -> None:
    assert "scrape job" in _check(jobs={}).blocked
    assert "scrape job" in _check(jobs={"prod": {}}).blocked
    assert "scrape job" in _check(jobs={"prod": {"": 50}}).blocked


def test_series_without_a_job_label_are_called_out() -> None:
    check = _check(jobs={"prod": {"api": 900, "": 5000}})
    assert check.blocked is None
    assert check.warnings == ("5,000 of its 5,900 series have no job label (sent by remote write or OTLP?). A scrape rule won't drop those; drop them where they're sent from.",)


def test_analyzed_and_pattern_matched_metrics_can_be_dropped_with_warnings() -> None:
    check = _check(analyzed=True, pattern_locations=["Ops / Overview / All orders"])
    assert check.blocked is None
    assert check.warnings == (
        "Ops Signals analyzes this metric. Dropping it stops that analysis.",
        "A query reads metrics by a name pattern that matches it: Ops / Overview / All orders. Check it before dropping.",
    )


def test_name_patterns_are_anchored_and_bad_ones_are_skipped() -> None:
    patterns = compile_patterns([{"pattern": "orders_.*", "location": "A"}, {"pattern": "cache", "location": "B"}, {"pattern": "(", "location": "C"}])
    assert len(patterns) == 2
    assert name_pattern_matches("orders_cache_evictions_total", patterns) == ["A"]
    assert name_pattern_matches("cache", patterns) == ["B"]


def _item(metric: str, jobs: dict[str, dict[str, int]], check: DropCheck | None = None) -> dict:
    return {"metric": metric, "jobs": jobs, "check": check or DropCheck(None)}


def test_config_has_one_rule_per_scrape_job() -> None:
    config = build_drop_config(
        [
            _item("orders_cache_evictions_total", {"prod": {"orders": 8240}}),
            _item("grpc_client_msg_sent_total", {"prod": {"orders": 1000, "payments": 330}}),
            # Its 90 series with no job label aren't dropped by a scrape rule, so not counted.
            _item("http_server_request_size_bytes_bucket", {"prod": {"checkout": 5410, "": 90}}),
            _item("up", {"prod": {"orders": 3}}, DropCheck("Prometheus makes it itself, so a scrape rule can't drop it.")),
            _item("checkout_latency_seconds", {"prod": {"checkout": 2100}}, DropCheck(None, ("Ops Signals analyzes this metric.",))),
        ],
        connection_names={"prod": "Prometheus prod"},
        checked_on=NOW,
    )
    assert config.metrics == ["orders_cache_evictions_total", "grpc_client_msg_sent_total", "http_server_request_size_bytes_bucket", "checkout_latency_seconds"]
    assert config.series == 8240 + 1330 + 5410 + 2100
    assert config.skipped == [{"metric": "up", "reason": "Prometheus makes it itself, so a scrape rule can't drop it."}]
    assert config.warnings == ["checkout_latency_seconds: Ops Signals analyzes this metric."]
    [block] = config.blocks
    assert (block.connection, block.name) == ("prod", "Prometheus prod")
    assert "# Ops Signals: not used by any dashboard or rule (2026-10-23)" in block.yaml
    assert "prometheus-operator" in block.yaml  # the job label isn't always the job_name

    jobs = {job["job_name"]: job["metric_relabel_configs"] for job in yaml.safe_load(block.yaml)["scrape_configs"]}
    assert list(jobs) == ["checkout", "orders", "payments"]
    assert jobs["orders"] == [{"source_labels": ["__name__"], "regex": "grpc_client_msg_sent_total|orders_cache_evictions_total", "action": "drop"}]
    # The regex drops exactly the chosen names, as Prometheus anchors it.
    assert re.fullmatch(jobs["checkout"][0]["regex"], "checkout_latency_seconds")
    assert not re.fullmatch(jobs["checkout"][0]["regex"], "checkout_latency_seconds_extra")


def test_config_is_one_block_per_prometheus_each_valid_on_its_own() -> None:
    config = build_drop_config(
        [_item("a_total", {"team-b": {"web": 4}, "team-a": {"web": 6}})],
        connection_names={"team-a": "Mimir team-a", "team-b": "Mimir team-b"},
        checked_on=NOW,
    )
    assert config.series == 10
    assert [block.name for block in config.blocks] == ["Mimir team-a", "Mimir team-b"]
    for block in config.blocks:
        assert yaml.safe_load(block.yaml)["scrape_configs"][0]["job_name"] == "web"


def test_unusual_job_names_are_quoted_and_nothing_selected_gives_no_config() -> None:
    config = build_drop_config([_item("a_total", {"p": {"true": 1, "it's: odd": 1}})], connection_names={}, checked_on=NOW)
    names = [job["job_name"] for job in yaml.safe_load(config.blocks[0].yaml)["scrape_configs"]]
    assert names == ["it's: odd", "true"]
    empty = build_drop_config([_item("up", {"p": {"x": 1}}, check=DropCheck("no"))], connection_names={}, checked_on=NOW)
    assert (empty.blocks, empty.metrics, empty.series) == ([], [], None)
