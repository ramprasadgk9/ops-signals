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
    exact: bool = True,
) -> dict[str, float | int] | None:
    """The strongest change point and its score: the step between the two sides' means against the
    noise on each side. With exact, the break is moved to the exact point near Binseg's (see
    _exact_break); without it, Binseg's every-`jump`-th-point break is kept."""
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

    candidates = [
        _exact_break(clean_values, point, jump, min_segment_size) if exact else point
        for point in breakpoints
        if min_segment_size <= point <= len(clean_values) - min_segment_size
    ]
    if not candidates:
        return None

    best: dict[str, float | int] | None = None
    for point in candidates:
        left = clean_values[:point]
        right = clean_values[point:]
        left_mean = float(left.mean())
        right_mean = float(right.mean())
        # The step against the noise on each side of it. The whole series' spread holds the step
        # itself, so it grew with the step: a step halfway through could never score above 2,
        # 50 -> 500 scored the same as 50 -> 54, and a clear 2-sigma shift scored 1.3 (issue #76).
        noise = np.sqrt((len(left) * left.var() + len(right) * right.var()) / len(clean_values))
        score = abs(right_mean - left_mean) / max(float(noise), 1e-9)
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


def _exact_break(values: np.ndarray, point: int, jump: int, min_segment_size: int) -> int:
    """The split within `jump` points of Binseg's that leaves the least spread on either side.
    Binseg only tries every `jump`-th point, so a step at 144 came back as 145, and the one old-level
    reading left on the new side counted as noise: 50 -> 500 scored 17 instead of 225."""
    low = max(min_segment_size, point - jump)
    high = min(len(values) - min_segment_size, point + jump)
    if low >= high:
        return point
    sums = np.concatenate(([0.0], np.cumsum(values)))
    squares = np.concatenate(([0.0], np.cumsum(values**2)))
    splits = np.arange(low, high + 1)
    left_n, right_n = splits, len(values) - splits
    left_ss = squares[splits] - sums[splits] ** 2 / left_n
    right_ss = (squares[-1] - squares[splits]) - (sums[-1] - sums[splits]) ** 2 / right_n
    return int(splits[np.argmin(left_ss + right_ss)])


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
