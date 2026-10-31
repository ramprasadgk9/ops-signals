"""One line per pod: how New Analysis turns a per-pod query into the one series it analyzes.

Scheduled runs already read a service as one line (`avg by (service) (...)` and friends, picked per
metric from config/prometheus_metric_knowledge.yaml). A hand-made New Analysis query returns one
series per pod instead, which the analysis can't take. This module notices that, builds the same
kind of combined query with the same per-metric choice, and names a pod that behaves differently
from the rest so the user can analyze it alone.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from statistics import median

from backend.app.models.prometheus import OddSeriesOut, PodSplitOut, PrometheusSeriesOut, PrometheusSeriesSample

COMBINE_CHOICES = ("max", "sum", "avg", "min")
_SIMPLE_SELECTOR = re.compile(r"^\s*([a-zA-Z_:][a-zA-Z0-9_:]*)\s*(?:\{(.*)\})?\s*$", re.DOTALL)
_LABEL_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
# Names of metrics that count things (per pod, so the service's value is the pods' sum).
_COUNT_OR_RATE = re.compile(r"(_per_second|_per_sec|_per_minute|_rps|_qps|_total|_count)$")


def find_pod_split(
    query: str,
    series: list[PrometheusSeriesOut],
    *,
    metric: str | None,
    split_labels: list[str],
    cluster_label: str | None,
) -> PodSplitOut | None:
    """The pod (or instance) label that tells the series apart, with the combined queries - or
    None when the series differ by something else (a cluster, a status code) that combining would
    wrongly merge."""
    if len(series) < 2:
        return None
    values: dict[str, set[str]] = {}
    for item in series:
        for key, value in item.labels.items():
            if key != "__name__":
                values.setdefault(key, set()).add(value)
    differing = {key for key, seen in values.items() if len(seen) > 1 or any(key not in item.labels for item in series)}
    if cluster_label and cluster_label in differing:
        return None
    # One value per series: a pod label. A label with fewer values than series (pod + status code)
    # means each pod has several lines, and combining would mix the status codes too.
    label = next(
        (key for key in split_labels if key in differing and all(key in item.labels for item in series) and len(values[key]) == len(series)),
        None,
    )
    if label is None:
        return None

    keep = sorted(key for key in values if key not in differing and _LABEL_NAME.match(key))
    inner = query.strip()
    queries = {how: f"{how} by ({', '.join(keep)}) ({inner})" for how in COMBINE_CHOICES}
    odd = odd_series(series, label)
    names = sorted(values[label])
    if odd:
        names = [odd.value, *[name for name in names if name != odd.value]]
    return PodSplitOut(
        label=label,
        values=names,
        suggested_combine=suggested_combine(metric or _metric_from_query(query, series)),
        queries=queries,
        one_queries={name: one_query for name in names if (one_query := _one_series_query(query, label, name))},
        odd=odd,
    )


def suggested_combine(metric: str | None) -> str:
    """The aggregation scheduled runs use for this metric, so a manual run reads the same line."""
    if not metric:
        return "avg"
    classification = _classifier().classify(_discovered(metric), [], _constraints())
    if classification.selection_reason is None and _COUNT_OR_RATE.search(metric):
        # No rule knows the metric (scheduled runs don't watch it), but its name says it counts
        # something: the pods' requests per second add up to the service's.
        return "sum"
    aggregation = classification.suggested_query_strategy.aggregation
    # service_level is how the planner names "avg across the service".
    return aggregation if aggregation in COMBINE_CHOICES else "avg"


def odd_series(series: list[PrometheusSeriesOut], label: str) -> OddSeriesOut | None:
    """A series far from the others at the same moments while the others agree with each other.

    For every timestamp with 3+ series, each series' distance from the median of the others; a
    series whose average distance is several times every other series' and large next to the
    typical value is the odd one out. With 2 series there's no telling which one is odd.
    """
    by_time: dict[object, dict[str, float]] = {}
    for item in series:
        name = item.labels.get(label)
        if name is None:
            continue
        for sample in item.samples:
            by_time.setdefault(sample.timestamp, {})[name] = sample.value
    distances: dict[str, list[float]] = {}
    for row in by_time.values():
        if len(row) < 3:
            continue
        for name, value in row.items():
            others = [other for key, other in row.items() if key != name]
            distances.setdefault(name, []).append(abs(value - median(others)))
    if len(distances) < 3:
        return None
    scores = sorted(((sum(items) / len(items), name) for name, items in distances.items()), reverse=True)
    (top, name), (second, _) = scores[0], scores[1]
    others = [value for row in by_time.values() for key, value in row.items() if key != name]
    typical = median(others) if others else 0.0
    if top <= 0 or top < 3 * second or top < 0.2 * max(abs(typical), 1e-9):
        return None
    # Its furthest point from the others, up or down: the odd pod may be bad only for part of the
    # window, so a percentile of its own values can look normal.
    own = [value for row in by_time.values() for key, value in row.items() if key == name]
    high, low = max(own), min(own)
    reach = "drops to" if typical - low > high - typical else "reaches"
    level = low if reach == "drops to" else high
    count = len(distances) - 1
    return OddSeriesOut(
        value=name,
        message=f"{name} is behaving differently from the other {count} {label}s: it {reach} {_number(level)} while the others stay near {_number(typical)}.",
    )


def series_from_samples(samples) -> list[PrometheusSeriesOut]:
    """Samples the plugin read through a Grafana data source (one row per sample, each with its
    series' labels) as series, so they can be checked for a pod split like a preview."""
    grouped: dict[str, PrometheusSeriesOut] = {}
    for sample in samples:
        labels = dict(sample.labels or {})
        key = sample.series_id or repr(sorted(labels.items()))
        series = grouped.setdefault(key, PrometheusSeriesOut(labels=labels, samples=[]))
        series.samples.append(PrometheusSeriesSample(timestamp=sample.timestamp, value=sample.value))
    return list(grouped.values())


def combine_series(series: list[PrometheusSeriesOut], how: str) -> list[PrometheusSeriesSample]:
    """The pods as one line, combined per timestamp - what `how by (...) (query)` returns."""
    by_time: dict[datetime, list[float]] = defaultdict(list)
    for item in series:
        for sample in item.samples:
            by_time[sample.timestamp].append(sample.value)
    combine = {"max": max, "min": min, "sum": sum, "avg": lambda values: sum(values) / len(values)}[how]
    return [PrometheusSeriesSample(timestamp=moment, value=combine(values)) for moment, values in sorted(by_time.items())]


def common_labels(series: list[PrometheusSeriesOut]) -> dict[str, str]:
    """The labels every series has with the same value: the combined line's labels."""
    first = series[0].labels if series else {}
    return {key: value for key, value in first.items() if all(item.labels.get(key) == value for item in series)}


@dataclass
class _Preview:
    series: list[PrometheusSeriesOut]


class SeriesAlreadyRead:
    """Stands in for Prometheus in the drill-down when the per-pod series were already read
    (through Grafana): `preview` returns them for the window asked, whatever the query."""

    def __init__(self, series: list[PrometheusSeriesOut]):
        self._series = series

    def preview(self, query: str, start: datetime, end: datetime, step: str) -> _Preview:
        return _Preview(series=[
            PrometheusSeriesOut(labels=item.labels, samples=[sample for sample in item.samples if start <= sample.timestamp <= end])
            for item in self._series
        ])


def _one_series_query(query: str, label: str, value: str) -> str | None:
    """The query for one pod, for a plain selector only: a filter can't be added safely inside an
    arbitrary PromQL expression."""
    match = _SIMPLE_SELECTOR.match(query)
    if not match:
        return None
    name, matchers = match.group(1), (match.group(2) or "").strip().rstrip(",")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'{name}{{{matchers + "," if matchers else ""}{label}="{escaped}"}}'


def _metric_from_query(query: str, series: list[PrometheusSeriesOut]) -> str | None:
    names = {item.labels["__name__"] for item in series if "__name__" in item.labels}
    if len(names) == 1:
        return names.pop()
    match = _SIMPLE_SELECTOR.match(query)
    return match.group(1) if match else None


def _number(value: float) -> str:
    if abs(value) >= 100:
        return f"{value:,.0f}"
    if abs(value) >= 1:
        return f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{value:.3g}"


@lru_cache(maxsize=1)
def _classifier():
    from backend.app.autonomous.services import AutonomousConfig, MetricClassificationService

    return MetricClassificationService(AutonomousConfig())


def _discovered(metric: str):
    from backend.app.autonomous.schemas import DiscoveredMetric

    return DiscoveredMetric(metric_name=metric)


def _constraints():
    from backend.app.autonomous.schemas import CustomMetricConstraints

    return CustomMetricConstraints()
