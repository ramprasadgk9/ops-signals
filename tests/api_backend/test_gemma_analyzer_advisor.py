from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
from typing import Type, TypeVar

from pydantic import BaseModel

from backend.app.ai.interfaces import LLMRequest
from backend.app.metric_analyzer_recommendations.gemma_advisor import (
    GemmaAnalyzerAdvisor,
    GemmaAnalyzerRecommendation,
)

T = TypeVar("T", bound=BaseModel)


@dataclass(slots=True)
class Profile:
    sample_count: int = 60
    regular_sampling: bool = True
    trend_strength: float = 0.25
    seasonality_strength: float = 0.05
    shift_index: float = 0.02
    detected_profiles: list[str] = field(default_factory=lambda: ["trend"])


@dataclass(slots=True)
class Decision:
    analyzer: str
    display_name: str
    recommendation: str
    final_score: float
    eligible: bool = True
    routing_reason: str = ""
    warnings: list[str] = field(default_factory=list)
    parameters_tested: dict = field(default_factory=dict)


class FakeStructuredLLM:
    def __init__(self) -> None:
        self.last_request: LLMRequest | None = None

    def generate_structured(self, request: LLMRequest, response_model: Type[T]) -> T:
        self.last_request = request
        return response_model.model_validate(
            {
                "best_analyzer_id": "trend_regression",
                "rationale": "The sample has a directional increase and no strong seasonal or regime-change signature.",
                "recommended": [
                    {
                        "analyzer_id": "trend_regression",
                        "recommendation": "recommended",
                        "confidence": 0.88,
                        "reason": "Trend profile and router score agree.",
                    }
                ],
                "not_recommended": [],
                "caveats": ["Validate against a longer window before tuning thresholds."],
            }
        )


def test_gemma_prompt_includes_timeseries_and_analyzer_patterns() -> None:
    start = datetime(2026, 1, 1)
    points = [(start + timedelta(minutes=index), 100 + index) for index in range(12)]
    decisions = [
        Decision(
            analyzer="trend_regression",
            display_name="Trend Regression",
            recommendation="RECOMMENDED",
            final_score=0.91,
            routing_reason="Matched detected profiles: trend.",
            parameters_tested={"supported_profiles": ["trend"], "matched_profiles": ["trend"]},
        )
    ]

    prompt = GemmaAnalyzerAdvisor.build_prompt(
        profile=Profile(),
        timeseries=points,
        analyzer_decisions=decisions,
        metric_context={"metric_name": "cpu_usage"},
        max_points=5,
    )
    payload = json.loads(prompt)

    assert payload["series_profile"]["detected_profiles"] == ["trend"]
    assert len(payload["timeseries_sample"]) == 5
    assert payload["available_analyzers"][0]["supported_patterns"] == ["trend"]
    assert payload["available_analyzers"][0]["matched_patterns"] == ["trend"]


def test_gemma_advisor_returns_validated_recommendation() -> None:
    fake_llm = FakeStructuredLLM()
    advisor = GemmaAnalyzerAdvisor(fake_llm)  # type: ignore[arg-type]

    result = advisor.recommend(
        profile=Profile(),
        timeseries=[(datetime(2026, 1, 1), 100.0), (datetime(2026, 1, 1, 0, 5), 110.0)],
        analyzer_decisions=[
            Decision(
                analyzer="trend_regression",
                display_name="Trend Regression",
                recommendation="RECOMMENDED",
                final_score=0.91,
            )
        ],
    )

    assert isinstance(result, GemmaAnalyzerRecommendation)
    assert result.best_analyzer_id == "trend_regression"
    assert fake_llm.last_request is not None
    assert fake_llm.last_request.response_format == "json"
