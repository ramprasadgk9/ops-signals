from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd


def _trend_percent(values: pd.Series) -> float:
    if len(values) < 3:
        return 0.0
    x_values = np.arange(len(values), dtype=float)
    y_values = values.to_numpy(dtype=float)
    slope, _ = np.polyfit(x_values, y_values, 1)
    baseline = abs(y_values[0]) if abs(y_values[0]) > 1e-9 else 1.0
    return float((slope * (len(values) - 1) / baseline) * 100.0)


def compare_windows(points: pd.DataFrame, signals: Iterable[object] | None = None) -> dict[str, object]:
    if points.empty:
        return {
            "new_behavior": False,
            "change_percent": 0.0,
            "summary": "No points available for comparison.",
            "current_mean": 0.0,
            "previous_mean": 0.0,
            "current_max": 0.0,
            "previous_max": 0.0,
            "signal_count_difference": 0,
            "anomaly_count_difference": 0,
            "trend_difference": 0.0,
        }

    ordered = points.sort_values("timestamp").reset_index(drop=True).copy()
    midpoint = max(len(ordered) // 2, 1)
    previous_window = ordered.iloc[:midpoint].copy()
    current_window = ordered.iloc[midpoint:].copy() if midpoint < len(ordered) else ordered.iloc[:midpoint].copy()

    previous_mean = float(previous_window["value"].mean()) if not previous_window.empty else 0.0
    current_mean = float(current_window["value"].mean()) if not current_window.empty else 0.0
    previous_max = float(previous_window["value"].max()) if not previous_window.empty else 0.0
    current_max = float(current_window["value"].max()) if not current_window.empty else 0.0

    change_percent = ((current_mean - previous_mean) / max(abs(previous_mean), 1e-9)) * 100.0 if previous_window is not None else 0.0
    previous_trend = _trend_percent(previous_window["value"])
    current_trend = _trend_percent(current_window["value"])

    previous_signal_count = 0
    current_signal_count = 0
    previous_anomaly_count = 0
    current_anomaly_count = 0
    signal_list = list(signals or [])
    if signal_list:
        boundary = current_window["timestamp"].min() if not current_window.empty else ordered["timestamp"].min()
        for signal in signal_list:
            midpoint_time = signal.start_time + (signal.end_time - signal.start_time) / 2
            if midpoint_time < boundary:
                previous_signal_count += 1
                if signal.signal_type == "anomaly":
                    previous_anomaly_count += 1
            else:
                current_signal_count += 1
                if signal.signal_type == "anomaly":
                    current_anomaly_count += 1

    anomaly_count_difference = current_anomaly_count - previous_anomaly_count
    signal_count_difference = current_signal_count - previous_signal_count
    trend_difference = current_trend - previous_trend
    new_behavior = abs(change_percent) >= 25.0 or anomaly_count_difference > 0 or abs(trend_difference) >= 10.0

    summary = (
        "CPU behaviour differs significantly from the previous day." if new_behavior else "Current behaviour is broadly consistent with the previous window."
    )

    return {
        "new_behavior": bool(new_behavior),
        "change_percent": round(float(change_percent), 4),
        "summary": summary,
        "current_mean": round(current_mean, 4),
        "previous_mean": round(previous_mean, 4),
        "current_max": round(current_max, 4),
        "previous_max": round(previous_max, 4),
        "signal_count_difference": int(signal_count_difference),
        "anomaly_count_difference": int(anomaly_count_difference),
        "trend_difference": round(float(trend_difference), 4),
        "current_signal_count": int(current_signal_count),
        "previous_signal_count": int(previous_signal_count),
        "current_anomaly_count": int(current_anomaly_count),
        "previous_anomaly_count": int(previous_anomaly_count),
        "current_trend_percent": round(float(current_trend), 4),
        "previous_trend_percent": round(float(previous_trend), 4),
    }
