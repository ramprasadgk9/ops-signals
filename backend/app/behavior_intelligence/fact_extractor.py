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
            },
            "trend": {
                "present": bool(trend_signals),
                "count": len(trend_signals),
                "direction": "upward" if trend_slope > 0 else "downward" if trend_slope < 0 else "flat",
                "change_percent": abs(trend_change_percent),
                "slope": trend_slope,
            },
            "baseline_shift": {
                "present": bool(baseline_signals),
                "count": len(baseline_signals),
                "change_percent": abs(_largest_change(baseline_signals)),
                "signed_change_percent": _largest_change(baseline_signals),
            },
            "ruptures": {
                "present": bool(ruptures_signals),
                "count": len(ruptures_signals),
                "change_percent": abs(_largest_change(ruptures_signals)),
                "signed_change_percent": _largest_change(ruptures_signals),
                "change_point_index": min([int(sig.get("evidence", {}).get("change_point_index", 0)) for sig in ruptures_signals], default=0),
            },
            "signal": {
                "count": len(metric_signals),
                "types": sorted({str(sig.get("signal_type")) for sig in metric_signals if sig.get("signal_type")}),
                "window_start": _to_iso(min((sig.get("start_time") for sig in metric_signals if sig.get("start_time")), default=None)),
                "window_end": _to_iso(max((sig.get("end_time") for sig in metric_signals if sig.get("end_time")), default=None)),
            },
        }
    return grouped


def extract_temporal_bounds(signals: list[dict[str, Any]]) -> tuple[datetime | None, datetime | None]:
    start_times = [sig.get("start_time") for sig in signals if sig.get("start_time")]
    end_times = [sig.get("end_time") for sig in signals if sig.get("end_time")]
    return (min(start_times) if start_times else None, max(end_times) if end_times else None)
