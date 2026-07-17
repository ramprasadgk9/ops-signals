from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from intelligence.findings.schema import OperationalFinding
from intelligence.importance_score import score_finding
from intelligence.signals.schema import OperationalSignal
from intelligence.window_compare import compare_windows


@dataclass(slots=True)
class FindingAggregationResult:
    findings: list[OperationalFinding]
    comparison_json: dict[str, object]


class FindingAggregator:
    def aggregate(self, signals: Iterable[OperationalSignal], points: pd.DataFrame) -> FindingAggregationResult:
        signal_list = list(signals)
        if not signal_list:
            return FindingAggregationResult(findings=[], comparison_json={})

        signals_by_key: dict[tuple[str | None, str], list[OperationalSignal]] = {}
        for signal in signal_list:
            key = (signal.service, signal.metric_name)
            signals_by_key.setdefault(key, []).append(signal)

        findings: list[OperationalFinding] = []
        comparison_json: dict[str, object] = {}
        for (service, metric_name), grouped_signals in signals_by_key.items():
            metric_points = points.copy()
            metric_points = metric_points[metric_points["metric_name"].astype(str) == str(metric_name)]
            if service is not None:
                metric_points = metric_points[metric_points["service"].astype(str) == str(service)]

            comparison_json = compare_windows(metric_points, grouped_signals)
            signal_ids = [signal.signal_id for signal in grouped_signals]
            importance = score_finding(grouped_signals, comparison_json)
            health_status = self._health_status(importance)
            investigation_priority = self._investigation_priority(importance)
            category = self._category(grouped_signals)
            title = self._title(metric_name, grouped_signals, comparison_json)
            summary = self._summary(metric_name, grouped_signals, comparison_json)
            findings.append(
                OperationalFinding(
                    service=service,
                    metric_name=metric_name,
                    title=title,
                    summary=summary,
                    category=category,
                    health_status=health_status,
                    importance_score=importance,
                    investigation_priority=investigation_priority,
                    signal_ids=signal_ids,
                    comparison_json=comparison_json,
                )
            )

        findings.sort(key=lambda item: item.importance_score, reverse=True)
        return FindingAggregationResult(findings=findings, comparison_json=comparison_json)

    def _category(self, signals: list[OperationalSignal]) -> str:
        counts = Counter(signal.signal_type for signal in signals)
        if counts.get("baseline_shift", 0) or counts.get("trend", 0):
            return "behavior_change"
        if counts.get("anomaly", 0):
            return "unusual_activity"
        return "operational_insight"

    def _health_status(self, importance_score: float) -> str:
        if importance_score >= 0.8:
            return "critical"
        if importance_score >= 0.55:
            return "significant"
        return "normal"

    def _investigation_priority(self, importance_score: float) -> int:
        if importance_score >= 0.8:
            return 1
        if importance_score >= 0.55:
            return 2
        return 3

    def _title(self, metric_name: str, signals: list[OperationalSignal], comparison_json: dict[str, object]) -> str:
        if comparison_json.get("new_behavior"):
            return f"{metric_name} behaviour changed significantly yesterday."
        signal_types = {signal.signal_type for signal in signals}
        if "baseline_shift" in signal_types:
            return f"{metric_name} moved to a new baseline."
        if "trend" in signal_types:
            return f"{metric_name} is trending in one direction."
        return f"{metric_name} has unusual behaviour."

    def _summary(self, metric_name: str, signals: list[OperationalSignal], comparison_json: dict[str, object]) -> str:
        signal_types = {signal.signal_type for signal in signals}
        baseline = next((signal for signal in signals if signal.signal_type == "baseline_shift"), None)
        trend = next((signal for signal in signals if signal.signal_type == "trend"), None)
        anomaly_count = sum(1 for signal in signals if signal.signal_type == "anomaly")

        parts: list[str] = []
        if baseline is not None:
            parts.append(f"baseline increased {abs(float(baseline.evidence.get('percent_change', 0.0))):.1f}%")
        if trend is not None:
            parts.append(f"{trend.summary.lower()}")
        if anomaly_count:
            parts.append(f"{anomaly_count} anomaly window(s) detected")

        if comparison_json.get("summary"):
            parts.append(str(comparison_json["summary"]))

        if not parts:
            return f"Operational behaviour for {metric_name} changed across the batch window."
        return "; ".join(parts).capitalize()
