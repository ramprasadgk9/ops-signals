from __future__ import annotations

import pandas as pd

from intelligence.analyzers.base import Analyzer
from intelligence.capability import Capability
from intelligence.signals.schema import OperationalSignal


class ZScoreAnomalyAnalyzer(Analyzer):
    analyzer_id = "anomaly_zscore"

    def __init__(self, zscore_threshold: float, grouping_gap: str) -> None:
        self.zscore_threshold = zscore_threshold
        self.grouping_gap = pd.to_timedelta(grouping_gap)

    def capability(self) -> Capability:
        return Capability(
            id="anomaly_detection",
            title="Anomaly Detection",
            description="Detects unusual behavior windows with statistically significant deviations.",
            analyzer_id=self.analyzer_id,
            enabled=True,
            supported_question_ids=[
                "unusual_activity",
                "investigation_priority",
                "what_changed",
                "service_health",
            ],
        )

    def analyze(self, dataframe: pd.DataFrame) -> list[OperationalSignal]:
        signals: list[OperationalSignal] = []
        for _, group in dataframe.groupby(["metric_name", "service", "env"], dropna=False):
            ordered = group.sort_values("timestamp").reset_index(drop=True)
            if len(ordered) < 3:
                continue
            std = float(ordered["value"].std(ddof=0))
            if std == 0:
                continue
            mean = float(ordered["value"].mean())
            ordered["zscore"] = (ordered["value"] - mean) / std
            anomalies = ordered[ordered["zscore"].abs() >= self.zscore_threshold].copy()
            if anomalies.empty:
                continue
            anomalies["group_id"] = (anomalies["timestamp"].diff().gt(self.grouping_gap)).cumsum()
            for _, anomaly_group in anomalies.groupby("group_id"):
                max_abs_z = float(anomaly_group["zscore"].abs().max())
                severity = "high" if max_abs_z >= self.zscore_threshold * 1.5 else "medium"
                confidence = min(1.0, max_abs_z / (self.zscore_threshold * 2.0))
                metric_name = anomaly_group.iloc[0]["metric_name"]
                service = anomaly_group.iloc[0].get("service")
                env = anomaly_group.iloc[0].get("env")
                summary = (
                    f"{metric_name} produced {len(anomaly_group)} anomalous point(s) with max absolute z-score {max_abs_z:.2f}."
                )
                signals.append(
                    OperationalSignal(
                        signal_type="anomaly",
                        analyzer_id=self.analyzer_id,
                        metric_name=metric_name,
                        service=service,
                        env=env,
                        severity=severity,
                        confidence=confidence,
                        start_time=anomaly_group["timestamp"].min().to_pydatetime(),
                        end_time=anomaly_group["timestamp"].max().to_pydatetime(),
                        summary=summary,
                        evidence={
                            "mean": round(mean, 4),
                            "stddev": round(std, 4),
                            "max_abs_zscore": round(max_abs_z, 4),
                            "point_count": int(len(anomaly_group)),
                            "grouping_gap_minutes": self.grouping_gap.total_seconds() / 60,
                        },
                    )
                )
        return signals
