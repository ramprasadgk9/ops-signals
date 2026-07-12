from __future__ import annotations

import math
from datetime import datetime
from typing import Iterable

from ops_signals.findings.schema import OperationalFinding
from ops_signals.signals.schema import OperationalSignal


_SEVERITY_WEIGHT = {
    "low": 0.35,
    "medium": 0.7,
    "high": 1.0,
}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _signal_magnitude(signal: OperationalSignal) -> float:
    evidence = signal.evidence
    if signal.signal_type == "baseline_shift":
        return _clamp(abs(float(evidence.get("percent_change", 0.0))) / 100.0)
    if signal.signal_type == "trend":
        return _clamp(abs(float(evidence.get("slope_percent", 0.0))) / 100.0)
    if signal.signal_type == "anomaly":
        return _clamp(abs(float(evidence.get("max_abs_zscore", 0.0))) / 6.0)
    return 0.5


def _duration_score(signal: OperationalSignal) -> float:
    duration_minutes = max((signal.end_time - signal.start_time).total_seconds() / 60.0, 0.0)
    return _clamp(duration_minutes / 30.0)


def _recency_score(signal: OperationalSignal, analysis_window_end: datetime | None) -> float:
    if analysis_window_end is None:
        return 0.5
    delta_minutes = max((analysis_window_end - signal.end_time).total_seconds() / 60.0, 0.0)
    # Recent signals are closer to the end of the batch window.
    return _clamp(math.exp(-delta_minutes / 180.0))


def score_signal(signal: OperationalSignal, analysis_window_end: datetime | None = None) -> float:
    severity_score = _SEVERITY_WEIGHT.get(signal.severity.lower(), 0.5)
    confidence_score = _clamp(signal.confidence)
    magnitude_score = _signal_magnitude(signal)
    duration_score = _duration_score(signal)
    recency_score = _recency_score(signal, analysis_window_end)
    score = (
        0.28 * severity_score
        + 0.22 * confidence_score
        + 0.25 * magnitude_score
        + 0.10 * duration_score
        + 0.15 * recency_score
    )
    return round(_clamp(score), 4)


def score_signals(signals: Iterable[OperationalSignal], analysis_window_end: datetime | None = None) -> list[OperationalSignal]:
    scored: list[OperationalSignal] = []
    for signal in signals:
        signal.importance_score = score_signal(signal, analysis_window_end)
        scored.append(signal)
    return scored


def score_finding(signals: list[OperationalSignal], comparison_json: dict[str, object]) -> float:
    if not signals:
        return 0.0

    signal_scores = [signal.importance_score for signal in signals]
    max_signal = max(signal_scores)
    mean_signal = sum(signal_scores) / len(signal_scores)
    signal_count_bonus = _clamp(len(signals) / 6.0)
    change_percent = float(comparison_json.get("change_percent", 0.0) or 0.0)
    change_bonus = _clamp(abs(change_percent) / 100.0)
    score = 0.45 * max_signal + 0.20 * mean_signal + 0.20 * signal_count_bonus + 0.15 * change_bonus
    return round(_clamp(score), 4)
