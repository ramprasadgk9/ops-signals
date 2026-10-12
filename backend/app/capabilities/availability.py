"""Which features the connected sources turn on.

One declarative list, read by the UI to group the menu, explain a feature that can't run yet and
show what each source unlocks. A feature lists the sources it can't run without (`needs`) and
those that only make it more complete (`better_with`). Source ids: otlp, prometheus (any
Prometheus-compatible connection), alertmanager, grafana, events (deploy and change events).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

FeatureState = Literal["on", "partly", "off"]


@dataclass(frozen=True)
class Feature:
    id: str
    label: str
    needs: tuple[str, ...] = ()
    better_with: tuple[str, ...] = ()
    # Why the feature is only partly there without `better_with`.
    partial_detail: str | None = None
    # A partial state that depends on more than a missing source; returns its detail, or None.
    partial_when: Callable[[set[str]], str | None] | None = field(default=None, compare=False)


def _otlp_histograms(connected: set[str]) -> str | None:
    if "otlp" in connected and "prometheus" not in connected:
        return "OTLP histograms aren't read yet, so percentiles come only from Prometheus or CSV data."
    return None


FEATURES: tuple[Feature, ...] = (
    Feature("findings", "Findings and analyzers"),
    Feature("cases", "Cases and ticketing"),
    Feature("memory", "Operational memory and similar cases"),
    Feature("notifications", "Slack notifications"),
    Feature("assistant", "Assistant and MCP"),
    Feature("behavior_rules", "Behavior rules"),
    Feature("deploy_correlation", "Deploy correlation", needs=("events",)),
    Feature("latency_percentiles", "Latency percentiles", partial_when=_otlp_histograms),
    Feature("autonomous_analysis", "Autonomous analysis", needs=("prometheus",)),
    Feature("pod_drilldown", "Drill-down by pod", needs=("prometheus",)),
    Feature("alert_enrichment", "Alert enrichment", needs=("alertmanager", "prometheus")),
    Feature(
        "metric_usage",
        "Metric Usage",
        needs=("prometheus",),
        better_with=("grafana",),
        partial_detail="Reads Prometheus alert and recording rules only; connect Grafana to include dashboards.",
    ),
)


class FeatureAvailability(BaseModel):
    id: str
    label: str
    state: FeatureState
    # The sources to connect: the missing `needs` when off, the missing `better_with` when partly.
    missing: list[str]
    detail: str | None = None
    # The feature's own requirements, so a source can list what it unlocks.
    needs: list[str] = []
    better_with: list[str] = []


def evaluate(connected: set[str]) -> list[FeatureAvailability]:
    out: list[FeatureAvailability] = []
    for feature in FEATURES:
        missing_needs = [source for source in feature.needs if source not in connected]
        missing_extras = [source for source in feature.better_with if source not in connected]
        if missing_needs:
            state, missing, detail = "off", missing_needs, None
        elif missing_extras:
            state, missing, detail = "partly", missing_extras, feature.partial_detail
        elif feature.partial_when and (reason := feature.partial_when(connected)):
            state, missing, detail = "partly", [], reason
        else:
            state, missing, detail = "on", [], None
        out.append(
            FeatureAvailability(
                id=feature.id,
                label=feature.label,
                state=state,
                missing=missing,
                detail=detail,
                needs=list(feature.needs),
                better_with=list(feature.better_with),
            )
        )
    return out
