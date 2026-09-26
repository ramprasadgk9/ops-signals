"""Decide whether an alert's series is worth running the analyzers on.

Every accepted alert is still enriched and (if configured) posted - this only gates the "What
happened" analysis. Rules are evaluated in order; the first match wins (docs/design/alert-enrichment-plan.md §C).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.app.alerts.query_builder import metric_names, strip_threshold
from backend.app.alerts.schemas import NormalizedAlert

_LOGQL = re.compile(
    r"\|=|\|~|!=\s*[\"`]|!~\s*[\"`]|\|\s*(json|logfmt|pattern|regexp|line_format|label_format|unpack|decolorize)\b"
)
_ABSENCE = re.compile(r"\babsent(_over_time)?\s*\(")
_STATUS_METRIC = re.compile(
    r"^(up|ALERTS|ALERTS_FOR_STATE|kube_.*_status_.*|kube_.*_(ready|phase|condition)|.*_restarts_total)$"
)

REASON_TEXT = {
    "disabled_by_annotation": "analysis disabled for this rule (ops_signals_analyze=false)",
    "no_prometheus": "no Prometheus connection configured",
    "no_query": "could not derive a PromQL query from this alert (add an ops_signals_query annotation)",
    "log_alert": "log-based alert (LogQL) - metric analysis doesn't apply",
    "absence_alert": "absence alert - there is no series to analyze",
    "status_alert": "status/health alert - a 0/1 series has no shape to analyze",
    "too_many_series": "the query returned too many series (add a narrower ops_signals_query)",
    "ambiguous_series": "could not match the alert to a single series (add a narrower ops_signals_query)",
    "no_data": "Prometheus returned no data for this series",
    "insufficient_data": "too few data points to analyze",
    "binary_series": "the series only takes 1-2 distinct values",
    "prometheus_unreachable": "Prometheus could not be reached",
    "query_failed": "the Prometheus query failed",
    "analysis_failed": "the analysis pipeline failed",
}


@dataclass(frozen=True)
class AnalysisDecision:
    analyze: bool
    reason: str | None = None
    query: str | None = None
    metric_key: str | None = None


def resolve_metric_key(alert: NormalizedAlert, query: str | None) -> str:
    """Stable per-alert metric name used for history lookups and finding reuse."""
    explicit = (alert.annotations.get("ops_signals_metric") or "").strip()
    if explicit:
        return explicit
    for candidate in (query, alert.expr):
        if candidate:
            names = metric_names(candidate)
            if names:
                return names[0]
    return alert.alert_name


def classify(alert: NormalizedAlert, prometheus_configured: bool) -> AnalysisDecision:
    annotation = (alert.annotations.get("ops_signals_analyze") or "").strip().lower()
    forced = annotation == "true"
    explicit_query = (alert.annotations.get("ops_signals_query") or "").strip() or None

    if annotation == "false":
        return AnalysisDecision(False, "disabled_by_annotation", metric_key=resolve_metric_key(alert, explicit_query))
    if not prometheus_configured:
        return AnalysisDecision(False, "no_prometheus", metric_key=resolve_metric_key(alert, explicit_query))

    raw_expr = explicit_query or alert.expr
    if not raw_expr:
        return AnalysisDecision(False, "no_query", metric_key=resolve_metric_key(alert, None))
    if _LOGQL.search(raw_expr):
        return AnalysisDecision(False, "log_alert", metric_key=resolve_metric_key(alert, None))
    if _ABSENCE.search(raw_expr):
        return AnalysisDecision(False, "absence_alert", metric_key=resolve_metric_key(alert, raw_expr))

    query = explicit_query or strip_threshold(raw_expr)
    metric_key = resolve_metric_key(alert, query or raw_expr)
    if not query:
        return AnalysisDecision(False, "no_query", metric_key=metric_key)

    if not forced:
        names = metric_names(query)
        if names and all(_STATUS_METRIC.match(name) for name in names):
            return AnalysisDecision(False, "status_alert", query=query, metric_key=metric_key)

    return AnalysisDecision(True, None, query=query, metric_key=metric_key)
