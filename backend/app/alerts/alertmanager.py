"""Alertmanager (and generic) alert payloads -> NormalizedAlert."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from backend.app.alerts.schemas import AlertmanagerWebhook, GenericAlertRequest, NormalizedAlert

# Alertmanager sends endsAt="0001-01-01T00:00:00Z" for alerts that haven't resolved.
_ZERO_TIME_YEAR = 1


def expr_from_generator_url(generator_url: str | None) -> str | None:
    """Prometheus-compatible rule engines (Prometheus, Thanos, Mimir, VictoriaMetrics) link back
    to the rule's graph with the expression in `g0.expr`. Anything else - Grafana-managed alerts
    (/alerting/grafana/<uid>/view), Loki's ruler without it - yields None."""
    if not generator_url:
        return None
    try:
        values = parse_qs(urlparse(generator_url).query).get("g0.expr")
    except ValueError:
        return None
    if not values or not values[0].strip():
        return None
    return values[0].strip()


def service_from_labels(labels: dict[str, str], service_labels: list[str]) -> str | None:
    for key in service_labels:
        value = labels.get(key)
        if value and value.strip():
            return value.strip()
    return None


def from_alertmanager(payload: AlertmanagerWebhook, service_labels: list[str]) -> list[NormalizedAlert]:
    alerts: list[NormalizedAlert] = []
    for item in payload.alerts:
        labels = dict(item.labels)
        ends_at = _to_utc(item.endsAt) if item.endsAt and item.endsAt.year > _ZERO_TIME_YEAR else None
        alerts.append(
            NormalizedAlert(
                source="alertmanager",
                fingerprint=item.fingerprint or _fingerprint("alertmanager", labels),
                status=item.status,
                alert_name=labels.get("alertname") or "unnamed-alert",
                service=service_from_labels(labels, service_labels),
                severity=(labels.get("severity") or None),
                starts_at=_to_utc(item.startsAt),
                ends_at=ends_at,
                labels=labels,
                annotations=dict(item.annotations),
                expr=expr_from_generator_url(item.generatorURL),
                generator_url=item.generatorURL,
                external_url=payload.externalURL,
            )
        )
    return alerts


def from_generic(payload: GenericAlertRequest, service_labels: list[str]) -> NormalizedAlert:
    labels = dict(payload.labels)
    labels.setdefault("alertname", payload.alert_name)
    return NormalizedAlert(
        source="generic",
        fingerprint=payload.fingerprint or _fingerprint("generic", labels),
        status=payload.status,
        alert_name=payload.alert_name,
        service=payload.service or service_from_labels(labels, service_labels),
        severity=payload.severity or labels.get("severity"),
        starts_at=_to_utc(payload.starts_at) if payload.starts_at else datetime.now(timezone.utc),
        ends_at=_to_utc(payload.ends_at) if payload.ends_at else None,
        labels=labels,
        annotations=dict(payload.annotations),
        expr=payload.expr,
        generator_url=payload.source_url,
    )


def _fingerprint(source: str, labels: dict[str, str]) -> str:
    raw = source + json.dumps(labels, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
