from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
from typing import Any

from pydantic import BaseModel, Field

from backend.app.ai.interfaces import LLMMessage, LLMRequest
from backend.app.ai.models import StructuredLLMService


class GemmaAnalyzerPick(BaseModel):
    analyzer_id: str
    recommendation: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class GemmaAnalyzerRecommendation(BaseModel):
    best_analyzer_id: str
    rationale: str
    recommended: list[GemmaAnalyzerPick] = Field(default_factory=list)
    not_recommended: list[GemmaAnalyzerPick] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class GemmaAnalyzerAdvisor:
    """Prompt builder for optional Gemma-backed analyzer recommendations."""

    def __init__(self, structured_llm: StructuredLLMService) -> None:
        self.structured_llm = structured_llm

    def recommend(
        self,
        *,
        profile: Any,
        timeseries: list[tuple[Any, float]],
        analyzer_decisions: list[Any],
        metric_context: dict[str, Any] | None = None,
        max_points: int = 80,
    ) -> GemmaAnalyzerRecommendation:
        request = LLMRequest(
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        "You are an analyzer-routing assistant. Recommend the time-series analyzers that best match "
                        "the observed metric pattern. Return only valid JSON matching the requested schema."
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=self.build_prompt(
                        profile=profile,
                        timeseries=timeseries,
                        analyzer_decisions=analyzer_decisions,
                        metric_context=metric_context,
                        max_points=max_points,
                    ),
                ),
            ],
            temperature=0.0,
            max_tokens=900,
            response_format="json",
        )
        return self.structured_llm.generate_structured(request, GemmaAnalyzerRecommendation)

    @classmethod
    def build_prompt(
        cls,
        *,
        profile: Any,
        timeseries: list[tuple[Any, float]],
        analyzer_decisions: list[Any],
        metric_context: dict[str, Any] | None = None,
        max_points: int = 80,
    ) -> str:
        payload = {
            "task": "Choose the best analyzer or analyzers for this metric sample.",
            "metric_context": metric_context or {},
            "series_profile": cls._compact_profile(profile),
            "timeseries_sample": cls._compact_timeseries(timeseries, max_points=max_points),
            "available_analyzers": [cls._compact_analyzer(decision) for decision in analyzer_decisions],
            "decision_rules": [
                "Prefer analyzers whose supported patterns match the time-series behavior.",
                "Do not recommend analyzers that are technically ineligible unless the caveat explains why.",
                "Use the existing router score as evidence, but override it when the raw series pattern clearly conflicts.",
                "Pick one best_analyzer_id even when multiple analyzers are useful.",
            ],
            "response_schema": {
                "best_analyzer_id": "string",
                "rationale": "short string",
                "recommended": [{"analyzer_id": "string", "recommendation": "recommended|optional", "confidence": "0..1", "reason": "string"}],
                "not_recommended": [{"analyzer_id": "string", "recommendation": "not_recommended|rejected", "confidence": "0..1", "reason": "string"}],
                "caveats": ["string"],
            },
        }
        return json.dumps(payload, default=str, separators=(",", ":"))

    @staticmethod
    def _compact_profile(profile: Any) -> dict[str, Any]:
        data = _object_to_dict(profile)
        keys = [
            "sample_count",
            "valid_sample_count",
            "regular_sampling",
            "missing_ratio",
            "missing_percentage",
            "irregular_sampling_percentage",
            "constant_value_ratio",
            "constant_value_percentage",
            "mean",
            "stddev",
            "minimum",
            "maximum",
            "variance",
            "trend_slope",
            "trend_strength",
            "seasonality_strength",
            "spikiness",
            "shift_index",
            "autocorrelation",
            "detected_profiles",
            "notes",
        ]
        return {key: data[key] for key in keys if key in data}

    @staticmethod
    def _compact_timeseries(timeseries: list[tuple[Any, float]], max_points: int) -> list[dict[str, Any]]:
        if max_points <= 0 or len(timeseries) <= max_points:
            selected = timeseries
        else:
            step = max(1, len(timeseries) // max_points)
            selected = timeseries[::step][:max_points]
            if timeseries[-1] not in selected:
                selected = [*selected[:-1], timeseries[-1]]
        return [{"timestamp": timestamp, "value": round(float(value), 6)} for timestamp, value in selected]

    @staticmethod
    def _compact_analyzer(decision: Any) -> dict[str, Any]:
        data = _object_to_dict(decision)
        parameters = data.get("parameters_tested") or {}
        return {
            "analyzer_id": data.get("analyzer") or data.get("analyzer_id"),
            "display_name": data.get("display_name"),
            "router_recommendation": data.get("recommendation"),
            "router_score": data.get("final_score") or data.get("fitness_score"),
            "eligible": data.get("eligible"),
            "supported_patterns": parameters.get("supported_profiles", []),
            "matched_patterns": parameters.get("matched_profiles", []),
            "reason": data.get("routing_reason") or data.get("summary") or data.get("explanation"),
            "warnings": data.get("warnings", []),
        }


def _object_to_dict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, dict):
        return dict(value)
    return {
        key: getattr(value, key)
        for key in dir(value)
        if not key.startswith("_") and not callable(getattr(value, key))
    }
