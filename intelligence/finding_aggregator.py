from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

import pandas as pd

from intelligence.findings.schema import OperationalFinding
from intelligence.importance_score import score_finding
from intelligence.series_identity import cluster_points
from intelligence.signals.schema import OperationalSignal
from intelligence.window_compare import compare_windows

# Signals saying the data itself is broken (stopped reporting, stopped changing). They become their
# own finding per metric instead of joining the metric's behavior finding, so "the data is broken"
# is never blended with - or allowed to rescue - a behavior finding built on that same data.
DATA_HEALTH_SIGNAL_TYPES = {"data_gap", "flatline"}

# An event ending this close to the last analyzed point is still going on. Wider for coarse data,
# where the last few steps are the same event's tail.
ONGOING_MIN_TOLERANCE = timedelta(minutes=5)
ONGOING_TOLERANCE_STEPS = 3


@dataclass(slots=True)
class FindingAggregationResult:
    findings: list[OperationalFinding]
    comparison_json: dict[str, object]


class FindingAggregator:
    def aggregate(
        self,
        signals: Iterable[OperationalSignal],
        points: pd.DataFrame,
        series_profile: dict[str, object] | None = None,
    ) -> FindingAggregationResult:
        signal_list = list(signals)
        if not signal_list:
            return FindingAggregationResult(findings=[], comparison_json={})

        signals_by_key: dict[tuple[str | None, str, str | None, bool], list[OperationalSignal]] = {}
        for signal in signal_list:
            key = (signal.service, signal.metric_name, signal.cluster, signal.signal_type in DATA_HEALTH_SIGNAL_TYPES)
            signals_by_key.setdefault(key, []).append(signal)

        findings: list[OperationalFinding] = []
        comparison_json: dict[str, object] = {}
        for (service, metric_name, cluster, _), grouped_signals in signals_by_key.items():
            if any(self._skip_by_finding_rule(grouped_signals, analyzer_id) for analyzer_id in self._FINDING_RULE_GATED_ANALYZERS):
                continue

            metric_points = points.copy()
            metric_points = metric_points[metric_points["metric_name"].astype(str) == str(metric_name)]
            if service is not None:
                metric_points = metric_points[metric_points["service"].astype(str) == str(service)]
            metric_points = cluster_points(metric_points, cluster)

            comparison_json = compare_windows(metric_points, grouped_signals)
            signal_ids = [signal.signal_id for signal in grouped_signals]
            importance = score_finding(grouped_signals, comparison_json)
            health_status = self._health_status(importance)
            investigation_priority = self._investigation_priority(importance)
            category = self._category(grouped_signals)
            title = self._title(metric_name, grouped_signals, comparison_json, series_profile)
            summary = self._summary(metric_name, grouped_signals, comparison_json, series_profile)
            event_start, event_end, ongoing = self._event_time(grouped_signals, metric_points)
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
                    cluster=cluster,
                    event_start=event_start,
                    event_end=event_end,
                    ongoing=ongoing,
                )
            )

        findings.sort(key=lambda item: item.importance_score, reverse=True)
        return FindingAggregationResult(findings=findings, comparison_json=comparison_json)

    # These 4 analyzers always emit a signal once they have enough data (so labs and the CSV
    # preview can still show forecast/score/relative-error diagnostics on a non-finding run),
    # tagging whether their own finding_rules threshold was actually crossed via
    # evidence["finding_rule_matched"] - unlike trend/ruptures/baseline_shift, which only ever
    # emit a signal once their own threshold is already crossed, so their mere presence already
    # means a real detection.
    _FINDING_RULE_GATED_ANALYZERS = {"pyod_outlier", "stumpy", "prophet", "anomaly_zscore"}

    def _skip_by_finding_rule(self, signals: list[OperationalSignal], analyzer_id: str) -> bool:
        own_signals = [signal for signal in signals if signal.analyzer_id == analyzer_id]
        if not own_signals:
            return False
        if any(signal.evidence.get("finding_rule_matched") is True for signal in own_signals):
            return False
        # Only rescue this analyzer's own non-match if something else in the group is
        # independently finding-worthy: an analyzer that doesn't use this pattern at all (its
        # presence already means a real detection), or another finding-rule-gated analyzer whose
        # own rule actually matched. Previously this rescued on "is there any other analyzer's
        # signal at all", which let e.g. stumpy's own non-matching pattern_discovery signal rescue
        # prophet's own non-matching forecast on a purely seasonal series with no real deviation -
        # see issue #20 (both signals were noise; two pieces of noise aren't a finding).
        other_signals = [signal for signal in signals if signal.analyzer_id != analyzer_id]
        for signal in other_signals:
            if signal.analyzer_id not in self._FINDING_RULE_GATED_ANALYZERS:
                return False
            if signal.evidence.get("finding_rule_matched") is True:
                return False
        return True

    def _category(self, signals: list[OperationalSignal]) -> str:
        counts = Counter(signal.signal_type for signal in signals)
        if DATA_HEALTH_SIGNAL_TYPES.intersection(counts):
            return "data_quality"
        if counts.get("ruptures", 0) or counts.get("baseline_shift", 0) or counts.get("trend", 0):
            return "behavior_change"
        if counts.get("anomaly", 0):
            return "unusual_activity"
        return "operational_insight"

    @staticmethod
    def _event_time(signals: list[OperationalSignal], points: pd.DataFrame) -> tuple[datetime | None, datetime | None, bool | None]:
        """The most recent event's start and end, and whether it was still going on at the last
        analyzed point. The most recent, not the whole span: a later run that still sees an old
        event next to a new one must date the finding by the new one."""
        timed = [
            (start, end)
            for start, end in ((_utc(signal.start_time), _utc(signal.end_time)) for signal in signals)
            if start is not None and end is not None
        ]
        if not timed:
            return None, None, None
        event_start, event_end = max(timed, key=lambda item: (item[0], item[1]))
        timestamps = pd.to_datetime(points["timestamp"], utc=True, errors="coerce").dropna().sort_values() if "timestamp" in points else pd.Series(dtype="datetime64[ns, UTC]")
        if timestamps.empty:
            return event_start, event_end, None
        step = timestamps.diff().median()
        tolerance = max(ONGOING_MIN_TOLERANCE, step * ONGOING_TOLERANCE_STEPS) if pd.notna(step) else ONGOING_MIN_TOLERANCE
        return event_start, event_end, bool(event_end >= timestamps.iloc[-1].to_pydatetime() - tolerance)

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

    def _title(
        self,
        metric_name: str,
        signals: list[OperationalSignal],
        comparison_json: dict[str, object],
        series_profile: dict[str, object] | None = None,
    ) -> str:
        signal_types = {signal.signal_type for signal in signals}
        if DATA_HEALTH_SIGNAL_TYPES >= signal_types:
            if signal_types == DATA_HEALTH_SIGNAL_TYPES:
                return f"{metric_name} stopped reporting and got stuck at a constant value during the selected time window."
            if "data_gap" in signal_types:
                return f"{metric_name} stopped reporting data during the selected time window."
            return f"{metric_name} got stuck at a constant value during the selected time window."
        if self._has_structural_change(signals, series_profile):
            return f"{metric_name} experienced a persistent baseline shift during the selected time window."
        if "baseline_shift" in signal_types:
            return f"{metric_name} moved to a new baseline."
        if {"anomaly", "spike", "outlier"}.intersection(signal_types):
            return f"{metric_name} has unusual activity in the selected time window."
        if "trend" in signal_types:
            return f"{metric_name} is trending in one direction."
        if {"forecast", "seasonality", "seasonal"}.intersection(signal_types):
            return f"{metric_name} shows predictable recurring or forecastable behaviour."
        if comparison_json.get("new_behavior"):
            return f"{metric_name} behaviour changed significantly during the selected time window."
        return f"{metric_name} has unusual behaviour."

    def _summary(
        self,
        metric_name: str,
        signals: list[OperationalSignal],
        comparison_json: dict[str, object],
        series_profile: dict[str, object] | None = None,
    ) -> str:
        signal_types = {signal.signal_type for signal in signals}
        if DATA_HEALTH_SIGNAL_TYPES >= signal_types:
            ordered = sorted(signals, key=lambda signal: signal.start_time)
            return " ".join(signal.summary for signal in ordered)
        ruptures = next((signal for signal in signals if signal.signal_type == "ruptures"), None)
        baseline = next((signal for signal in signals if signal.signal_type == "baseline_shift"), None)
        trend = next((signal for signal in signals if signal.signal_type == "trend"), None)
        anomaly = next((signal for signal in signals if signal.signal_type in {"anomaly", "spike", "outlier"}), None)
        forecast_signals = [signal for signal in signals if signal.signal_type in {"forecast", "seasonality", "seasonal"}]
        anomaly_count = sum(1 for signal in signals if signal.signal_type in {"anomaly", "spike", "outlier"})

        if ruptures is not None and self._has_structural_change(signals, series_profile):
            return self._structural_change_summary(ruptures, baseline, trend, comparison_json)

        parts: list[str] = []
        if baseline is not None:
            parts.append(self._baseline_summary(baseline))
            if trend is not None:
                parts.append(self._secondary_trend_summary(trend))
        elif anomaly is not None:
            parts.append(anomaly.summary)
            if trend is not None:
                parts.append(self._secondary_trend_summary(trend))
        if trend is not None and baseline is None and anomaly is None:
            parts.append(f"{trend.summary.lower()}")
        if anomaly_count:
            parts.append(f"{anomaly_count} anomaly window(s) detected")
        for forecast_signal in forecast_signals:
            parts.append(forecast_signal.summary)

        if comparison_json.get("summary"):
            parts.append(str(comparison_json["summary"]))

        if not parts:
            return f"Operational behaviour for {metric_name} changed across the batch window."
        return "; ".join(parts).capitalize()

    def _has_structural_change(self, signals: list[OperationalSignal], series_profile: dict[str, object] | None) -> bool:
        if not any(signal.signal_type == "ruptures" for signal in signals):
            return False
        profiles = {
            str(item).strip().lower()
            for item in (series_profile or {}).get("detected_profiles", [])
            if str(item).strip()
        }
        if profiles:
            return bool({"baseline_shift", "regime_change"}.intersection(profiles))
        return any(signal.signal_type == "baseline_shift" for signal in signals)

    def _structural_change_summary(
        self,
        ruptures: OperationalSignal,
        baseline: OperationalSignal | None,
        trend: OperationalSignal | None,
        comparison_json: dict[str, object],
    ) -> str:
        evidence = ruptures.evidence
        sample = evidence.get("change_point_index")
        left_mean = self._optional_float(evidence.get("left_mean"))
        right_mean = self._optional_float(evidence.get("right_mean"))
        percent_change = self._optional_float(evidence.get("percent_change"))

        if sample is not None and left_mean is not None and right_mean is not None and percent_change is not None:
            primary = (
                f"A structural change was detected around sample {sample}, where the average value "
                f"{self._direction_word(percent_change)} from {left_mean:.4f} to {right_mean:.4f}, "
                f"a change of {abs(percent_change):.1f}%."
            )
        else:
            primary = ruptures.summary

        parts = [primary]
        if baseline is not None:
            baseline_change = self._optional_float(baseline.evidence.get("percent_change"))
            if percent_change is not None:
                parts.append("A first-half/second-half baseline shift supports this structural finding.")
            elif baseline_change is not None:
                parts.append(self._baseline_summary(baseline))
        if comparison_json.get("summary"):
            parts.append(str(comparison_json["summary"]))
        if trend is not None:
            parts.append(
                f"Trend Regression observed an overall {self._trend_direction(trend)} direction, "
                "but the dominant behavior is an abrupt regime change."
            )
        return " ".join(parts)

    def _baseline_summary(self, baseline: OperationalSignal) -> str:
        percent_change = self._optional_float(baseline.evidence.get("percent_change"))
        if percent_change is None:
            return baseline.summary
        return f"Baseline {self._direction_word(percent_change)} {abs(percent_change):.1f}%"

    def _secondary_trend_summary(self, trend: OperationalSignal) -> str:
        return f"Trend Regression observed an overall {self._trend_direction(trend)} direction as secondary context"

    def _trend_direction(self, trend: OperationalSignal) -> str:
        slope = self._optional_float(trend.evidence.get("slope"))
        if slope is not None:
            return "upward" if slope >= 0 else "downward"
        summary = trend.summary.lower()
        if "downward" in summary:
            return "downward"
        return "upward"

    @staticmethod
    def _direction_word(percent_change: float) -> str:
        return "increased" if percent_change >= 0 else "decreased"

    @staticmethod
    def _optional_float(value: object) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


def _utc(value: object) -> datetime | None:
    if value is None:
        return None
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        return None
    timestamp = timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")
    return timestamp.to_pydatetime()
