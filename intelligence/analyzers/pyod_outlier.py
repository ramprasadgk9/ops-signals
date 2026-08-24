from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from pyod.models.knn import KNN

from intelligence.analyzers.base import Analyzer
from intelligence.capability import Capability
from intelligence.signals.schema import OperationalSignal


@dataclass(slots=True)
class PyODOutlierConfig:
    detector_type: str = "knn"
    contamination: float = 0.05
    grouping_gap: pd.Timedelta = pd.Timedelta("15m")
    min_samples: int = 50


class PyODOutlierAnalyzer(Analyzer):
    analyzer_id = "pyod_outlier"

    def __init__(
        self,
        detector_type: str = "knn",
        contamination: float = 0.05,
        grouping_gap: str = "15m",
        min_samples: int = 50,
    ) -> None:
        detector = detector_type.lower().strip()
        if detector != "knn":
            raise ValueError("PyODOutlierAnalyzer v1 supports detector_type='knn' only")
        self.config = PyODOutlierConfig(
            detector_type=detector,
            contamination=max(1e-6, min(float(contamination), 0.5)),
            grouping_gap=pd.to_timedelta(grouping_gap),
            min_samples=max(3, int(min_samples)),
        )

    def capability(self) -> Capability:
        return Capability(
            id="pyod_outlier_detection",
            title="PyOD Outlier Detection",
            description="Detects advanced outliers and unusual metric points using PyOD.",
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
            ordered = group.sort_values("timestamp").reset_index(drop=True).copy()
            ordered["value"] = pd.to_numeric(ordered["value"], errors="coerce")
            ordered = ordered.dropna(subset=["value"])
            if len(ordered) < self.config.min_samples:
                continue

            values = ordered["value"].to_numpy(dtype=float)
            if not np.isfinite(values).all() or np.std(values, ddof=0) == 0:
                continue

            features = values.reshape(-1, 1)
            detector = KNN(contamination=self.config.contamination)
            detector.fit(features)
            labels = detector.labels_
            scores = detector.decision_scores_
            if labels is None or scores is None:
                continue

            ordered["pyod_label"] = labels.astype(int)
            ordered["pyod_score"] = scores.astype(float)
            anomalies = ordered[ordered["pyod_label"] == 1].copy()
            if anomalies.empty:
                continue

            anomalies["group_id"] = (anomalies["timestamp"].diff().gt(self.config.grouping_gap)).cumsum()
            for _, anomaly_group in anomalies.groupby("group_id"):
                max_score = float(anomaly_group["pyod_score"].max())
                score_scale = max(float(np.nanmax(scores)), 1e-9)
                confidence = min(1.0, max_score / score_scale)
                severity = "high" if confidence >= 0.75 else "medium"
                metric_name = anomaly_group.iloc[0]["metric_name"]
                service = anomaly_group.iloc[0].get("service")
                env = anomaly_group.iloc[0].get("env")
                summary = (
                    f"{metric_name} produced {len(anomaly_group)} PyOD outlier point(s) "
                    f"with max anomaly score {max_score:.4f}."
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
                            "library": "pyod",
                            "detector": "KNN",
                            "contamination": self.config.contamination,
                            "max_anomaly_score": round(max_score, 6),
                            "point_count": int(len(anomaly_group)),
                            "grouping_gap_minutes": self.config.grouping_gap.total_seconds() / 60,
                            "min_samples": self.config.min_samples,
                        },
                    )
                )
        return signals
