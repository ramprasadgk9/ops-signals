from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
from typing import Type, TypeVar

import pytest
from pydantic import BaseModel

from backend.app.ai.exceptions import AIResponseFormatError
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
                        "rank": 1,
                        "confidence": 0.88,
                        "reason": "Rank 1 primary trend summarizer. Trend profile and router score agree.",
                    },
                    {
                        "analyzer_id": "prophet",
                        "recommendation": "optional",
                        "rank": 2,
                        "confidence": 0.62,
                        "reason": "Rank 2 supporting forecaster when trend needs projection.",
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
    payload = json.loads(prompt.split("Input data:\n", 1)[1])

    assert payload["series_profile"]["detected_profiles"] == ["trend"]
    # Bucketed min/max downsampling of 12 points into ~5: two buckets of 6, each contributing its
    # min and max index (0, 5) and (6, 11) - see test_compact_timeseries_* below for the dedicated
    # coverage of why this replaced plain stride sampling.
    assert [item["index"] for item in payload["timeseries_sample"]] == [0, 5, 6, 11]
    assert [item["value"] for item in payload["timeseries_sample"]] == [100.0, 105.0, 106.0, 111.0]
    assert payload["available_analyzers"][0]["supported_patterns"] == ["trend"]
    assert payload["available_analyzers"][0]["matched_patterns"] == ["trend"]
    assert payload["available_analyzers"][0]["description"] == (
        "Fits a linear/robust regression line to detect a sustained directional drift "
        "(steady increase or decrease), not one-off jumps."
    )
    assert "exactly 3 analyzers" in prompt
    assert "Return exactly 3 items" in prompt
    assert payload["router_top_pick"] == {"analyzer_id": "trend_regression", "router_score": 0.91}
    assert "justifies overriding the router's top-scored" in prompt


def test_compact_analyzer_omits_description_for_an_unrecognized_analyzer_id() -> None:
    decisions = [
        Decision(analyzer="some_future_analyzer", display_name="Future Analyzer", recommendation="OPTIONAL", final_score=0.5)
    ]

    prompt = GemmaAnalyzerAdvisor.build_prompt(
        profile=Profile(),
        timeseries=[(datetime(2026, 1, 1), 1.0), (datetime(2026, 1, 1, 0, 5), 2.0)],
        analyzer_decisions=decisions,
    )
    payload = json.loads(prompt.split("Input data:\n", 1)[1])

    assert payload["available_analyzers"][0]["description"] is None


def test_compact_timeseries_preserves_a_spike_that_uniform_stride_sampling_would_skip() -> None:
    start = datetime(2026, 1, 1)
    baseline = 10.0
    spike_index = 16
    points = [(start + timedelta(minutes=index), baseline) for index in range(30)]
    points[spike_index] = (points[spike_index][0], 500.0)

    sample = GemmaAnalyzerAdvisor._compact_timeseries(points, max_points=10)
    sampled_indices = {item["index"] for item in sample}

    # A naive `every Nth point` stride of 3 over 30 points lands on 0,3,6,...,27 - it would never
    # land on index 16, silently dropping the one point that actually matters.
    naive_stride_indices = set(range(0, 30, max(1, 30 // 10)))
    assert spike_index not in naive_stride_indices  # confirms this scenario would defeat the old approach
    assert spike_index in sampled_indices
    assert sample[[item["index"] for item in sample].index(spike_index)]["value"] == 500.0


def test_compact_timeseries_always_keeps_series_endpoints() -> None:
    points = [(datetime(2026, 1, 1) + timedelta(minutes=index), float(index)) for index in range(50)]

    sample = GemmaAnalyzerAdvisor._compact_timeseries(points, max_points=10)
    sampled_indices = [item["index"] for item in sample]

    assert sampled_indices[0] == 0
    assert sampled_indices[-1] == 49


def test_compact_timeseries_returns_all_points_when_series_is_shorter_than_max_points() -> None:
    points = [(datetime(2026, 1, 1) + timedelta(minutes=index), float(index)) for index in range(3)]

    sample = GemmaAnalyzerAdvisor._compact_timeseries(points, max_points=40)

    assert [item["index"] for item in sample] == [0, 1, 2]
    assert [item["value"] for item in sample] == [0.0, 1.0, 2.0]


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
            ),
            Decision(
                analyzer="prophet",
                display_name="Prophet",
                recommendation="OPTIONAL",
                final_score=0.6,
            ),
        ],
    )

    assert isinstance(result, GemmaAnalyzerRecommendation)
    assert result.best_analyzer_id == "trend_regression"
    assert len(result.recommended) == 2
    assert fake_llm.last_request is not None
    assert fake_llm.last_request.response_format == "json"


def test_gemma_advisor_normalizes_ranked_picks_from_wrong_bucket() -> None:
    # ruptures/stumpy carry a real rank (2/3) but were mis-bucketed under not_recommended - the
    # recommendation Literal enum no longer lets a model smuggle "Rank 2" into that field itself,
    # so this exercises the dedicated `rank` field as the (now sole, reliable) promotion signal.
    result = GemmaAnalyzerRecommendation.model_validate(
        {
            "best_analyzer_id": "prophet",
            "rationale": "Ranked result.",
            "recommended": [
                {"analyzer_id": "prophet", "recommendation": "recommended", "rank": 1, "confidence": 1.0, "reason": "Rank 1 forecaster."}
            ],
            "not_recommended": [
                {"analyzer_id": "ruptures", "recommendation": "not_recommended", "rank": 2, "confidence": 1.0, "reason": "Rank 2 change detector."},
                {"analyzer_id": "stumpy", "recommendation": "not_recommended", "rank": 3, "confidence": 1.0, "reason": "Rank 3 motif detector."},
                {"analyzer_id": "pyod", "recommendation": "not_recommended", "confidence": 0.4, "reason": "Outlier view is less aligned."},
            ],
            "caveats": [],
        }
    )

    normalized = GemmaAnalyzerAdvisor._normalize_top_recommendations(result)

    assert [item.analyzer_id for item in normalized.recommended] == ["prophet", "ruptures", "stumpy"]
    assert [item.analyzer_id for item in normalized.not_recommended] == ["pyod"]
    assert [item.recommendation for item in normalized.recommended] == ["recommended", "optional", "optional"]


def test_gemma_pick_rejects_a_recommendation_value_outside_the_fixed_vocabulary() -> None:
    with pytest.raises(Exception):
        GemmaAnalyzerRecommendation.model_validate(
            {
                "best_analyzer_id": "prophet",
                "rationale": "Invalid label test.",
                "recommended": [
                    {"analyzer_id": "prophet", "recommendation": "Rank 1", "confidence": 1.0, "reason": "Should fail validation."}
                ],
                "not_recommended": [],
                "caveats": [],
            }
        )


def test_prompt_states_the_fixed_recommendation_vocabulary_and_confidence_rubric() -> None:
    prompt = GemmaAnalyzerAdvisor.build_prompt(
        profile=Profile(),
        timeseries=[(datetime(2026, 1, 1), 1.0), (datetime(2026, 1, 1, 0, 5), 2.0)],
        analyzer_decisions=[
            Decision(analyzer="trend_regression", display_name="Trend Regression", recommendation="RECOMMENDED", final_score=0.91)
        ],
    )

    assert "recommendation must be exactly one of: recommended, optional, not_recommended" in prompt
    assert "Do not invent statistics, patterns, or analyzer capabilities" in prompt
    assert "Calibrate confidence to the evidence" in prompt
    assert "JSON SHAPE ONLY" in prompt


def test_prompt_example_uses_placeholder_ids_that_would_fail_the_real_analyzer_check() -> None:
    # A local model running at temperature=0.0 can latch onto a realistic-looking worked example
    # and echo its wording almost verbatim instead of reasoning about the real input - confirmed
    # live against two genuinely different samples returning byte-identical rationale text. Using
    # placeholder ids that don't exist in this system means even a copied example would get
    # dropped by _drop_unrecognized_analyzers rather than silently displayed as real analysis.
    prompt = GemmaAnalyzerAdvisor.build_prompt(
        profile=Profile(),
        timeseries=[(datetime(2026, 1, 1), 1.0), (datetime(2026, 1, 1, 0, 5), 2.0)],
        analyzer_decisions=[
            Decision(analyzer="trend_regression", display_name="Trend Regression", recommendation="RECOMMENDED", final_score=0.91)
        ],
    )

    assert "ANALYZER_X" in prompt
    assert "must never appear in your answer" in prompt
    assert "deliberately generic filler, not real analysis" in prompt


class _HallucinatingLLM:
    """Returns a best_analyzer_id and a pick that were never offered as available analyzers -
    simulates the LLM inventing or misspelling an analyzer id."""

    def __init__(self, best_analyzer_id: str = "stumpy_v2") -> None:
        self.best_analyzer_id = best_analyzer_id

    def generate_structured(self, request: LLMRequest, response_model: Type[T]) -> T:
        return response_model.model_validate(
            {
                "best_analyzer_id": self.best_analyzer_id,
                "rationale": "Fabricated rationale referencing an analyzer that was never offered.",
                "recommended": [
                    {
                        "analyzer_id": "trend_regression",
                        "recommendation": "recommended",
                        "confidence": 0.7,
                        "reason": "Rank 1 real analyzer that was actually offered.",
                    },
                    {
                        "analyzer_id": self.best_analyzer_id,
                        "recommendation": "recommended",
                        "confidence": 0.95,
                        "reason": "Rank 2 hallucinated analyzer id.",
                    },
                ],
                "not_recommended": [],
                "caveats": [],
            }
        )


def test_recommend_drops_a_hallucinated_analyzer_id_and_falls_back_to_a_real_pick() -> None:
    advisor = GemmaAnalyzerAdvisor(_HallucinatingLLM())  # type: ignore[arg-type]

    result = advisor.recommend(
        profile=Profile(),
        timeseries=[(datetime(2026, 1, 1), 100.0), (datetime(2026, 1, 1, 0, 5), 110.0)],
        analyzer_decisions=[
            Decision(analyzer="trend_regression", display_name="Trend Regression", recommendation="RECOMMENDED", final_score=0.91)
        ],
    )

    assert result.best_analyzer_id == "trend_regression"
    assert [item.analyzer_id for item in result.recommended] == ["trend_regression"]


def test_recommend_raises_when_no_returned_analyzer_id_matches_a_real_analyzer() -> None:
    class _OnlyHallucinatedLLM:
        def generate_structured(self, request: LLMRequest, response_model: Type[T]) -> T:
            return response_model.model_validate(
                {
                    "best_analyzer_id": "totally_made_up",
                    "rationale": "Everything here is invented.",
                    "recommended": [
                        {"analyzer_id": "totally_made_up", "recommendation": "recommended", "confidence": 0.9, "reason": "Not real."}
                    ],
                    "not_recommended": [],
                    "caveats": [],
                }
            )

    advisor = GemmaAnalyzerAdvisor(_OnlyHallucinatedLLM())  # type: ignore[arg-type]

    with pytest.raises(AIResponseFormatError):
        advisor.recommend(
            profile=Profile(),
            timeseries=[(datetime(2026, 1, 1), 100.0), (datetime(2026, 1, 1, 0, 5), 110.0)],
            analyzer_decisions=[
                Decision(analyzer="trend_regression", display_name="Trend Regression", recommendation="RECOMMENDED", final_score=0.91)
            ],
        )


def test_router_top_pick_prefers_eligible_analyzers_and_highest_score() -> None:
    decisions = [
        Decision(analyzer="stumpy", display_name="STUMPY", recommendation="NOT_RECOMMENDED", final_score=0.0, eligible=False),
        Decision(analyzer="trend_regression", display_name="Trend Regression", recommendation="RECOMMENDED", final_score=0.91, eligible=True),
        Decision(analyzer="ruptures", display_name="Ruptures", recommendation="OPTIONAL", final_score=0.6, eligible=True),
    ]

    prompt = GemmaAnalyzerAdvisor.build_prompt(
        profile=Profile(),
        timeseries=[(datetime(2026, 1, 1), 100.0), (datetime(2026, 1, 1, 0, 5), 110.0)],
        analyzer_decisions=decisions,
    )
    payload = json.loads(prompt.split("Input data:\n", 1)[1])

    assert payload["router_top_pick"] == {"analyzer_id": "trend_regression", "router_score": 0.91}
