from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from intelligence.analyzers.base import Analyzer
from intelligence.capability import Capability
from intelligence.signals.schema import OperationalSignal

try:  # pragma: no cover - optional dependency
    import stumpy as _stumpy
except Exception:  # pragma: no cover - optional dependency
    _stumpy = None


@dataclass(slots=True)
class StumpyConfig:
    window_size: int = 20
    motif_count: int = 1
    profile_threshold: float = 2.0
    library: str = "stumpy"
    algorithm: str = "stump"
    finding_max_motif_distance: float = 1.0
    finding_min_confidence: float = 0.75


class STUMPYAnalyzer(Analyzer):
    analyzer_id = "stumpy"

    def __init__(
        self,
        window_size: int = 20,
        motif_count: int = 1,
        profile_threshold: float = 2.0,
        finding_rules: dict[str, object] | None = None,
        implementation: dict[str, object] | None = None,
    ) -> None:
        rules = finding_rules or {}
        impl = implementation or {}
        window_size = int(impl.get("window_size", window_size))
        motif_count = int(impl.get("motif_count", motif_count))
        profile_threshold = float(impl.get("profile_threshold", profile_threshold))
        self.config = StumpyConfig(
            window_size=max(4, int(window_size)),
            motif_count=max(1, int(motif_count)),
            profile_threshold=float(profile_threshold),
            library=str(impl.get("library", "stumpy")),
            algorithm=str(impl.get("algorithm", "stump")),
            finding_max_motif_distance=max(0.0, float(rules.get("max_motif_distance", 1.0))),
            finding_min_confidence=max(0.0, min(float(rules.get("min_confidence", 0.75)), 1.0)),
        )

    def capability(self) -> Capability:
        return Capability(
            id="pattern_discovery",
            title="Pattern Discovery",
            description="Detects repeated motifs, recurring subsequences, and unusual patterns in regular series.",
            analyzer_id=self.analyzer_id,
            enabled=True,
            supported_question_ids=[
                "what_changed",
                "behavior_novelty",
                "long_term_trends",
                "service_health",
            ],
        )

    def analyze(self, dataframe: pd.DataFrame) -> list[OperationalSignal]:
        signals: list[OperationalSignal] = []
        for _, group in dataframe.groupby(["metric_name", "service", "env"], dropna=False):
            ordered = group.sort_values("timestamp").reset_index(drop=True)
            if len(ordered) < self.config.window_size * 2:
                continue

            values = ordered["value"].to_numpy(dtype=float)
            if np.std(values, ddof=0) == 0:
                continue

            motif_summary = self._detect_motif(values)
            if motif_summary is None:
                continue

            metric_name = ordered.iloc[0]["metric_name"]
            service = ordered.iloc[0].get("service")
            env = ordered.iloc[0].get("env")
            distance = float(motif_summary["distance"])
            confidence = max(0.0, min(1.0, 1.0 - (distance / max(self.config.profile_threshold, 1e-9))))
            severity = "high" if confidence >= 0.75 else "medium"
            signals.append(
                OperationalSignal(
                    signal_type="pattern_discovery",
                    analyzer_id=self.analyzer_id,
                    metric_name=metric_name,
                    service=service,
                    env=env,
                    severity=severity,
                    confidence=confidence,
                    start_time=ordered["timestamp"].min().to_pydatetime(),
                    end_time=ordered["timestamp"].max().to_pydatetime(),
                    summary=(
                        f"{metric_name} showed repeated subsequences and a potential motif around index {motif_summary['index']}."
                    ),
                    evidence={
                        "window_size": self.config.window_size,
                        "motif_index": motif_summary["index"],
                        "motif_distance": round(motif_summary["distance"], 4),
                        "motif_count": self.config.motif_count,
                        "implementation": {
                            "library": self.config.library if _stumpy is not None else "fallback",
                            "algorithm": self.config.algorithm if _stumpy is not None else "pairwise_numpy",
                            "window_size": self.config.window_size,
                            "motif_count": self.config.motif_count,
                            "profile_threshold": self.config.profile_threshold,
                        },
                        "library": self.config.library if _stumpy is not None else "fallback",
                        "algorithm": self.config.algorithm if _stumpy is not None else "pairwise_numpy",
                        "finding_rules": {
                            "max_motif_distance": self.config.finding_max_motif_distance,
                            "min_confidence": self.config.finding_min_confidence,
                        },
                        "finding_rule_matched": (
                            distance <= self.config.finding_max_motif_distance
                            and confidence >= self.config.finding_min_confidence
                        ),
                    },
                )
            )
        return signals

    def _detect_motif(self, values: np.ndarray) -> dict[str, float | int] | None:
        if _stumpy is not None:
            try:  # pragma: no cover - optional dependency
                profile = _stumpy.stump(values, m=self.config.window_size)
                if len(profile) == 0:
                    return None
                index = int(np.nanargmin(profile[:, 0]))
                distance = float(profile[index, 0])
                if np.isnan(distance):
                    return None
                return {"index": index, "distance": distance}
            except Exception:
                return None

        window = self.config.window_size
        best_index = None
        best_distance = float("inf")
        for index in range(0, len(values) - window + 1):
            candidate = values[index : index + window]
            if len(candidate) != window:
                continue
            others = []
            for other_index in range(0, len(values) - window + 1):
                if abs(other_index - index) < window // 2:
                    continue
                other = values[other_index : other_index + window]
                if len(other) != window:
                    continue
                others.append(np.linalg.norm(candidate - other))
            if not others:
                continue
            distance = float(np.min(others))
            if distance < best_distance:
                best_distance = distance
                best_index = index
        if best_index is None or not np.isfinite(best_distance):
            return None
        return {"index": best_index, "distance": best_distance}
