from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import logging
from math import isclose, isfinite
from pathlib import Path
from statistics import mean, pstdev, pvariance
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from experiments.analyzer_router.analyzer_registry import AnalyzerRegistry
from experiments.analyzer_router.feature_extractor import _shift_index, _spikiness
from experiments.analyzer_router.router import UniversalTimeSeriesRouter

from backend.app.ai.factory import OptionalAIServices
from backend.app.metric_analyzer_recommendations.gemma_advisor import GemmaAnalyzerAdvisor
from backend.app.models.entities import NormalizedPoint

logger = logging.getLogger(__name__)


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
    def __init__(self, registry_path: str | None = None) -> None:
        self.registry_path = registry_path
        self.router = self._build_router()

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
            numeric = self._finite_values([val for _, val in values])
            if not numeric:
                continue
            samples.append(
                {
                    "service": service,
                    "metric_name": metric_name,
                    "analysis_run_id": analysis_run_id,
                    "sample_count": len(values),
                    "start_time": min(timestamps),
                    "end_time": max(timestamps),
                    "sampling_interval_seconds": self._infer_interval_seconds(timestamps),
                    "missing_ratio": 1.0 - (len(numeric) / max(len(values), 1)),
                    "min_value": min(numeric),
                    "max_value": max(numeric),
                    "mean_value": mean(numeric),
                    "stddev_value": pstdev(numeric) if len(numeric) > 1 else 0.0,
                }
            )
        return samples

    def find_sample(self, db: Session, service: str, metric_name: str, analysis_run_id: str | None = None) -> dict[str, Any] | None:
        """The stored sample for this service and metric: the given run's, or, when no run id is
        given, the most recent run's. The run id is optional in the API, but without this every
        call that left it out was a 404: no sample has a run id of None."""
        matches = [
            sample
            for sample in self.list_samples(db)
            if sample["service"] == service and sample["metric_name"] == metric_name
        ]
        if analysis_run_id is not None:
            return next((sample for sample in matches if sample["analysis_run_id"] == analysis_run_id), None)
        return max(matches, key=lambda sample: sample["end_time"], default=None)

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
        finite_points = [(point.timestamp, float(point.value)) for point in points if isfinite(float(point.value))]
        if not finite_points:
            raise ValueError("sample has no finite numeric values")
        timestamps = [timestamp for timestamp, _ in finite_points]
        values = [value for _, value in finite_points]
        duplicate_timestamps = len(timestamps) - len(set(timestamps))
        interval = self._infer_interval_seconds(timestamps)
        regular_sampling = self._is_regular(timestamps, interval)
        missing_ratio = max(self._missing_ratio(timestamps, interval), 1.0 - (len(values) / max(len(points), 1)))
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

    def recommend(
        self,
        profile: MetricProfile,
        selection_mode: str = "all",
        selected_analyzers: list[str] | None = None,
        timeseries: list[tuple[Any, float]] | None = None,
    ) -> list[dict[str, Any]]:
        router = self._build_router()
        router_profile = self._build_router_profile(profile, timeseries, router)
        decisions = router.recommend_analyzers_for_profile(router_profile)
        selected = set(selected_analyzers or [])
        mode = selection_mode.lower().strip()
        if mode == "recommended_only":
            decisions = [decision for decision in decisions if decision.recommendation == "RECOMMENDED"]
        elif mode == "manual_override" and selected:
            decisions = [
                decision
                for decision in decisions
                if decision.recommendation == "RECOMMENDED" or decision.analyzer in selected
            ]
        return [
            {
                "analyzer_id": self._public_analyzer_id(decision.analyzer),
                "display_name": decision.display_name,
                "recommendation": decision.recommendation.lower(),
                "fitness_score": decision.final_score,
                "decision_confidence": min(1.0, 0.55 + decision.final_score * 0.45),
                "summary": decision.explanation,
                "evidence": {"reasons": decision.reasons, "warnings": decision.warnings},
                "requirements": self._requirements_list(decision.parameters_tested.get("eligibility_rules", {})),
                "warnings": decision.warnings,
                "parameters_tested": decision.parameters_tested,
            }
            for decision in decisions
        ]

    def _build_router_profile(
        self,
        profile: MetricProfile,
        timeseries: list[tuple[Any, float]] | None = None,
        router: UniversalTimeSeriesRouter | None = None,
    ) -> Any:
        # With real sample data, profile it exactly the way a real analysis run does (the router's
        # own profile_dataframe -> feature_extractor.extract_series_profile), so this page gives
        # the same advice analysis would. That profile carries detected_profiles (baseline_shift,
        # trend, spike, ...), which the router's profile-match step needs: without it, every
        # analyzer restricted to specific behaviors scored as "did not match" and came back
        # not_recommended - including ruptures on an obvious regime shift.
        if timeseries:
            frame = pd.DataFrame({"timestamp": [ts for ts, _ in timeseries], "value": [value for _, value in timeseries]})
            validation, series_profile, _ = (router or self._build_router()).profile_dataframe(frame, "timestamp", "value")
            if validation.valid:
                return series_profile
        return self._fallback_router_profile(profile, timeseries)

    @staticmethod
    def _fallback_router_profile(profile: MetricProfile, timeseries: list[tuple[Any, float]] | None = None) -> Any:
        # Used only when there's no real series to profile (the preliminary chat path, which has
        # no underlying data at all) or the extractor rejects it. It has no detected_profiles, so
        # behavior-restricted analyzers can't match - acceptable for a preliminary estimate only.
        # spikiness and shift_index are the two features the router's scoring rules lean on most
        # heavily (they drive most of pyod_outlier's and ruptures' score). Computed here from the
        # real values via the same functions the production analysis pipeline uses
        # (experiments/analyzer_router/feature_extractor.py), instead of the workbench inventing
        # its own approximation - previously spikiness was hardcoded to 0.0 (never computed at
        # all) and shift_index was a crude variance/mean ratio that can't distinguish "there's a
        # real change point" from "this series is just noisy". Falls back to conservative defaults
        # only when there's no real series to compute from (e.g. the preliminary chat profile,
        # which has no underlying data at all).
        spikiness = 0.0
        shift_index = min(1.0, max(0.0, profile.variance / (abs(profile.mean) + 1e-9)))
        if timeseries:
            values = np.array([value for _, value in timeseries], dtype=float)
            if len(values) >= 8:
                spikiness, _, _ = _spikiness(values)
            shift_index = _shift_index(values)

        return type(
            "RouterProfile",
            (),
            {
                "sample_count": profile.sample_count,
                "valid_sample_count": profile.sample_count,
                "regular_sampling": profile.regular_sampling,
                "missing_percentage": profile.missing_ratio * 100.0,
                "irregular_sampling_percentage": profile.missing_ratio * 100.0,
                "constant_value_percentage": profile.constant_value_ratio * 100.0,
                "mean": profile.mean,
                "stddev": profile.stddev,
                "minimum": profile.minimum,
                "maximum": profile.maximum,
                "variance": profile.variance,
                "trend_slope": profile.trend_slope,
                "trend_strength": profile.trend_strength,
                "autocorrelation": profile.autocorrelation,
                "seasonality_strength": profile.seasonality_strength,
                "spikiness": spikiness,
                "shift_index": shift_index,
                "duration_seconds": int((profile.end_time - profile.start_time).total_seconds()) if profile.start_time and profile.end_time else None,
                "notes": [],
            },
        )()

    def recommend_ai_opinion(
        self,
        profile: MetricProfile,
        timeseries: list[tuple[Any, float]],
        ai_services: OptionalAIServices | None,
        metric_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Independent second opinion from an optional LLM advisor (Design B) - computed alongside,
        never instead of, recommend()'s deterministic output. The rule-based scores/eligibility/
        thresholds remain the sole authority over what actually executes; this can never change
        that. Returns available=False (never a fabricated opinion) whenever AI is off, or the
        advisor call fails for any reason - callers must always be ready to show just recommend()'s
        output on its own."""
        if not ai_services:
            return {"available": False, "unavailable_reason": "AI assistance is not configured"}

        router = self._build_router()
        router_profile = self._build_router_profile(profile, timeseries, router)
        decisions = router.recommend_analyzers_for_profile(router_profile)
        eligible_decisions = [decision for decision in decisions if decision.eligible] or decisions
        router_top = max(eligible_decisions, key=lambda decision: decision.final_score, default=None)

        try:
            result = GemmaAnalyzerAdvisor(ai_services.structured).recommend(
                profile=router_profile,
                timeseries=timeseries,
                analyzer_decisions=decisions,
                metric_context=metric_context,
            )
        except Exception as exc:
            logger.warning("Gemma analyzer advisor failed, falling back to rule-based recommendations only: %s", exc)
            return {"available": False, "unavailable_reason": "AI advisor call failed"}

        diverges = bool(router_top) and result.best_analyzer_id != router_top.analyzer
        return {
            "available": True,
            "best_analyzer_id": self._public_analyzer_id(result.best_analyzer_id),
            "rationale": result.rationale,
            "recommended": [self._to_ai_pick_dict(pick) for pick in result.recommended],
            "not_recommended": [self._to_ai_pick_dict(pick) for pick in result.not_recommended],
            "caveats": result.caveats,
            "diverges_from_router": diverges,
            "router_top_analyzer_id": self._public_analyzer_id(router_top.analyzer) if router_top else None,
        }

    @classmethod
    def _to_ai_pick_dict(cls, pick: Any) -> dict[str, Any]:
        return {
            "analyzer_id": cls._public_analyzer_id(pick.analyzer_id),
            "recommendation": pick.recommendation,
            "rank": pick.rank,
            "confidence": pick.confidence,
            "reason": pick.reason,
        }

    @staticmethod
    def _public_analyzer_id(analyzer_id: str) -> str:
        if analyzer_id == "trend_regression":
            return "trend"
        return analyzer_id

    @staticmethod
    def _requirements_list(requirements: Any) -> list[str]:
        if isinstance(requirements, list):
            return [str(item) for item in requirements]
        if isinstance(requirements, dict):
            return [f"{key}: {value}" for key, value in requirements.items()]
        if requirements is None:
            return []
        return [str(requirements)]

    def _build_router(self) -> UniversalTimeSeriesRouter:
        # No path: the same registry the pipeline's router uses (built-ins plus analyzers promoted
        # through the Add Analyzer wizard into config/analyzer_registry.d/), so recommendations
        # show every analyzer that can actually be routed. An explicit path skips that merge.
        registry = AnalyzerRegistry(self.registry_path)
        if self.registry_path is None:
            custom_path = Path("config/custom_analyzers.yaml")
            if custom_path.exists():
                custom_registry = AnalyzerRegistry(custom_path)
                registry._registry.update(custom_registry._registry)
                registry.registry_version = f"{registry.registry_version}+custom"
        return UniversalTimeSeriesRouter(
            registry=registry,
            config={"data_validation": {"interpolation": {"enabled": True, "maximum_gap_points": 5, "maximum_interpolated_percentage": 20}}},
        )

    @staticmethod
    def _finite_values(values: list[float]) -> list[float]:
        return [value for value in values if isfinite(value)]

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
