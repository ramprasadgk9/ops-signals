"""Recording rules of a Prometheus connection: the queries Prometheus runs on a schedule and saves
under a new metric name. New Analysis marks those names in its Metrics list and shows the saved
query, so a name like `service:error_rate:percent` says what it measures."""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping

from fastapi import HTTPException

from backend.app.metric_usage.promql_metrics import extract_query_metrics
from backend.app.models.prometheus import RecordingRuleAlertOut, RecordingRuleOut, RecordingRulesOut
from backend.app.services.alert_rules import AlertRule, alert_labels, alert_rules, alert_text
from backend.app.services.finding_plain import Wording, duration_words, format_value, load_wording, metric_meaning
from backend.app.services.prometheus_service import PrometheusQueryService

# Rules change when someone edits a rules file, not between two clicks in the Metrics list.
CACHE_SECONDS = 60
_HEALTH = {"ok", "err", "unknown"}

_cache: dict[str, tuple[float, RecordingRulesOut]] = {}
_lock = threading.Lock()


def parse_recording_rules(payload: Mapping) -> list[RecordingRuleOut]:
    """The recording rules in a GET /api/v1/rules response. Alerting rules are skipped, so a server
    that ignores `type=record` gives the same list."""
    rules: list[RecordingRuleOut] = []
    data = payload.get("data") if isinstance(payload, Mapping) else None
    groups = data.get("groups") if isinstance(data, Mapping) else None
    for group in groups if isinstance(groups, list) else []:
        if not isinstance(group, Mapping):
            continue
        for rule in group.get("rules") or []:
            if not isinstance(rule, Mapping) or rule.get("type") != "recording":
                continue
            name, query = rule.get("name"), rule.get("query")
            if not isinstance(name, str) or not name or not isinstance(query, str) or not query:
                continue
            health = str(rule.get("health") or "unknown")
            interval = group.get("interval")
            rules.append(
                RecordingRuleOut(
                    name=name,
                    query=query,
                    group=str(group.get("name") or ""),
                    interval_seconds=float(interval) if isinstance(interval, (int, float)) and interval > 0 else None,
                    # "unknown" also covers a rule Prometheus hasn't run yet.
                    health=health if health in _HEALTH else "unknown",
                    last_error=rule.get("lastError") or None,
                    source_metrics=sorted(extract_query_metrics(query).names - {name}),
                )
            )
    return rules


def _fires(rule: AlertRule, wording: Wording | None) -> str | None:
    threshold = rule.threshold
    if threshold is None:
        return None
    unit = metric_meaning(threshold.metric, wording).unit if wording else None
    limit = format_value(threshold.limit, unit) or str(threshold.limit)
    return f"{'above' if threshold.keep == 'below' else 'below'} {limit}"


def with_alerts(rules: list[RecordingRuleOut], alerts: list[AlertRule]) -> list[RecordingRuleOut]:
    """Each rule with the alerts whose query reads it. Their text is filled only from what the
    alert's own query pins: no service is known yet in New Analysis."""
    wording = load_wording()
    for rule in rules:
        rule.alerts = [
            RecordingRuleAlertOut(
                name=alert.name,
                group=alert.group,
                text=alert_text(alert, alert_labels(alert, rule.name, None, ())),
                fires=_fires(alert, wording) if alert.threshold and alert.threshold.metric == rule.name else None,
                wait=duration_words(alert.wait_seconds / 60) if alert.wait_seconds else None,
                runbook_url=alert.runbook_url,
            )
            for alert in alerts
            if rule.name in alert.metrics
        ]
    return rules


def recording_rules(service: PrometheusQueryService) -> RecordingRulesOut:
    """The connection's recording rules, cached a minute. A server without a rules API (or a Mimir
    tenant without a ruler) gives an empty list and a message, not an error: the Metrics list still works."""
    connection_id = service.config.id
    now = time.monotonic()
    with _lock:
        cached = _cache.get(connection_id)
        if cached and now - cached[0] < CACHE_SECONDS:
            return cached[1]
    try:
        rules = parse_recording_rules(service.rules("record"))
        result = RecordingRulesOut(connection_id=connection_id, rules=with_alerts(rules, alert_rules(service)) if rules else rules)
    except HTTPException as exc:
        if exc.status_code == 400:
            raise
        # Not cached: a timeout shouldn't hide the rules for a minute.
        return RecordingRulesOut(connection_id=connection_id, rules=[], message=f"Couldn't read recording rules: {exc.detail}")
    with _lock:
        _cache[connection_id] = (now, result)
    return result


def clear_cache() -> None:
    with _lock:
        _cache.clear()
