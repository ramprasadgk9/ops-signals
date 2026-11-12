"""Alerting rules of a Prometheus connection, read so a finding can borrow what the team wrote about
its metric: the alert's description, its runbook and the line it fires at.

A recording rule such as `service:error_rate:percent` has no description, but the alert built on
it usually has (`service:error_rate:percent{service="checkout"} > 5`, summary, description,
runbook_url). The same lookup works for a raw metric an alert uses. Nothing is stored: findings
read the rules when they are shown, through a short cache, and without an alert they read as before.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.alerts.query_builder import metric_names
from backend.app.config import PrometheusConnectionConfig, PrometheusConnectionsError, get_prometheus_connections
from backend.app.models.entities import AnalysisRunEntity, FindingEntity
from backend.app.services.prometheus_service import PrometheusQueryService

logger = logging.getLogger(__name__)

# Rules change when someone edits a rules file. A failed read is remembered for less time, but it
# is remembered: a Findings page shouldn't wait on an unreachable ruler at every load.
CACHE_SECONDS = 60
FAILURE_CACHE_SECONDS = 30
# The Findings page waits at most this long for a connection's rules; slower means no alert context.
LOOKUP_TIMEOUT_SECONDS = 2.0
# Alert text shown on a finding is clipped to this many characters.
TEXT_MAX = 300

_cache: dict[str, tuple[float, float, list["AlertRule"]]] = {}
_lock = threading.Lock()

_NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_NAME = r"[a-zA-Z_:][a-zA-Z0-9_:]*"
_SELECTOR = rf"({_NAME})\s*(\{{[^}}]*\}})?"
# `rule > 5` and `5 < rule`: the only alert queries whose line is a plain number. `bool` turns a
# comparison into 0/1 and isn't a line, so it isn't matched.
_METRIC_FIRST = re.compile(rf"^\s*{_SELECTOR}\s*(>=|<=|>|<)\s*({_NUMBER})\s*$")
_NUMBER_FIRST = re.compile(rf"^\s*({_NUMBER})\s*(>=|<=|>|<)\s*{_SELECTOR}\s*$")
_FLIP = {">": "<", "<": ">", ">=": "<=", "<=": ">="}
_MATCHER = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)\s*(=~|!~|!=|=)\s*"((?:\\.|[^"\\])*)"')
_LABEL_TEMPLATE = re.compile(r"\{\{-?\s*(?:\$labels|\.Labels)\.([a-zA-Z_][a-zA-Z0-9_]*)\s*-?\}\}")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Matcher:
    label: str
    op: str
    value: str

    def matches(self, actual: str | None) -> bool | None:
        """Whether a series with this label value is selected; None when the regex can't be read."""
        actual = actual or ""
        if self.op == "=":
            return actual == self.value
        if self.op == "!=":
            return actual != self.value
        try:
            found = re.fullmatch(self.value, actual) is not None
        except re.error:
            return None
        return found if self.op == "=~" else not found


@dataclass(frozen=True)
class Threshold:
    metric: str
    # The comparison with the metric on the left: `>` for `rule > 5` and for `5 < rule`.
    op: str
    limit: float

    @property
    def keep(self) -> str:
        """Which side of the line is fine, in finding_plain.Target terms."""
        return "below" if self.op in {">", ">="} else "above"


@dataclass(frozen=True)
class AlertRule:
    name: str
    group: str
    expr: str
    metrics: tuple[str, ...]
    # The label matchers on each metric's first selector in the query.
    matchers: Mapping[str, tuple[Matcher, ...]]
    threshold: Threshold | None
    # How long the condition must hold before the alert fires (the rule's `for`), in seconds.
    wait_seconds: float | None
    summary: str | None
    description: str | None
    runbook_url: str | None


def _blank_quoted(expr: str) -> str:
    """The query with every quoted string's content blanked, same length, so a name or a brace
    inside a label value is never taken for part of the query."""
    return re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`[^`]*`', lambda match: match.group(0)[0] + " " * (len(match.group(0)) - 2) + match.group(0)[-1], expr)


def _selector_matchers(expr: str, metrics: Iterable[str]) -> dict[str, tuple[Matcher, ...]]:
    """The matchers in `metric{...}` for each metric's first appearance; none for a bare name."""
    blanked = _blank_quoted(expr)
    found: dict[str, tuple[Matcher, ...]] = {}
    for metric in metrics:
        match = re.search(rf"(?<![a-zA-Z0-9_:]){re.escape(metric)}(?![a-zA-Z0-9_:])\s*(\{{[^}}]*\}})?", blanked)
        braces = expr[match.start(1) : match.end(1)] if match and match.group(1) else ""
        found[metric] = tuple(Matcher(label, op, value.replace('\\"', '"')) for label, op, value in _MATCHER.findall(braces))
    return found


def parse_threshold(expr: str) -> Threshold | None:
    """The line of a `metric OP number` alert; None for any other query (it still gives its text)."""
    match = _METRIC_FIRST.match(expr)
    if match:
        metric, _, op, number = match.groups()
        return Threshold(metric, op, float(number))
    match = _NUMBER_FIRST.match(expr)
    if match:
        number, op, metric, _ = match.groups()
        return Threshold(metric, _FLIP[op], float(number))
    return None


def safe_runbook_url(url: object) -> str | None:
    """An http(s) runbook link, or None. Annotations are free text; only a web link is shown."""
    if not isinstance(url, str):
        return None
    url = url.strip()
    if not url or any(char.isspace() for char in url) or "{{" in url:
        return None
    parts = urlsplit(url)
    return url if parts.scheme in {"http", "https"} and parts.netloc else None


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def parse_alert_rules(payload: Mapping) -> list[AlertRule]:
    """The alerting rules in a GET /api/v1/rules response. Recording rules are skipped, so a server
    that ignores `type=alert` gives the same list."""
    rules: list[AlertRule] = []
    data = payload.get("data") if isinstance(payload, Mapping) else None
    groups = data.get("groups") if isinstance(data, Mapping) else None
    for group in groups if isinstance(groups, list) else []:
        if not isinstance(group, Mapping):
            continue
        for rule in group.get("rules") or []:
            if not isinstance(rule, Mapping) or rule.get("type") != "alerting":
                continue
            name, expr = rule.get("name"), rule.get("query")
            if not isinstance(name, str) or not name or not isinstance(expr, str) or not expr:
                continue
            metrics = tuple(metric_names(expr))
            if not metrics:
                continue
            annotations = rule.get("annotations") if isinstance(rule.get("annotations"), Mapping) else {}
            wait = rule.get("duration")
            rules.append(
                AlertRule(
                    name=name,
                    group=str(group.get("name") or ""),
                    expr=expr,
                    metrics=metrics,
                    matchers=_selector_matchers(expr, metrics),
                    threshold=parse_threshold(expr),
                    wait_seconds=float(wait) if isinstance(wait, (int, float)) and wait > 0 else None,
                    summary=_text(annotations.get("summary")),
                    description=_text(annotations.get("description")),
                    runbook_url=safe_runbook_url(annotations.get("runbook_url")),
                )
            )
    return rules


def alert_rules(service: PrometheusQueryService) -> list[AlertRule]:
    """The connection's alerting rules, cached. A server without a rules API, a ruler that doesn't
    answer or a timeout gives an empty list: alert context is extra, never a reason to fail."""
    connection_id = service.config.id
    now = time.monotonic()
    with _lock:
        cached = _cache.get(connection_id)
        if cached and now - cached[0] < cached[1]:
            return cached[2]
    try:
        rules, keep = parse_alert_rules(service.rules("alert")), CACHE_SECONDS
    except HTTPException as exc:
        logger.info("alert_rules: couldn't read alerting rules of %s (%s)", connection_id, exc.detail)
        rules, keep = [], FAILURE_CACHE_SECONDS
    with _lock:
        _cache[connection_id] = (now, keep, rules)
    return rules


def clear_cache() -> None:
    with _lock:
        _cache.clear()


# ---------------------------------------------------------------------------------------------
# Which alerts speak for a finding


def _applies(rule: AlertRule, metric: str, service: str | None, service_labels: Sequence[str]) -> tuple[bool, bool]:
    """(applies to this metric and service, names the service). An alert without a matcher on a
    service label covers every service; one with a matcher covers the services it selects."""
    service_matchers = [matcher for matcher in rule.matchers.get(metric, ()) if matcher.label in service_labels]
    if not service_matchers:
        return True, False
    if not service:
        return False, True
    return all(matcher.matches(service) is True for matcher in service_matchers), True


def matching_alerts(rules: Iterable[AlertRule], metric: str | None, service: str | None, service_labels: Sequence[str]) -> list[AlertRule]:
    """The alerts whose query reads `metric` for `service`. When some name the service, only those
    are kept: the service's own team wrote them. In rules order otherwise."""
    if not metric:
        return []
    service = service if service and service.lower() != "unknown" else None
    specific: list[AlertRule] = []
    generic: list[AlertRule] = []
    for rule in rules:
        if metric not in rule.metrics:
            continue
        applies, named = _applies(rule, metric, service, service_labels)
        if applies:
            (specific if named else generic).append(rule)
    return specific or generic


def alert_text(rule: AlertRule, labels: Mapping[str, str]) -> str | None:
    """The alert's description as written: what the team says the problem means. Never the
    summary, which is a title that usually restates the condition ("p95 latency above 300ms") and
    would push out a better Why it matters; see alert_summary."""
    return _filled(rule.description, labels)


def alert_summary(rule: AlertRule, labels: Mapping[str, str]) -> str | None:
    """The alert's summary, filled the same way, for the tooltip that names the alert."""
    return _filled(rule.summary, labels)


def _filled(raw: str | None, labels: Mapping[str, str]) -> str | None:
    """`raw` with `{{ $labels.x }}` filled in from `labels`. A sentence still holding a template
    (`{{ $value }}`, an unknown label) is left out: the finding can't know the value the alert
    would have shown."""
    if not raw:
        return None
    filled = _LABEL_TEMPLATE.sub(lambda match: labels.get(match.group(1), match.group(0)), raw)
    sentences = [sentence for sentence in _SENTENCE_END.split(" ".join(filled.split())) if sentence and "{{" not in sentence]
    text = " ".join(sentences).strip()
    if not text:
        return None
    return text if len(text) <= TEXT_MAX else text[: TEXT_MAX - 1].rstrip() + "…"


def alert_labels(rule: AlertRule, metric: str, service: str | None, service_labels: Sequence[str]) -> dict[str, str]:
    """The label values a finding knows for this alert's templates: its service under each service
    label, and what the alert's own query pins with `=`."""
    labels = {matcher.label: matcher.value for matcher in rule.matchers.get(metric, ()) if matcher.op == "="}
    if service and service.lower() != "unknown":
        labels.update({label: service for label in service_labels if label not in labels})
    return labels


# ---------------------------------------------------------------------------------------------
# Lookup for findings read from the database


def _connection_rules(connection: PrometheusConnectionConfig) -> list[AlertRule]:
    """The rules of one connection, asked with a short timeout. tests/conftest.py replaces this so
    no test reads a real Prometheus."""
    if not connection.base_url:
        return []
    quick = connection.model_copy(update={"timeout_seconds": min(connection.timeout_seconds, LOOKUP_TIMEOUT_SECONDS)})
    return alert_rules(PrometheusQueryService(quick))


def alerts_for_findings(db: Session, rows: Sequence[FindingEntity], service_labels: Sequence[str]) -> dict[int, list[AlertRule]]:
    """The alerts that speak for each finding, by finding id. Only findings from a Prometheus run
    have a connection to ask; OTLP and CSV findings get none."""
    run_ids = {row.analysis_run_id for row in rows if row.analysis_run_id}
    if not run_ids:
        return {}
    runs = dict(
        db.execute(
            select(AnalysisRunEntity.id, AnalysisRunEntity.connection_id).where(AnalysisRunEntity.id.in_(run_ids), AnalysisRunEntity.connection_id.is_not(None))
        ).all()
    )
    if not runs:
        return {}
    try:
        connections = get_prometheus_connections()
    except PrometheusConnectionsError:
        return {}
    rules_by_connection: dict[str, list[AlertRule]] = {}
    for connection_id in set(runs.values()):
        connection = connections.get(connection_id)
        rules_by_connection[connection_id] = _connection_rules(connection) if connection is not None else []
    found: dict[int, list[AlertRule]] = {}
    for row in rows:
        connection_id = runs.get(row.analysis_run_id)
        if row.id is None or connection_id is None:
            continue
        matched = matching_alerts(rules_by_connection.get(connection_id, ()), row.metric_name, row.service, service_labels)
        if matched:
            found[row.id] = matched
    return found
