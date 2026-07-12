from __future__ import annotations

import math

import pandas as pd

from ops_signals.analyzers.base import Analyzer
from ops_signals.capability import Capability
from ops_signals.signals.schema import OperationalSignal


class BaselineShiftAnalyzer(Analyzer):
    analyzer_id = "baseline_shift"

    def __init__(self, threshold_percent: float) -> None:
        self.threshold_percent = threshold_percent

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
            if len(ordered) < 4:
                continue
            midpoint = len(ordered) // 2
            first_half = ordered.iloc[:midpoint]
            second_half = ordered.iloc[midpoint:]
            first_mean = float(first_half["value"].mean())
            second_mean = float(second_half["value"].mean())
            if math.isclose(first_mean, 0.0, abs_tol=1e-9):
                continue
            percent_change = ((second_mean - first_mean) / abs(first_mean)) * 100.0
            if abs(percent_change) < self.threshold_percent:
                continue
            magnitude = abs(percent_change)
            severity = "high" if magnitude >= self.threshold_percent * 2 else "medium"
            confidence = min(1.0, magnitude / max(self.threshold_percent * 2, 1.0))
            metric_name = ordered.iloc[0]["metric_name"]
            service = ordered.iloc[0].get("service")
            env = ordered.iloc[0].get("env")
            summary = (
                f"{metric_name} baseline shifted by {percent_change:.1f}% between the first and second half of the batch window."
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
                    },
                )
            )
        return signals
