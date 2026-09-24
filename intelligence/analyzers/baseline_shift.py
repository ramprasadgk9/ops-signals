from __future__ import annotations

import math

import pandas as pd

from intelligence.analyzers.base import Analyzer
from intelligence.analyzers.ruptures import change_point_time, detect_primary_change_point
from intelligence.capability import Capability
from intelligence.signals.schema import OperationalSignal


class BaselineShiftAnalyzer(Analyzer):
    analyzer_id = "baseline_shift"

    def __init__(
        self,
        threshold_percent: float,
        min_segment_size: int = 5,
        change_threshold: float = 1.5,
        ruptures_algorithm: str = "binseg",
        ruptures_model: str = "l2",
        ruptures_jump: int = 5,
        ruptures_n_bkps: int = 1,
    ) -> None:
        self.threshold_percent = threshold_percent
        self.min_segment_size = max(2, int(min_segment_size))
        self.change_threshold = float(change_threshold)
        self.ruptures_algorithm = ruptures_algorithm
        self.ruptures_model = ruptures_model
        self.ruptures_jump = int(ruptures_jump)
        self.ruptures_n_bkps = int(ruptures_n_bkps)

    def capability(self) -> Capability:
        return Capability(
            id="baseline_analysis",
            title="Baseline Analysis",
            description="Detects sustained changes in the normal operating level.",
            analyzer_id=self.analyzer_id,
            enabled=True,
            supported_question_ids=[
                "what_changed",
                "baseline_changes",
                "behavior_novelty",
                "service_health",
            ],
        )

    def analyze(self, dataframe: pd.DataFrame) -> list[OperationalSignal]:
        signals: list[OperationalSignal] = []
        for _, group in dataframe.groupby(["metric_name", "service", "env"], dropna=False):
            ordered = group.sort_values("timestamp").reset_index(drop=True)
            ordered = ordered.copy()
            ordered["value"] = pd.to_numeric(ordered["value"], errors="coerce")
            ordered = ordered.dropna(subset=["value"])
            result = detect_primary_change_point(
                ordered["value"].to_numpy(dtype=float),
                min_segment_size=self.min_segment_size,
                change_threshold=self.change_threshold,
                algorithm=self.ruptures_algorithm,
                model=self.ruptures_model,
                jump=self.ruptures_jump,
                n_bkps=self.ruptures_n_bkps,
            )
            if result is None:
                continue

            first_mean = float(result["left_mean"])
            second_mean = float(result["right_mean"])
            percent_change = float(result["percent_change"])
            score = float(result["score"])
            if not math.isfinite(percent_change):
                continue
            if abs(percent_change) < self.threshold_percent:
                continue
            magnitude = abs(percent_change)
            severity = "high" if magnitude >= self.threshold_percent * 2 else "medium"
            confidence = min(1.0, magnitude / max(self.threshold_percent * 2, 1.0))
            metric_name = ordered.iloc[0]["metric_name"]
            service = ordered.iloc[0].get("service")
            env = ordered.iloc[0].get("env")
            summary = (
                f"{metric_name} baseline shifted by {percent_change:.1f}% around sample {int(result['change_point_index'])}."
            )
            signals.append(
                OperationalSignal(
                    signal_type="baseline_shift",
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
                        "first_half_mean": round(first_mean, 4),
                        "second_half_mean": round(second_mean, 4),
                        "percent_change": round(percent_change, 4),
                        "threshold_percent": self.threshold_percent,
                        "change_point_index": int(result["change_point_index"]),
                        "change_point_time": change_point_time(
                            ordered["timestamp"], ordered["value"], int(result["change_point_index"])
                        ),
                        "score": round(score, 4),
                        "change_threshold": round(self.change_threshold, 4),
                        "min_segment_size": self.min_segment_size,
                        "library": "ruptures",
                        "algorithm": self.ruptures_algorithm,
                        "model": self.ruptures_model,
                        "jump": self.ruptures_jump,
                        "n_bkps": self.ruptures_n_bkps,
                    },
                )
            )
        return signals
