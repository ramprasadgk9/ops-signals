from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any


def _to_iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _largest_change(signals: list[dict[str, Any]]) -> float:
    """The level change with the largest magnitude among these signals, as a signed percentage:
    positive means the metric moved up. Both level-change analyzers (baseline_shift, ruptures)
    report it as evidence["percent_change"]; "change_percent" is accepted too."""
    changes = []
    for sig in signals:
        evidence = sig.get("evidence", {})
        value = evidence.get("percent_change", evidence.get("change_percent"))
        if value is not None:
            changes.append(float(value))
    return max(changes, key=abs, default=0.0)


def _windows(signals: list[dict[str, Any]], level_change: bool = False) -> list[list[Any]]:
    """When each signal was active, as [start, end] pairs - what behavior correlation compares
    across inputs. A level change (baseline_shift, ruptures) runs from its change point to the end of
    the window, since the new level persists; anything else uses its own start and end."""
    windows = []
    for sig in signals:
        start = sig.get("start_time")
        if level_change:
            start = sig.get("evidence", {}).get("change_point_time") or start
        end = sig.get("end_time") or start
        if start:
            windows.append([_to_iso(start), _to_iso(end)])
    return windows


# A ruptures change point counts as a change only above this size: unlike baseline_shift and
# trend, the ruptures analyzer reports every change point it finds, however small. The same
# "> 25" the shipped rules used before the change facts existed.
RUPTURES_MIN_CHANGE_PERCENT = 25.0


def _change_facts(
    trend_signals: list[dict[str, Any]],
    trend_slope: float,
    trend_change_percent: float,
    baseline_signals: list[dict[str, Any]],
    ruptures_signals: list[dict[str, Any]],
) -> dict[str, Any]:
    """Whether the metric went up or down, whichever analyzer saw it: a trend, a baseline shift, or
    a ruptures change point of more than RUPTURES_MIN_CHANGE_PERCENT. The router runs only some of
    these on a given series (ruptures on a steady climb, often), so a rule that means "went up"
    asks this instead of naming one analyzer and missing the run where another one ran."""
    sources: list[tuple[str, float, list[dict[str, Any]], bool]] = []
    if trend_signals and trend_slope:
        signed = abs(trend_change_percent) if trend_slope > 0 else -abs(trend_change_percent)
        sources.append(("trend", signed, trend_signals, False))
    if baseline_signals:
        sources.append(("baseline_shift", _largest_change(baseline_signals), baseline_signals, True))
    significant_ruptures = [
        sig for sig in ruptures_signals if abs(_largest_change([sig])) > RUPTURES_MIN_CHANGE_PERCENT
    ]
    if significant_ruptures:
        sources.append(("ruptures", _largest_change(significant_ruptures), significant_ruptures, True))

    upward = any(signed > 0 for _, signed, _, _ in sources)
    downward = any(signed < 0 for _, signed, _, _ in sources)
    signed_change = max((signed for _, signed, _, _ in sources), key=abs, default=0.0)
    return {
        "present": bool(sources),
        "upward": upward,
        "downward": downward,
        "direction": "mixed" if upward and downward else "upward" if upward else "downward" if downward else "none",
        "change_percent": abs(signed_change),
        "signed_change_percent": signed_change,
        "sources": [name for name, _, _, _ in sources],
        "windows": [window for _, _, signals, level in sources for window in _windows(signals, level_change=level)],
    }


def input_facts(metric_names: list[str], analyzers: list[str], signals: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Facts for one behavior input: the signals of the first of its metric names that has any
    (from the input's analyzers, when it lists some). None when none of the names has signals."""
    for name in metric_names:
        matched = [
            signal for signal in signals
            if signal.get("metric_name") == name and (not analyzers or signal.get("analyzer_id") in analyzers)
        ]
        if matched:
            return extract_facts(matched)[name]
    return None


def extract_facts(signals: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    by_metric: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for signal in signals:
        by_metric[str(signal.get("metric_name") or "unknown")].append(signal)

    for metric_name, metric_signals in by_metric.items():
        anomaly_signals = [sig for sig in metric_signals if sig.get("signal_type") in {"anomaly_zscore", "anomaly"}]
        trend_signals = [sig for sig in metric_signals if sig.get("signal_type") == "trend"]
        baseline_signals = [sig for sig in metric_signals if sig.get("signal_type") == "baseline_shift"]
        ruptures_signals = [sig for sig in metric_signals if sig.get("signal_type") == "ruptures"]
        trend_slope = next(
            (float(sig.get("evidence", {}).get("slope", 0.0)) for sig in trend_signals if sig.get("evidence", {}).get("slope") is not None),
            0.0,
        )
        trend_change_percent = next(
            (
                float(sig.get("evidence", {}).get("slope_percent", sig.get("evidence", {}).get("change_percent", 0.0)))
                for sig in trend_signals
                if sig.get("evidence", {}).get("slope_percent") is not None or sig.get("evidence", {}).get("change_percent") is not None
            ),
            0.0,
        )

        grouped[metric_name] = {
            "anomaly": {
                "present": bool(anomaly_signals),
                "count": len(anomaly_signals),
                "max_score": max([float(sig.get("importance_score", 0.0)) for sig in anomaly_signals], default=0.0),
                "windows": _windows(anomaly_signals),
            },
            "trend": {
                "present": bool(trend_signals),
                "count": len(trend_signals),
                "direction": "upward" if trend_slope > 0 else "downward" if trend_slope < 0 else "flat",
                "change_percent": abs(trend_change_percent),
                "slope": trend_slope,
                "windows": _windows(trend_signals),
            },
            "baseline_shift": {
                "present": bool(baseline_signals),
                "count": len(baseline_signals),
                "change_percent": abs(_largest_change(baseline_signals)),
                "signed_change_percent": _largest_change(baseline_signals),
                "windows": _windows(baseline_signals, level_change=True),
            },
            "ruptures": {
                "present": bool(ruptures_signals),
                "count": len(ruptures_signals),
                "change_percent": abs(_largest_change(ruptures_signals)),
                "signed_change_percent": _largest_change(ruptures_signals),
                "change_point_index": min([int(sig.get("evidence", {}).get("change_point_index", 0)) for sig in ruptures_signals], default=0),
                "windows": _windows(ruptures_signals, level_change=True),
            },
            "change": _change_facts(trend_signals, trend_slope, trend_change_percent, baseline_signals, ruptures_signals),
            "signal": {
                "count": len(metric_signals),
                "types": sorted({str(sig.get("signal_type")) for sig in metric_signals if sig.get("signal_type")}),
                "window_start": _to_iso(min((sig.get("start_time") for sig in metric_signals if sig.get("start_time")), default=None)),
                "window_end": _to_iso(max((sig.get("end_time") for sig in metric_signals if sig.get("end_time")), default=None)),
                "windows": _windows(metric_signals),
            },
        }
    return grouped


def extract_temporal_bounds(signals: list[dict[str, Any]]) -> tuple[datetime | None, datetime | None]:
    start_times = [sig.get("start_time") for sig in signals if sig.get("start_time")]
    end_times = [sig.get("end_time") for sig in signals if sig.get("end_time")]
    return (min(start_times) if start_times else None, max(end_times) if end_times else None)
