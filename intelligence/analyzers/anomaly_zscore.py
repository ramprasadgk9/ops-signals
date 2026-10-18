from __future__ import annotations

import numpy as np
import pandas as pd

from intelligence.analyzers.base import Analyzer
from intelligence.analyzers.ruptures import detect_primary_change_point
from intelligence.capability import Capability
from intelligence.signals.schema import OperationalSignal


def _is_new_level(before: np.ndarray, after: np.ndarray) -> bool:
    """Whether a short tail sits at a new level, rather than at the old level with an outlier in it:
    its typical point is at least 3 robust spreads from the earlier median. A lone spike leaves
    most of the tail where it was."""
    center = float(np.median(before))
    spread = max(1.4826 * float(np.median(np.abs(before - center))), 1e-9)
    return float(np.median(np.abs(after - center))) / spread >= 3.0


class ZScoreAnomalyAnalyzer(Analyzer):
    analyzer_id = "anomaly_zscore"

    def __init__(
        self,
        zscore_threshold: float = 3.0,
        grouping_gap: str = "15m",
        finding_rules: dict[str, object] | None = None,
        implementation: dict[str, object] | None = None,
        rebaseline: dict[str, object] | None = None,
    ) -> None:
        impl = implementation or {}
        rules = finding_rules or {}
        rebase = rebaseline or {}
        zscore_threshold = float(impl.get("zscore_threshold", zscore_threshold))
        grouping_gap = str(impl.get("grouping_gap", grouping_gap))
        self.zscore_threshold = zscore_threshold
        self.grouping_gap = pd.to_timedelta(grouping_gap)
        self.library = str(impl.get("library", "pandas"))
        self.method = str(impl.get("method", "zscore"))
        self.finding_min_abs_zscore = max(0.0, float(rules.get("min_abs_zscore", zscore_threshold)))
        self.finding_min_points = max(1, int(rules.get("min_points", 1)))
        self.rebaseline_enabled = bool(rebase.get("enabled", True))
        self.rebaseline_min_segment_size = max(2, int(rebase.get("min_segment_size", 5)))
        self.rebaseline_change_threshold = float(rebase.get("change_threshold", 1.5))
        self.rebaseline_max_iterations = max(1, int(rebase.get("max_iterations", 5)))

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

    def _most_recent_stable_regime_start(self, values) -> int:
        """Walks forward through successive detected change points to find where the
        most recent stable regime begins.

        A single change point can land inside a still-noisy transition rather than
        at its true start - rebaselining against that segment would be contaminated
        by the transition's own volatility, masking exactly the anomaly a fresh
        baseline should be judged against (observed on real NAB EC2 CPU data: a
        breakpoint landing mid-recovery inflated the post-shift std enough to hide
        the event it was still part of). So each step re-checks the remaining tail
        for a further change point and only stops once none is found.
        """
        start = 0
        for _ in range(self.rebaseline_max_iterations):
            remaining = values[start:]
            if len(remaining) < self.rebaseline_min_segment_size * 2:
                break
            change_point = detect_primary_change_point(
                remaining,
                min_segment_size=self.rebaseline_min_segment_size,
                change_threshold=self.rebaseline_change_threshold,
            )
            if change_point is None:
                break
            start += int(change_point["change_point_index"])
        return start

    def _min_baseline_points(self) -> int:
        """The fewest points a rebaselined segment needs before any reading in it can reach the
        z-score threshold. In n points no value can sit more than (n - 1) / sqrt(n) standard
        deviations from their own mean, so a shorter tail can never flag anything. A fresh spike
        made the change point land 8 points from the end, where the ceiling is 2.47, and the
        30-sigma reading went unreported (QA-31). Such a tail is still rebaselined onto when it is a
        genuine new level (_is_new_level), so a settled shift stops being flagged as before. The
        1.25 margin keeps the threshold within reach."""
        target = self.zscore_threshold * 1.25
        points = 3
        while (points - 1) / points**0.5 < target:
            points += 1
        return points

    def analyze(self, dataframe: pd.DataFrame) -> list[OperationalSignal]:
        signals: list[OperationalSignal] = []
        for _, group in dataframe.groupby(["metric_name", "service", "env"], dropna=False):
            ordered = group.sort_values("timestamp").reset_index(drop=True)
            if len(ordered) < 3:
                continue

            working = ordered
            rebaselined = False
            change_point_index: int | None = None
            if self.rebaseline_enabled:
                start = self._most_recent_stable_regime_start(ordered["value"].to_numpy(dtype=float))
                if start > 0:
                    post_shift = ordered.iloc[start:].reset_index(drop=True)
                    values = ordered["value"].to_numpy(dtype=float)
                    if len(post_shift) >= self.rebaseline_min_segment_size and (
                        len(post_shift) >= self._min_baseline_points() or _is_new_level(values[:start], values[start:])
                    ):
                        working = post_shift
                        rebaselined = True
                        change_point_index = start

            std = float(working["value"].std(ddof=0))
            if std == 0:
                continue
            mean = float(working["value"].mean())
            working = working.copy()
            working["zscore"] = (working["value"] - mean) / std
            anomalies = working[working["zscore"].abs() >= self.zscore_threshold].copy()
            if anomalies.empty:
                continue
            anomalies["group_id"] = (anomalies["timestamp"].diff().gt(self.grouping_gap)).cumsum()
            for _, anomaly_group in anomalies.groupby("group_id"):
                max_abs_z = float(anomaly_group["zscore"].abs().max())
                finding_rule_matched = bool(
                    max_abs_z >= self.finding_min_abs_zscore and len(anomaly_group) >= self.finding_min_points
                )
                severity = "high" if max_abs_z >= self.finding_min_abs_zscore * 1.5 else "medium"
                confidence = min(1.0, max_abs_z / max(self.finding_min_abs_zscore * 2.0, 1e-9))
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
                            "rebaselined_after_change_point": rebaselined,
                            **({"change_point_index": change_point_index} if rebaselined else {}),
                            "implementation": {
                                "library": self.library,
                                "method": self.method,
                                "zscore_threshold": self.zscore_threshold,
                                "grouping_gap": str(self.grouping_gap),
                            },
                            "library": self.library,
                            "method": self.method,
                            "finding_rules": {
                                "min_abs_zscore": self.finding_min_abs_zscore,
                                "min_points": self.finding_min_points,
                            },
                            "finding_rule_matched": finding_rule_matched,
                        },
                    )
                )
        return signals
