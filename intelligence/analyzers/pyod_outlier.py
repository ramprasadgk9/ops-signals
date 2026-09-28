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
    finding_min_range_excess: float = 0.56
    finding_min_sustained_points: int = 8
    finding_window: pd.Timedelta = pd.Timedelta("15m")


class PyODOutlierAnalyzer(Analyzer):
    """Flags outlier points with PyOD's KNN detector and groups nearby ones.

    KNN with a contamination share always marks that share of points as outliers - the top 1% of
    even a perfectly healthy series. So a group becomes a finding (finding_rule_matched) only on one
    of two kinds of evidence:

    - A clear spike: its most extreme value lies beyond the series' normal range (the 5th-95th
      percentile of its values) by at least `min_range_excess` times that range. The default, 0.56,
      is the standard 3.5-standard-deviation outlier cut-off (Iglewicz & Hoaglin, the one
      seasonal_anomaly uses) in those units: on normally distributed data the 5th-95th range spans
      3.29 standard deviations and its edge sits at 1.645, so 3.5 is (3.5 - 1.645) / 3.29 = 0.56
      ranges beyond it. Healthy noise rarely gets that far (about 1 point in 2,000).
    - A sustained unusual stretch: at least `min_sustained_points` outlier points close together
      (within grouping_gap of each other), even when their values stay inside the normal range - the
      kind of anomaly that changes a series' shape rather than its level.

    When most values are identical and the 5th-95th range is empty, the standard deviation stands in
    for it.

    Confidence says how strong the evidence is on an absolute scale: 0.5 exactly at either threshold,
    rising towards 1.0 without reaching it (0.75 at twice the threshold), and below 0.5 when neither
    is met - so stronger outliers always rank above weaker ones. (It used to be the group's KNN score
    divided by the window's largest, so the most unusual point of every window scored 1.0, however
    normal it was.)
    """

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
            finding_min_range_excess=max(0.0, float(rule.get("min_range_excess", 0.56))),
            finding_min_sustained_points=max(2, int(rule.get("min_sustained_points", 8))),
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
            low, high = (float(value) for value in np.percentile(values, [5, 95]))
            width = high - low if high - low > 1e-12 else float(np.std(values, ddof=0))
            ordered["range_excess"] = np.maximum(ordered["value"] - high, low - ordered["value"]).clip(lower=0.0) / width
            anomalies = ordered[ordered["pyod_label"] == 1].copy()
            if anomalies.empty:
                continue

            anomalies["group_id"] = (anomalies["timestamp"].diff().gt(self.config.grouping_gap)).cumsum()
            for _, anomaly_group in anomalies.groupby("group_id"):
                max_score = float(anomaly_group["pyod_score"].max())
                range_excess = float(anomaly_group["range_excess"].max())
                points = int(len(anomaly_group))
                confidence = self._confidence(range_excess, points)
                severity = "high" if confidence >= 0.75 else "medium"
                metric_name = anomaly_group.iloc[0]["metric_name"]
                service = anomaly_group.iloc[0].get("service")
                env = anomaly_group.iloc[0].get("env")
                summary = (
                    f"{metric_name} produced {len(anomaly_group)} PyOD outlier point(s), reaching "
                    f"{range_excess:.2f}x its normal range beyond that range (normally {low:.4g} to {high:.4g})."
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
                            "range_excess": round(range_excess, 4),
                            "normal_range": {"low": round(low, 6), "high": round(high, 6)},
                            "finding_rule": {
                                "min_range_excess": self.config.finding_min_range_excess,
                                "min_sustained_points": self.config.finding_min_sustained_points,
                                "window": str(self.config.finding_window),
                            },
                            "finding_rule_matched": (
                                range_excess >= self.config.finding_min_range_excess
                                or points >= self.config.finding_min_sustained_points
                            ),
                        },
                    )
                )
        return signals

    def _confidence(self, range_excess: float, points: int = 1) -> float:
        """The stronger of the two kinds of evidence, each 0.5 exactly at its threshold."""
        return round(max(_strength(range_excess, self.config.finding_min_range_excess),
                         _strength(float(points), float(self.config.finding_min_sustained_points))), 4)


def _strength(value: float, threshold: float) -> float:
    """Below the threshold, rises linearly from 0 to 0.5; at or above it, 0.5 + 0.5 * (1 - threshold / value),
    so 0.75 at twice the threshold and approaching (never reaching) 1.0 for far stronger evidence."""
    if threshold <= 0:
        return 1.0 if value > 0 else 0.0
    if value < threshold:
        return 0.5 * max(value, 0.0) / threshold
    return 0.5 + 0.5 * (1.0 - threshold / value)
