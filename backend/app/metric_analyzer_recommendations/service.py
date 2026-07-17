from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import isclose
from statistics import mean, pstdev, pvariance
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.entities import NormalizedPoint


@dataclass(slots=True)
class MetricProfile:
    sample_count: int
    start_time: Any
    end_time: Any
    sampling_interval_seconds: int | None
    regular_sampling: bool
    missing_ratio: float
    duplicate_timestamps: int
    constant_value_ratio: float
    mean: float
    stddev: float
    minimum: float
    maximum: float
    variance: float
    trend_slope: float
    trend_strength: float
    autocorrelation: float | None
    seasonality_strength: float
    sparsity: float
    metric_behavior: str


class MetricAnalyzerRecommendationService:
    GOAL_KEYWORDS: dict[str, tuple[str, str]] = {
        "trend": ("detect_trend", "Detect Trend"),
        "increasing": ("detect_trend", "Detect Trend"),
        "rising": ("detect_trend", "Detect Trend"),
        "baseline": ("detect_baseline_shift", "Detect Baseline Shift"),
        "shift": ("detect_baseline_shift", "Detect Baseline Shift"),
        "change": ("detect_baseline_shift", "Detect Baseline Shift"),
        "anomal": ("detect_anomaly", "Detect Anomaly"),
        "spike": ("detect_anomaly", "Detect Anomaly"),
        "repeat": ("detect_repeated_pattern", "Detect Repeated Pattern"),
        "pattern": ("detect_repeated_pattern", "Detect Repeated Pattern"),
        "forecast": ("forecast_future", "Forecast Future"),
        "predict": ("forecast_future", "Forecast Future"),
        "exhaust": ("detect_resource_exhaustion", "Detect Resource Exhaustion"),
        "season": ("detect_seasonality", "Detect Seasonality"),
        "variance": ("detect_variance_change", "Detect Variance Change"),
    }

    def list_samples(self, db: Session) -> list[dict[str, Any]]:
        rows = db.execute(
            select(
                NormalizedPoint.service,
                NormalizedPoint.metric_name,
                NormalizedPoint.analysis_run_id,
                NormalizedPoint.timestamp,
                NormalizedPoint.value,
            ).order_by(NormalizedPoint.timestamp.asc())
        ).all()
        grouped: dict[tuple[str, str, str | None], list[tuple[Any, float]]] = {}
        for service, metric_name, analysis_run_id, timestamp, value in rows:
            key = (service or "unknown", metric_name, analysis_run_id)
            grouped.setdefault(key, []).append((timestamp, float(value)))
        samples = []
        for (service, metric_name, analysis_run_id), values in grouped.items():
            timestamps = [stamp for stamp, _ in values]
            numeric = [val for _, val in values]
            samples.append(
                {
                    "service": service,
                    "metric_name": metric_name,
                    "analysis_run_id": analysis_run_id,
                    "sample_count": len(values),
                    "start_time": min(timestamps),
                    "end_time": max(timestamps),
                    "sampling_interval_seconds": self._infer_interval_seconds(timestamps),
                    "missing_ratio": 0.0,
                    "min_value": min(numeric),
                    "max_value": max(numeric),
                    "mean_value": mean(numeric),
                    "stddev_value": pstdev(numeric) if len(numeric) > 1 else 0.0,
                }
            )
        return samples

    def profile_sample(self, db: Session, service: str, metric_name: str, analysis_run_id: str | None = None) -> tuple[MetricProfile, list[tuple[Any, float]]]:
        query = select(NormalizedPoint).where(
            NormalizedPoint.service == service,
            NormalizedPoint.metric_name == metric_name,
        )
        if analysis_run_id:
            query = query.where(NormalizedPoint.analysis_run_id == analysis_run_id)
        points = db.execute(query.order_by(NormalizedPoint.timestamp.asc())).scalars().all()
        if not points:
            raise ValueError("sample not found")
        timestamps = [point.timestamp for point in points]
        values = [float(point.value) for point in points]
        duplicate_timestamps = len(timestamps) - len(set(timestamps))
        interval = self._infer_interval_seconds(timestamps)
        regular_sampling = self._is_regular(timestamps, interval)
        missing_ratio = self._missing_ratio(timestamps, interval)
        constant_value_ratio = self._constant_ratio(values)
        x = np.arange(len(values), dtype=float)
        y = np.array(values, dtype=float)
        slope = float(np.polyfit(x, y, 1)[0]) if len(values) >= 2 else 0.0
        trend_strength = min(1.0, abs(slope) / (abs(mean(values)) + 1e-9))
        autocorrelation = self._autocorrelation(values)
        seasonality_strength = self._seasonality_strength(values)
        metric_behavior = self._classify_metric_behavior(values, regular_sampling)
        profile = MetricProfile(
            sample_count=len(points),
            start_time=min(timestamps),
            end_time=max(timestamps),
            sampling_interval_seconds=interval,
            regular_sampling=regular_sampling,
            missing_ratio=missing_ratio,
            duplicate_timestamps=duplicate_timestamps,
            constant_value_ratio=constant_value_ratio,
            mean=float(mean(values)),
            stddev=float(pstdev(values)) if len(values) > 1 else 0.0,
            minimum=float(min(values)),
            maximum=float(max(values)),
            variance=float(pvariance(values)) if len(values) > 1 else 0.0,
            trend_slope=slope,
            trend_strength=trend_strength,
            autocorrelation=autocorrelation,
            seasonality_strength=seasonality_strength,
            sparsity=1.0 - min(1.0, len(points) / max(len(points), 1)),
            metric_behavior=metric_behavior,
        )
        return profile, list(zip(timestamps, values))

    def recommend(self, profile: MetricProfile) -> list[dict[str, Any]]:
        candidates = [
            self._ruptures(profile),
            self._trend(profile),
            self._baseline_shift(profile),
            self._anomaly(profile),
            self._stumpy(profile),
            self._forecast(profile),
        ]
        return candidates

    def normalize_goals(self, texts: list[str]) -> list[dict[str, str]]:
        normalized: dict[str, dict[str, str]] = {}
        for text in texts:
            lower = text.lower()
            matched = False
            for needle, (goal_id, display_name) in self.GOAL_KEYWORDS.items():
                if needle in lower:
                    normalized[goal_id] = {"goal_id": goal_id, "display_name": display_name, "source_text": text}
                    matched = True
                    break
            if not matched:
                normalized.setdefault(
                    "detect_trend",
                    {"goal_id": "detect_trend", "display_name": "Detect Trend", "source_text": text},
                )
        return list(normalized.values())

    def context_hash(self, context: dict[str, Any], sample_signature: str | None = None) -> str:
        payload = {k: context.get(k) for k in sorted(context.keys())}
        if sample_signature:
            payload["sample_signature"] = sample_signature
        return sha256(repr(payload).encode("utf-8")).hexdigest()

    def _trend(self, profile: MetricProfile) -> dict[str, Any]:
        fitness = max(0.0, min(1.0, profile.trend_strength * 0.9 + (0.1 if profile.metric_behavior in {"gauge", "latency", "duration"} else 0.0)))
        decision = "recommended" if fitness >= 0.75 else "conditional" if fitness >= 0.5 else "not_recommended"
        return self._result("trend", "Trend Analyzer", fitness, decision, "Useful when the series has a stable directional change.", {
            "trend_slope": round(profile.trend_slope, 6),
            "trend_strength": round(profile.trend_strength, 4),
            "regular_sampling": profile.regular_sampling,
        }, [], [], {"min_slope_percent": 10})

    def _baseline_shift(self, profile: MetricProfile) -> dict[str, Any]:
        fitness = 1.0 - min(1.0, profile.constant_value_ratio + profile.missing_ratio)
        decision = "recommended" if profile.variance > 0 and fitness >= 0.7 else "conditional" if fitness >= 0.45 else "not_recommended"
        return self._result("baseline_shift", "Baseline Shift Analyzer", fitness, decision, "Useful when the metric shows a sustained level change.", {
            "constant_value_ratio": round(profile.constant_value_ratio, 4),
            "missing_ratio": round(profile.missing_ratio, 4),
            "variance": round(profile.variance, 4),
        }, [], [], {"threshold_percent": 25})

    def _ruptures(self, profile: MetricProfile) -> dict[str, Any]:
        fitness = max(0.0, min(1.0, 0.55 + (0.35 if profile.variance > 0.01 else 0.0) + (0.1 if profile.missing_ratio < 0.1 else 0.0)))
        decision = "recommended" if fitness >= 0.75 else "conditional" if fitness >= 0.5 else "not_recommended"
        return self._result("ruptures", "Ruptures", fitness, decision, "Useful when the series has persistent regime or baseline changes.", {
            "variance": round(profile.variance, 4),
            "missing_ratio": round(profile.missing_ratio, 4),
            "regular_sampling": profile.regular_sampling,
            "trend_strength": round(profile.trend_strength, 4),
        }, ["Needs enough history to compare regimes"], [], {"min_segment_size": 5, "change_threshold": 1.5})

    def _anomaly(self, profile: MetricProfile) -> dict[str, Any]:
        fitness = min(1.0, (1.0 - profile.constant_value_ratio) * 0.7 + profile.stddev / (abs(profile.mean) + 1e-9) * 0.3)
        decision = "recommended" if fitness >= 0.7 else "conditional" if fitness >= 0.5 else "not_recommended"
        return self._result("anomaly_zscore", "Anomaly Z-Score Analyzer", fitness, decision, "Useful when the series has variance and isolated spikes.", {
            "stddev": round(profile.stddev, 4),
            "mean": round(profile.mean, 4),
            "constant_value_ratio": round(profile.constant_value_ratio, 4),
        }, [], [], {"zscore_threshold": 3.0})

    def _stumpy(self, profile: MetricProfile) -> dict[str, Any]:
        fitness = max(0.0, min(1.0, profile.seasonality_strength * 0.8 + (0.2 if profile.regular_sampling and profile.sample_count >= 20 else 0.0)))
        decision = "recommended" if fitness >= 0.75 else "conditional" if fitness >= 0.5 else "not_recommended"
        return self._result("stumpy", "STUMPY", fitness, decision, "Useful when repeated motifs or recurring patterns are present.", {
            "seasonality_strength": round(profile.seasonality_strength, 4),
            "regular_sampling": profile.regular_sampling,
        }, ["Best with dense regular samples"], [], {"window": 60})

    def _forecast(self, profile: MetricProfile) -> dict[str, Any]:
        fitness = max(0.0, min(1.0, 0.4 + (0.3 if profile.sample_count >= 50 else 0.0) + (0.3 if profile.seasonality_strength > 0.4 else 0.0)))
        decision = "recommended" if fitness >= 0.75 else "conditional" if fitness >= 0.5 else "not_recommended"
        return self._result("forecasting", "Forecasting", fitness, decision, "Useful when the metric has enough history and a stable seasonal signal.", {
            "sample_count": profile.sample_count,
            "seasonality_strength": round(profile.seasonality_strength, 4),
        }, ["Needs more history for high confidence"], [], {"backtest": "naive_baseline"})

    def _result(self, analyzer_id: str, display_name: str, fitness: float, recommendation: str, summary: str, evidence: dict[str, Any], requirements: list[str], warnings: list[str], parameters_tested: dict[str, Any]) -> dict[str, Any]:
        decision_confidence = round(min(1.0, 0.55 + fitness * 0.45), 4)
        return {
            "analyzer_id": analyzer_id,
            "display_name": display_name,
            "recommendation": recommendation,
            "fitness_score": round(fitness, 4),
            "decision_confidence": decision_confidence,
            "summary": summary,
            "evidence": evidence,
            "requirements": requirements,
            "warnings": warnings,
            "parameters_tested": parameters_tested,
        }

    @staticmethod
    def _infer_interval_seconds(timestamps: list[Any]) -> int | None:
        if len(timestamps) < 2:
            return None
        diffs = sorted(int((timestamps[idx] - timestamps[idx - 1]).total_seconds()) for idx in range(1, len(timestamps)))
        return int(diffs[len(diffs) // 2])

    @staticmethod
    def _is_regular(timestamps: list[Any], interval: int | None) -> bool:
        if interval is None or len(timestamps) < 3:
            return False
        return all(isclose((timestamps[idx] - timestamps[idx - 1]).total_seconds(), interval, rel_tol=0.05, abs_tol=1.0) for idx in range(1, len(timestamps)))

    @staticmethod
    def _missing_ratio(timestamps: list[Any], interval: int | None) -> float:
        if interval is None or len(timestamps) < 2:
            return 0.0
        span = (timestamps[-1] - timestamps[0]).total_seconds()
        expected = max(1, int(span // interval) + 1)
        return max(0.0, min(1.0, 1.0 - (len(timestamps) / expected)))

    @staticmethod
    def _constant_ratio(values: list[float]) -> float:
        if not values:
            return 0.0
        return sum(1 for value in values if isclose(value, values[0], rel_tol=0.0, abs_tol=1e-9)) / len(values)

    @staticmethod
    def _autocorrelation(values: list[float]) -> float | None:
        if len(values) < 4:
            return None
        arr = np.asarray(values, dtype=float)
        return float(np.corrcoef(arr[:-1], arr[1:])[0, 1])

    @staticmethod
    def _seasonality_strength(values: list[float]) -> float:
        if len(values) < 8:
            return 0.0
        arr = np.asarray(values, dtype=float)
        lag = max(2, min(24, len(arr) // 4))
        if len(arr) <= lag:
            return 0.0
        corr = np.corrcoef(arr[:-lag], arr[lag:])[0, 1]
        if np.isnan(corr):
            return 0.0
        return float(max(0.0, min(1.0, abs(corr))))

    @staticmethod
    def _classify_metric_behavior(values: list[float], regular_sampling: bool) -> str:
        if not values:
            return "unknown"
        if regular_sampling and all(curr >= prev for prev, curr in zip(values, values[1:])):
            return "counter"
        spread = max(values) - min(values)
        if spread == 0:
            return "constant"
        return "gauge"
