from __future__ import annotations

import numpy as np
import pandas as pd

from intelligence.analyzers.base import Analyzer
from intelligence.capability import Capability
from intelligence.signals.schema import OperationalSignal


class RupturesAnalyzer(Analyzer):
    analyzer_id = "ruptures"

    def __init__(self, min_segment_size: int, change_threshold: float) -> None:
        self.min_segment_size = max(2, int(min_segment_size))
        self.change_threshold = float(change_threshold)

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

            values = ordered["value"].to_numpy(dtype=float)
            best_index = None
            best_score = 0.0
            scale = max(float(np.std(values, ddof=0)), 1e-9)

            for index in range(self.min_segment_size, len(values) - self.min_segment_size + 1):
                left = values[:index]
                right = values[index:]
                score = abs(float(right.mean()) - float(left.mean())) / scale
                if score > best_score:
                    best_score = score
                    best_index = index

            if best_index is None or best_score < self.change_threshold:
                continue

            left = values[:best_index]
            right = values[best_index:]
            left_mean = float(left.mean())
            right_mean = float(right.mean())
            percent_change = ((right_mean - left_mean) / max(abs(left_mean), 1e-9)) * 100.0
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
                        "left_mean": round(left_mean, 4),
                        "right_mean": round(right_mean, 4),
                        "percent_change": round(percent_change, 4),
                        "score": round(float(best_score), 4),
                        "threshold": round(self.change_threshold, 4),
                        "min_segment_size": self.min_segment_size,
                    },
                )
            )
        return signals
