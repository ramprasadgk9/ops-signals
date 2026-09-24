from __future__ import annotations

import numpy as np
import pandas as pd
import ruptures as rpt

from intelligence.analyzers.base import Analyzer
from intelligence.capability import Capability
from intelligence.signals.schema import OperationalSignal


def detect_primary_change_point(
    values: np.ndarray,
    *,
    min_segment_size: int,
    change_threshold: float,
    algorithm: str = "binseg",
    model: str = "l2",
    jump: int = 5,
    n_bkps: int = 1,
) -> dict[str, float | int] | None:
    if algorithm.lower().strip() != "binseg":
        raise ValueError("Only ruptures algorithm 'binseg' is supported")

    clean_values = np.asarray(values, dtype=float)
    clean_values = clean_values[np.isfinite(clean_values)]
    if len(clean_values) < min_segment_size * 2:
        return None

    signal = clean_values.reshape(-1, 1)
    try:
        breakpoints = (
            rpt.Binseg(model=model, min_size=min_segment_size, jump=jump)
            .fit(signal)
            .predict(n_bkps=n_bkps)
        )
    except rpt.exceptions.BadSegmentationParameters:
        return None

    candidates = [point for point in breakpoints if min_segment_size <= point <= len(clean_values) - min_segment_size]
    if not candidates:
        return None

    scale = max(float(np.std(clean_values, ddof=0)), 1e-9)
    best: dict[str, float | int] | None = None
    for point in candidates:
        left = clean_values[:point]
        right = clean_values[point:]
        left_mean = float(left.mean())
        right_mean = float(right.mean())
        score = abs(right_mean - left_mean) / scale
        if best is None or score > float(best["score"]):
            percent_change = ((right_mean - left_mean) / max(abs(left_mean), 1e-9)) * 100.0
            best = {
                "change_point_index": int(point),
                "left_mean": left_mean,
                "right_mean": right_mean,
                "percent_change": percent_change,
                "score": score,
            }

    if best is None or float(best["score"]) < change_threshold:
        return None
    return best


def change_point_time(timestamps: pd.Series, values: pd.Series, change_point_index: int) -> str | None:
    """ISO timestamp of the first sample after the break.

    detect_primary_change_point() indexes into the *finite* values only, so the index is mapped
    back through the same filter rather than used directly against the (possibly NaN-holed) frame.
    """
    finite = np.isfinite(pd.to_numeric(values, errors="coerce").to_numpy(dtype=float))
    finite_timestamps = pd.to_datetime(timestamps.to_numpy()[finite], utc=True)
    if not 0 <= change_point_index < len(finite_timestamps):
        return None
    return finite_timestamps[change_point_index].isoformat()


class RupturesAnalyzer(Analyzer):
    analyzer_id = "ruptures"

    def __init__(self, min_segment_size: int, change_threshold: float) -> None:
        self.min_segment_size = max(2, int(min_segment_size))
        self.change_threshold = float(change_threshold)
        self.algorithm = "binseg"
        self.model = "l2"
        self.jump = 5
        self.n_bkps = 1

    def capability(self) -> Capability:
        return Capability(
            id="change_point_analysis",
            title="Change Point Analysis",
            description="Detects persistent changes in the metric baseline.",
            analyzer_id=self.analyzer_id,
            enabled=True,
            supported_question_ids=[
                "what_changed",
                "baseline_changes",
                "behavior_novelty",
                "service_health",
                "long_term_trends",
            ],
        )

    def analyze(self, dataframe: pd.DataFrame) -> list[OperationalSignal]:
        signals: list[OperationalSignal] = []
        for _, group in dataframe.groupby(["metric_name", "service", "env"], dropna=False):
            ordered = group.sort_values("timestamp").reset_index(drop=True)
            if len(ordered) < self.min_segment_size * 2:
                continue

            result = detect_primary_change_point(
                ordered["value"].to_numpy(dtype=float),
                min_segment_size=self.min_segment_size,
                change_threshold=self.change_threshold,
                algorithm=self.algorithm,
                model=self.model,
                jump=self.jump,
                n_bkps=self.n_bkps,
            )
            if result is None:
                continue

            best_index = int(result["change_point_index"])
            best_score = float(result["score"])
            left_mean = float(result["left_mean"])
            right_mean = float(result["right_mean"])
            percent_change = float(result["percent_change"])
            severity = "high" if best_score >= self.change_threshold * 1.5 else "medium"
            confidence = min(1.0, best_score / max(self.change_threshold * 2.0, 1.0))
            metric_name = ordered.iloc[0]["metric_name"]
            service = ordered.iloc[0].get("service")
            env = ordered.iloc[0].get("env")
            summary = f"{metric_name} showed a persistent baseline shift of {percent_change:.1f}% around sample {best_index}."

            signals.append(
                OperationalSignal(
                    signal_type="ruptures",
                    analyzer_id=self.analyzer_id,
                    metric_name=metric_name,
                    service=service,
                    env=env,
                    severity=severity,
                    confidence=confidence,
                    start_time=ordered["timestamp"].min().to_pydatetime(),
                    end_time=ordered["timestamp"].max().to_pydatetime(),
                    summary=summary,
                    evidence={
                        "change_point_index": int(best_index),
                        "change_point_time": change_point_time(ordered["timestamp"], ordered["value"], best_index),
                        "left_mean": round(left_mean, 4),
                        "right_mean": round(right_mean, 4),
                        "percent_change": round(percent_change, 4),
                        "score": round(float(best_score), 4),
                        "threshold": round(self.change_threshold, 4),
                        "min_segment_size": self.min_segment_size,
                        "library": "ruptures",
                        "algorithm": self.algorithm,
                        "model": self.model,
                        "jump": self.jump,
                        "n_bkps": self.n_bkps,
                    },
                )
            )
        return signals
