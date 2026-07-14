from __future__ import annotations

from dataclasses import dataclass

from .confidence import calculate_confidence
from .condition_evaluator import evaluate_conditions
from .correlation import evaluate_correlation
from .models import BehaviorDefinition, BehaviorEvaluation


@dataclass(slots=True)
class BehaviorFindingDraft:
    evaluation: BehaviorEvaluation
    should_create: bool


def build_evaluation(definition: BehaviorDefinition, facts: dict, matched_inputs: dict, service: str | None, analysis_run_id: str | None) -> BehaviorEvaluation:
    condition_matches = evaluate_conditions(facts, definition.conditions)
    all_results = [item["passed"] for item in condition_matches if item["group"] == "all"]
    any_results = [item["passed"] for item in condition_matches if item["group"] == "any"]
    correlation = evaluate_correlation(
        {
            "correlation": definition.correlation,
        },
        matched_inputs,
    )
    matched = all(all_results or [True]) and (not any_results or any(any_results)) and correlation["matched"]
    confidence = calculate_confidence(condition_matches, correlation["matched"])
    return BehaviorEvaluation(
        definition_id=definition.id,
        definition_version=definition.version,
        title=definition.title,
        description=definition.description,
        matched=matched,
        confidence=confidence,
        service=service,
        analysis_run_id=analysis_run_id,
        facts=facts,
        matched_conditions=condition_matches,
        evidence=definition.output.evidence,
        correlation=correlation,
    )
