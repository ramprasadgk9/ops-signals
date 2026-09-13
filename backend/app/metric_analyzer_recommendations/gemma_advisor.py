from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.ai.exceptions import AIResponseFormatError
from backend.app.ai.interfaces import LLMMessage, LLMRequest
from backend.app.ai.models import StructuredLLMService


# The registry (experiments/analyzer_router/analyzer_registry.yaml, config/custom_analyzers.yaml)
# only carries category tags (supported_profiles) and canned template sentences for each analyzer -
# nothing that tells the model what the underlying algorithm actually does. Without this, the LLM
# is reasoning from the analyzer's name plus whatever it recalls from training, not from anything
# this codebase actually tells it. Unknown ids simply get no description (see _compact_analyzer).
_ANALYZER_DESCRIPTIONS: dict[str, str] = {
    "ruptures": "Change-point detection: compares segments of the series to find a discrete, persistent shift in the mean or variance (e.g. a step change after a deploy).",
    "stumpy": "Matrix-profile analysis: finds recurring motifs or repeated/anomalous subsequences. Needs dense, regularly sampled data to work well.",
    "prophet": "Additive trend + seasonality forecasting model. Projects future values; needs enough history and a reasonably stable seasonal signal.",
    "river": "Online/streaming anomaly and concept-drift detection, updated incrementally point-by-point rather than analyzing a fixed historical window.",
    "kats": "General time-series toolkit bundling baseline-shift, forecast, anomaly, and seasonality detectors - useful when more than one pattern type may be present.",
    "darts": "Multi-backend forecasting library covering trend, seasonality, and more complex non-linear patterns; needs enough history to fit a model.",
    "alibi_detect": "Statistical drift detection: flags when the series' underlying distribution or concept has shifted over time, distinct from a single spike or trend.",
    "trend_regression": "Fits a linear/robust regression line to detect a sustained directional drift (steady increase or decrease), not one-off jumps.",
    "adtk": "Rule-based anomaly detection: flags spikes and seasonal anomalies using configurable threshold rules rather than a single statistical model.",
    "pyod": "General outlier-detection toolkit (e.g. isolation-forest style models) that flags points which don't fit the overall data distribution.",
    "pyod_outlier": "PyOD-based detector tuned specifically for spikes and short anomalous windows rather than broad distributional outliers.",
    "statsforecast_forecast": "Lightweight statistical forecasting (statsforecast library) for series with regular sampling and a seasonal signal.",
}


class GemmaAnalyzerPick(BaseModel):
    analyzer_id: str
    # Constrained to the router's own vocabulary (rather than free text like "Rank 1") so this
    # field is directly comparable to the deterministic router's recommendation, and a smaller
    # local model can't drift into inconsistent labels - see _normalize_top_recommendations.
    recommendation: Literal["recommended", "optional", "not_recommended"]
    rank: int | None = Field(default=None, ge=1, le=3)
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
        max_points: int = 40,
    ) -> GemmaAnalyzerRecommendation:
        request = LLMRequest(
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        "You are an analyzer-routing assistant. Rank the time-series analyzers that best match "
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
            max_tokens=1800,
            response_format="json",
        )
        result = self.structured_llm.generate_structured(request, GemmaAnalyzerRecommendation)
        result = self._normalize_top_recommendations(result)
        known_analyzer_ids = {self._compact_analyzer(decision)["analyzer_id"] for decision in analyzer_decisions}
        return self._drop_unrecognized_analyzers(result, known_analyzer_ids)

    @classmethod
    def build_prompt(
        cls,
        *,
        profile: Any,
        timeseries: list[tuple[Any, float]],
        analyzer_decisions: list[Any],
        metric_context: dict[str, Any] | None = None,
        max_points: int = 40,
    ) -> str:
        compact_analyzers = [cls._compact_analyzer(decision) for decision in analyzer_decisions]
        router_top_pick = cls._router_top_pick(compact_analyzers)
        payload = {
            "metric_context": metric_context or {},
            "series_profile": cls._compact_profile(profile),
            "timeseries_sample": cls._compact_timeseries(timeseries, max_points=max_points),
            "available_analyzers": compact_analyzers,
            "router_top_pick": router_top_pick,
        }
        return (
            "Choose exactly 3 analyzers for this metric sample, ranked from best primary choice to supporting choices.\n"
            "Return only one JSON object. Do not echo the input. Do not use markdown.\n\n"
            "Rules:\n"
            "- Set best_analyzer_id to the strongest primary analyzer.\n"
            "- Return exactly 3 items in recommended when at least 3 eligible analyzers are available.\n"
            "- Break router score ties using the dominant raw-series behavior.\n"
            "- Assign rank 1, 2, or 3 to each of your top 3 picks (in the recommended list); leave rank unset "
            "for every other pick. Mention the analyzer's role (primary vs supporting) in its reason.\n"
            "- Put eligible analyzers outside the top 3 into not_recommended when redundant, too broad, or less aligned.\n"
            "- If best_analyzer_id differs from router_top_pick.analyzer_id, you must explain in rationale exactly "
            "what evidence in series_profile or timeseries_sample justifies overriding the router's top-scored "
            "analyzer. Do not diverge from router_top_pick without a specific, evidenced reason.\n"
            "- Base every reason, rationale, and caveat strictly on the series_profile, timeseries_sample, and "
            "available_analyzers data given below. Do not invent statistics, patterns, or analyzer capabilities "
            "that are not evidenced in the input.\n"
            "- Calibrate confidence to the evidence, not a gut feeling: use 0.8-1.0 only when matched_patterns "
            "clearly overlaps supported_patterns and router_score is above 0.7; use 0.5-0.79 for a plausible but "
            "not strongly confirmed fit; use below 0.5 for a speculative or weakly supported pick.\n\n"
            "Required JSON keys: best_analyzer_id, rationale, recommended, not_recommended, caveats.\n"
            "Each recommended/not_recommended item must include analyzer_id, recommendation, confidence, reason, "
            "and optionally rank. recommendation must be exactly one of: recommended, optional, not_recommended.\n\n"
            "Example below illustrates JSON SHAPE ONLY. ANALYZER_X/ANALYZER_Y/ANALYZER_Z are placeholders that do "
            "not exist in this system and must never appear in your answer, and the reason/rationale/caveat text is "
            "deliberately generic filler, not real analysis. Copying any of this wording, or these ids, into your "
            "answer is wrong - every reason, rationale, and caveat you write must instead reference specific values "
            "actually present in the real input data below (e.g. actual numbers from series_profile, actual ids "
            "from available_analyzers).\n"
            '{"best_analyzer_id":"ANALYZER_X","rationale":"<state the specific series_profile/timeseries_sample '
            'evidence that makes ANALYZER_X the strongest match>","recommended":[{"analyzer_id":"ANALYZER_X",'
            '"recommendation":"recommended","rank":1,"confidence":0.85,"reason":"<why this is the primary pick, '
            'citing real evidence>"},{"analyzer_id":"ANALYZER_Y","recommendation":"optional","rank":2,'
            '"confidence":0.55,"reason":"<why this is a useful supporting pick, citing real evidence>"}],'
            '"not_recommended":[{"analyzer_id":"ANALYZER_Z","recommendation":"not_recommended","confidence":0.2,'
            '"reason":"<why this does not fit, citing real evidence>"}],"caveats":["<any real caveat about this '
            'specific sample, if any>"]}\n\n'
            f"Input data:\n{json.dumps(payload, default=str, separators=(',', ':'))}"
        )

    @staticmethod
    def _router_top_pick(compact_analyzers: list[dict[str, Any]]) -> dict[str, Any] | None:
        scoring_pool = [item for item in compact_analyzers if item.get("eligible")] or compact_analyzers
        scored = [item for item in scoring_pool if isinstance(item.get("router_score"), (int, float))]
        if not scored:
            return None
        top = max(scored, key=lambda item: item["router_score"])
        return {"analyzer_id": top["analyzer_id"], "router_score": top["router_score"]}

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
        """Shape-preserving downsample. Plain uniform-stride sampling (every Nth point) can step
        right over a short spike or the exact point of a regime change - exactly the detail the
        whole point of showing raw data to the LLM depends on it noticing. Instead, bucket the
        series and keep each bucket's min and max point, so extrema always survive compression;
        only smooth, uneventful stretches actually get thinned out."""
        if max_points <= 0 or len(timeseries) <= max_points:
            selected_indices = list(range(len(timeseries)))
        else:
            bucket_count = max(1, max_points // 2)
            bucket_size = max(1, len(timeseries) // bucket_count)
            keep: set[int] = {0, len(timeseries) - 1}
            for bucket_start in range(0, len(timeseries), bucket_size):
                bucket = timeseries[bucket_start : bucket_start + bucket_size]
                if not bucket:
                    continue
                local_min = min(range(len(bucket)), key=lambda i: bucket[i][1])
                local_max = max(range(len(bucket)), key=lambda i: bucket[i][1])
                keep.add(bucket_start + local_min)
                keep.add(bucket_start + local_max)
            selected_indices = sorted(keep)
        return [{"index": index, "value": round(float(timeseries[index][1]), 6)} for index in selected_indices]

    @staticmethod
    def _compact_analyzer(decision: Any) -> dict[str, Any]:
        data = _object_to_dict(decision)
        parameters = data.get("parameters_tested") or {}
        analyzer_id = data.get("analyzer") or data.get("analyzer_id")
        return {
            "analyzer_id": analyzer_id,
            "display_name": data.get("display_name"),
            "description": _ANALYZER_DESCRIPTIONS.get(analyzer_id),
            "router_recommendation": data.get("recommendation"),
            "router_score": data.get("final_score") or data.get("fitness_score"),
            "eligible": data.get("eligible"),
            "supported_patterns": parameters.get("supported_profiles", []),
            "matched_patterns": parameters.get("matched_profiles", []),
            "reason": data.get("routing_reason") or data.get("summary") or data.get("explanation"),
            "warnings": data.get("warnings", []),
        }

    @staticmethod
    def _normalize_top_recommendations(result: GemmaAnalyzerRecommendation) -> GemmaAnalyzerRecommendation:
        """A smaller local model can get the recommended/not_recommended bucket wrong while still
        getting the rank right (e.g. filing a rank-2 pick under not_recommended). Trust an
        explicit rank as the stronger signal - anything ranked 1-3 belongs in recommended even if
        the model bucketed it elsewhere."""
        recommended = list(result.recommended)
        recommended_ids = {pick.analyzer_id for pick in recommended}
        remaining_not_recommended: list[GemmaAnalyzerPick] = []
        for pick in result.not_recommended:
            if pick.rank is not None and len(recommended) < 3 and pick.analyzer_id not in recommended_ids:
                promoted = pick.model_copy(update={"recommendation": "recommended" if pick.rank == 1 else "optional"})
                recommended.append(promoted)
                recommended_ids.add(pick.analyzer_id)
            else:
                remaining_not_recommended.append(pick)
        return result.model_copy(update={"recommended": recommended[:3], "not_recommended": remaining_not_recommended})

    @staticmethod
    def _drop_unrecognized_analyzers(
        result: GemmaAnalyzerRecommendation, known_analyzer_ids: set[str]
    ) -> GemmaAnalyzerRecommendation:
        """StructuredLLMService only validates JSON shape against the schema, not that returned
        analyzer_id values are among the analyzers actually offered to the model - a hallucinated
        or misspelled id would otherwise pass through silently and be displayed as a real pick.
        Drop anything unrecognized, and never fabricate a winner: if nothing valid survives, raise
        so the caller falls back to the deterministic router recommendation instead."""
        recommended = [pick for pick in result.recommended if pick.analyzer_id in known_analyzer_ids]
        not_recommended = [pick for pick in result.not_recommended if pick.analyzer_id in known_analyzer_ids]
        best_analyzer_id = result.best_analyzer_id
        if best_analyzer_id not in known_analyzer_ids:
            if recommended:
                best_analyzer_id = recommended[0].analyzer_id
            else:
                raise AIResponseFormatError(
                    f"Gemma advisor returned no analyzer ids that match the analyzers actually offered to it "
                    f"(best_analyzer_id={result.best_analyzer_id!r}, known_analyzer_ids={sorted(known_analyzer_ids)!r})"
                )
        return result.model_copy(update={"best_analyzer_id": best_analyzer_id, "recommended": recommended, "not_recommended": not_recommended})


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
