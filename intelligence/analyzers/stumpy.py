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
    # "motif" reports the series' most repeated stretch; "discord" its most unusual ones.
    mode: str = "motif"
    max_discords: int = 3
    finding_min_surprise: float = 8.0


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
            mode=str(impl.get("mode", "motif")),
            max_discords=max(1, int(impl.get("max_discords", 3))),
            finding_min_surprise=max(0.0, float(rules.get("min_surprise", 8.0))),
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
            if self.config.mode == "discord":
                signals.extend(self._discords(ordered))
                continue
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

    def _discords(self, ordered: pd.DataFrame) -> list[OperationalSignal]:
        """The series' most unusual stretches: the subsequences farthest from their nearest
        neighbour anywhere else in the series (matrix-profile discords, via stumpy's self-join).

        The window is one period of the series, estimated from its autocorrelation, so on a metric
        with a daily cycle a discord is a day unlike the other days. A stretch is reported only
        when its distance stands out from the series' typical nearest-neighbour distance: the
        robust z-score (median/MAD) of the distance - its "surprise" - must reach
        finding_min_surprise. Every series has a most unusual stretch; most of them aren't
        worth a finding. Up to max_discords non-overlapping stretches are reported.

        Needs the stumpy library: without it, nothing is reported (the pairwise fallback used
        for motifs is far too slow for a full self-join)."""
        if _stumpy is None:
            return []
        values = ordered["value"].to_numpy(dtype=float)
        if not np.isfinite(values).all() or np.std(values, ddof=0) == 0:
            return []
        window = min(estimate_period(values), len(values) // 4)
        if window < MIN_DISCORD_WINDOW:
            return []
        try:  # pragma: no cover - optional dependency
            distances = _stumpy.stump(values, m=window)[:, 0].astype(float)
        except Exception:
            return []
        finite = distances[np.isfinite(distances)]
        if not len(finite):
            return []
        median = float(np.median(finite))
        spread = 1.4826 * float(np.median(np.abs(finite - median)))
        if spread <= 1e-12:
            return []
        remaining = np.where(np.isfinite(distances), distances, -np.inf)
        signals: list[OperationalSignal] = []
        metric_name = ordered.iloc[0]["metric_name"]
        for _ in range(self.config.max_discords):
            index = int(np.argmax(remaining))
            if not np.isfinite(remaining[index]):
                break
            surprise = (float(remaining[index]) - median) / spread
            if surprise < self.config.finding_min_surprise:
                break
            remaining[max(0, index - window) : index + window] = -np.inf
            last = min(index + window - 1, len(ordered) - 1)
            signals.append(
                OperationalSignal(
                    signal_type="anomaly",
                    analyzer_id=self.analyzer_id,
                    metric_name=metric_name,
                    service=ordered.iloc[0].get("service"),
                    env=ordered.iloc[0].get("env"),
                    severity="high" if surprise >= self.config.finding_min_surprise * 2 else "medium",
                    confidence=round(min(1.0, surprise / (self.config.finding_min_surprise * 2)), 4),
                    start_time=ordered["timestamp"].iloc[index].to_pydatetime(),
                    end_time=ordered["timestamp"].iloc[last].to_pydatetime(),
                    summary=(
                        f"{metric_name} had a stretch of {window} points unlike anything else in the window "
                        f"({surprise:.1f} times further from its closest match than usual)."
                    ),
                    evidence={
                        "detector": "matrix_profile_discord",
                        "window_size": window,
                        "discord_index": index,
                        "discord_distance": round(float(distances[index]), 4),
                        "typical_distance": round(median, 4),
                        "surprise": round(surprise, 2),
                        # A robust z-score of the discord's distance; importance scoring reads anomalies' size here.
                        "max_abs_zscore": round(surprise, 2),
                        "implementation": {"library": "stumpy", "algorithm": "stump", "mode": "discord", "max_discords": self.config.max_discords},
                        "finding_rules": {"min_surprise": self.config.finding_min_surprise},
                        "finding_rule_matched": True,
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


MIN_DISCORD_WINDOW, MAX_DISCORD_WINDOW, DEFAULT_DISCORD_WINDOW = 16, 1000, 100


def estimate_period(values: np.ndarray, search_points: int = 20_000) -> int:
    """The series' period in points: the first autocorrelation peak after the autocorrelation first
    turns negative, clipped to [MIN_DISCORD_WINDOW, MAX_DISCORD_WINDOW]; DEFAULT_DISCORD_WINDOW when
    the series shows no period. The same estimate the UCR benchmark's discord reference uses."""
    x = np.asarray(values[-search_points:], dtype=float)
    x = x - x.mean()
    if len(x) < 2 * MIN_DISCORD_WINDOW or not np.any(x):
        return DEFAULT_DISCORD_WINDOW
    spectrum = np.fft.rfft(x, n=2 * len(x))
    acf = np.fft.irfft(spectrum * np.conj(spectrum))[: len(x)]
    acf /= acf[0]
    limit = min(len(acf) - 1, MAX_DISCORD_WINDOW * 2)
    negative = np.flatnonzero(acf[1:limit] < 0)
    if not len(negative):
        return DEFAULT_DISCORD_WINDOW
    first = int(negative[0]) + 1
    peak = first + int(np.argmax(acf[first:limit]))
    if acf[peak] <= 0.1:
        return DEFAULT_DISCORD_WINDOW
    return int(np.clip(peak, MIN_DISCORD_WINDOW, MAX_DISCORD_WINDOW))
