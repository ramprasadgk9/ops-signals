"""Incident-level scoring for SMD, the way an on-call engineer would judge alerts.

- Alarms at or above the confidence threshold, from any of a machine's 38 metrics, are grouped into
  one alert while each is within ALERT_GAP_ROWS (15 minutes) of the previous one: a burst of alarms
  across several metrics is one page, not twenty.
- An incident is caught when an alert starts inside it. An alert that starts inside no incident is a
  false alert.
- Which metrics: for each caught incident, the metrics that alarmed inside it, ranked by their highest
  confidence there, are compared with the metrics listed for it. HitRate@P% (the OmniAnomaly paper's
  measure) is the share of listed metrics found among the top floor(P% x listed) ranked metrics.

No point-adjust. Much published SMD work scores with "point-adjust", which counts every row of an
incident as detected once any row is; it's been shown to let even random scores look strong (Kim et al.,
AAAI 2022). Scores here are not comparable with point-adjusted ones.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from benchmark.smd.data import Incident

ALERT_GAP_ROWS = 15
THRESHOLDS = (0.25, 0.5, 0.75, 0.9)
HEADLINE_THRESHOLD = 0.5
HIT_RATES = (1.0, 1.5)


@dataclass(slots=True)
class Alert:
    start: int
    end: int
    metrics: list[int]
    score: float


@dataclass(slots=True)
class IncidentCounts:
    incidents: int = 0
    caught: int = 0
    alerts: int = 0
    alerts_in_incidents: int = 0
    false_alerts: int = 0
    test_rows: int = 0
    delays: list[int] = field(default_factory=list)
    hit_rates: dict[str, list[float]] = field(default_factory=dict)
    localization_precision: list[float] = field(default_factory=list)

    def add(self, other: "IncidentCounts") -> None:
        self.incidents += other.incidents
        self.caught += other.caught
        self.alerts += other.alerts
        self.alerts_in_incidents += other.alerts_in_incidents
        self.false_alerts += other.false_alerts
        self.test_rows += other.test_rows
        self.delays.extend(other.delays)
        for key, values in other.hit_rates.items():
            self.hit_rates.setdefault(key, []).extend(values)
        self.localization_precision.extend(other.localization_precision)

    def summary(self) -> dict[str, Any]:
        recall = self.caught / self.incidents if self.incidents else None
        precision = self.alerts_in_incidents / self.alerts if self.alerts else None
        f1 = 2 * recall * precision / (recall + precision) if recall and precision else 0.0
        days = self.test_rows / 1440 if self.test_rows else 0
        return {
            "incidents": self.incidents,
            "caught": self.caught,
            "alerts": self.alerts,
            "alerts_in_incidents": self.alerts_in_incidents,
            "false_alerts": self.false_alerts,
            "recall": recall,
            "precision": precision,
            "f1": f1,
            "false_alerts_per_machine_day": self.false_alerts / days if days else None,
            "median_delay_minutes": _median(self.delays),
            "hit_rate": {key: (sum(values) / len(values) if values else None) for key, values in self.hit_rates.items()},
            "localization_precision": (sum(self.localization_precision) / len(self.localization_precision)) if self.localization_precision else None,
        }


def group_alerts(alarms: list[list[Any]], threshold: float) -> list[Alert]:
    """Alarms are [test row, metric number, score, analyzer]."""
    kept = sorted((a for a in alarms if a[2] >= threshold), key=lambda a: a[0])
    alerts: list[Alert] = []
    for row, metric, score, _ in kept:
        if alerts and row - alerts[-1].end <= ALERT_GAP_ROWS:
            last = alerts[-1]
            last.end = row
            last.score = max(last.score, score)
            if metric not in last.metrics:
                last.metrics.append(metric)
        else:
            alerts.append(Alert(row, row, [metric], score))
    return alerts


def score_machine(alarms: list[list[Any]], incidents: list[Incident], test_rows: int, threshold: float) -> IncidentCounts:
    alerts = group_alerts(alarms, threshold)
    counts = IncidentCounts(incidents=len(incidents), alerts=len(alerts), test_rows=test_rows)
    for alert in alerts:
        if any(incident.start <= alert.start <= incident.end for incident in incidents):
            counts.alerts_in_incidents += 1
        else:
            counts.false_alerts += 1
    for incident in incidents:
        first = next((alert for alert in alerts if incident.start <= alert.start <= incident.end), None)
        if first is None:
            continue
        counts.caught += 1
        counts.delays.append(first.start - incident.start)
        ranked = rank_metrics(alarms, incident, threshold)
        if incident.metrics:
            listed = set(incident.metrics)
            for p in HIT_RATES:
                top = ranked[: math.floor(p * len(listed))]
                counts.hit_rates.setdefault(f"{int(p * 100)}", []).append(len(listed & set(top)) / len(listed))
            if ranked:
                counts.localization_precision.append(len(listed & set(ranked)) / len(ranked))
    return counts


def rank_metrics(alarms: list[list[Any]], incident: Incident, threshold: float) -> list[int]:
    """Metrics that alarmed inside the incident, highest confidence first, earliest first on ties."""
    best: dict[int, tuple[float, int]] = {}
    for row, metric, score, _ in alarms:
        if score < threshold or not incident.start <= row <= incident.end:
            continue
        current = best.get(metric)
        if current is None or (-score, row) < (-current[0], current[1]):
            best[metric] = (score, row)
    return [metric for metric, _ in sorted(best.items(), key=lambda item: (-item[1][0], item[1][1]))]


def _median(values: list[int]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    return float(ordered[middle]) if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
