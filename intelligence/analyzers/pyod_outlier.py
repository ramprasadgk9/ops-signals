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
    detector: str = "KNN"
    library: str = "pyod"
    contamination: float = 0.05
    grouping_gap: pd.Timedelta = pd.Timedelta("15m")
    min_samples: int = 50
    finding_min_outlier_points: int = 1
    finding_min_confidence: float = 0.0
    finding_window: pd.Timedelta = pd.Timedelta("15m")


class PyODOutlierAnalyzer(Analyzer):
    analyzer_id = "pyod_outlier"

    def __init__(
        self,
        detector_type: str = "knn",
        contamination: float = 0.05,
        grouping_gap: str = "15m",
        min_samples: int = 50,
        finding_rule: dict[str, object] | None = None,
        implementation: dict[str, object] | None = None,
    ) -> None:
        impl = implementation or {}
        detector_type = str(impl.get("detector_type", detector_type))
        contamination = float(impl.get("contamination", contamination))
        grouping_gap = str(impl.get("grouping_gap", grouping_gap))
        min_samples = int(impl.get("min_samples", min_samples))
        detector = detector_type.lower().strip()
        if detector != "knn":
            raise ValueError("PyODOutlierAnalyzer v1 supports detector_type='knn' only")
        rule = finding_rule or {}
        self.config = PyODOutlierConfig(
            detector_type=detector,
            detector=str(impl.get("detector", "KNN")),
            library=str(impl.get("library", "pyod")),
            contamination=max(1e-6, min(float(contamination), 0.5)),
            grouping_gap=pd.to_timedelta(grouping_gap),
            min_samples=max(3, int(min_samples)),
            finding_min_outlier_points=max(1, int(rule.get("min_outlier_points", 1))),
            finding_min_confidence=max(0.0, min(float(rule.get("min_confidence", 0.0)), 1.0)),
            finding_window=pd.to_timedelta(str(rule.get("window", grouping_gap))),
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
                            "implementation": {
                                "library": self.config.library,
                                "detector": self.config.detector,
                                "detector_type": self.config.detector_type,
                                "contamination": self.config.contamination,
                                "grouping_gap": str(self.config.grouping_gap),
                                "min_samples": self.config.min_samples,
                            },
                            "library": self.config.library,
                            "detector": self.config.detector,
                            "contamination": self.config.contamination,
                            "max_anomaly_score": round(max_score, 6),
                            "point_count": int(len(anomaly_group)),
                            "outlier_indices": [int(index) for index in anomaly_group.index.tolist()],
                            "outlier_timestamps": [timestamp.isoformat() for timestamp in anomaly_group["timestamp"]],
                            "grouping_gap_minutes": self.config.grouping_gap.total_seconds() / 60,
                            "min_samples": self.config.min_samples,
                            "finding_rule": {
                                "min_outlier_points": self.config.finding_min_outlier_points,
                                "min_confidence": self.config.finding_min_confidence,
                                "window": str(self.config.finding_window),
                            },
                            "finding_rule_matched": (
                                int(len(anomaly_group)) >= self.config.finding_min_outlier_points
                                and confidence >= self.config.finding_min_confidence
                            ),
                        },
                    )
                )
        return signals
