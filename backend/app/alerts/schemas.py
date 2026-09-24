from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AlertmanagerAlert(BaseModel):
    status: Literal["firing", "resolved"]
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: datetime
    endsAt: datetime | None = None
    generatorURL: str | None = None
    fingerprint: str | None = None


class AlertmanagerWebhook(BaseModel):
    """Alertmanager webhook payload, version 4
    (https://prometheus.io/docs/alerting/latest/configuration/#webhook_config)."""

    version: str = "4"
    status: Literal["firing", "resolved"]
    receiver: str | None = None
    groupKey: str | None = None
    externalURL: str | None = None
    alerts: list[AlertmanagerAlert] = Field(default_factory=list)


class GenericAlertRequest(BaseModel):
    """Vendor-neutral alert shape for POST /api/alerts - anything that isn't Alertmanager maps
    into this (a future Grafana/Datadog adapter, or a plain curl)."""

    alert_name: str = Field(min_length=1)
    status: Literal["firing", "resolved"] = "firing"
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    fingerprint: str | None = None
    service: str | None = None
    severity: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    expr: str | None = Field(default=None, description="PromQL for the alerting series, if known")
    source_url: str | None = None


class AlertReceiptOut(BaseModel):
    accepted: int
    duplicates: int = 0
    resolved: int = 0
    disabled: bool = False
    enrichment_ids: list[int] = Field(default_factory=list)


@dataclass
class NormalizedAlert:
    source: str
    fingerprint: str
    status: str
    alert_name: str
    service: str | None
    severity: str | None
    starts_at: datetime
    ends_at: datetime | None
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)
    expr: str | None = None
    generator_url: str | None = None
    external_url: str | None = None

    @property
    def summary(self) -> str:
        return self.annotations.get("summary") or self.annotations.get("description") or self.alert_name
