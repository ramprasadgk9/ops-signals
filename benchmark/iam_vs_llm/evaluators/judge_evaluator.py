from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from benchmark.iam_vs_llm.configs.manifest_loader import BenchmarkManifest, ModelRunConfig, load_manifest
from benchmark.iam_vs_llm.evaluators.judge_agreement import calculate_fleiss_kappa, calculate_krippendorff_alpha
from benchmark.iam_vs_llm.evaluators.taxonomy import RootCauseClass
from benchmark.iam_vs_llm.runners.base_runner import BenchmarkRunResult
from benchmark.iam_vs_llm.runners.react_base import resolve_llm_client


JUDGE_RUBRIC_PROMPT = """You are an expert Principal Site Reliability Engineer serving as an impartial benchmark judge.
Your goal is to evaluate a system's incident diagnosis against curated ground truth telemetry and causal invariants.

Evaluate the diagnosis along three strictly unbundled 5-point Likert axes:

1. ATTRIBUTION (1 to 5):
- 5: Exactly identifies the root cause mechanism and culprit entity, clearly isolating cause from downstream symptoms.
- 4: Identifies the root cause class correctly, but has slight ambiguity in entity or mechanism.
- 3: Identifies a major contributing factor or symptom, but misses the true root cause mechanism.
- 2: Confuses downstream symptoms with the root cause (e.g. blaming API gateway for DB connection exhaustion).
- 1: Entirely incorrect or hallucinated attribution.

2. GROUNDING (1 to 5):
- 5: Thoroughly grounded in verified metrics, K8s events, or signals; cited window matches incident timeline; zero hallucinations.
- 4: Grounded in genuine telemetry, but minor inaccuracies in timestamps or missing secondary evidence.
- 3: Telemetry citations are sparse, vague, or partially unverified.
- 2: Significant unsupported claims or false telemetry citations.
- 1: Purely speculative or completely un-grounded in scenario telemetry.

3. ACTIONABILITY (1 to 5):
- 5: Provides specific, safe, non-destructive remediation advice directly addressing the culprit entity.
- 4: Provides reasonable remediation advice, but lacks precise configuration or command specifics.
- 3: High-level or generic advice (e.g. "investigate logs and monitor metrics").
- 2: Inappropriate or misleading remediation steps that would prolong the outage.
- 1: Destructive, dangerous, or completely irrelevant remediation advice.

GROUND TRUTH:
- Expected Root Cause: {expected_root_cause}
- Culprit Entity: {expected_entity}
- Expected Evidence: {expected_evidence}

SYSTEM DIAGNOSIS UNDER REVIEW:
- Normalized Root Cause: {diagnosed_root_cause}
- Diagnosed Entity: {diagnosed_entity}
- Cited Evidence: {diagnosed_evidence}
- Raw Diagnosis Output:
{raw_diagnosis}

Respond STRICTLY with a valid JSON object matching this schema:
{{
  "attribution": <integer 1-5>,
  "grounding": <integer 1-5>,
  "actionability": <integer 1-5>,
  "justification": "<concise explanation citing rubric criteria>"
}}
"""


@dataclass(slots=True)
class JudgeScore:
    """Individual rating from a single judge rater across the three benchmark axes."""
    attribution: int
    grounding: int
    actionability: int
    justification: str = ""
    judge_id: str = "judge-0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "judge_id": self.judge_id,
            "attribution": self.attribution,
            "grounding": self.grounding,
            "actionability": self.actionability,
            "justification": self.justification,
        }


@dataclass(slots=True)
class JudgeEvaluationResult:
    """Consensus evaluation result and statistical inter-rater agreement."""
    scores: list[JudgeScore]
    consensus: JudgeScore
    fleiss_kappa: float
    krippendorff_alpha: float
    calibrated: bool = True
    token_usage: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "consensus": self.consensus.to_dict(),
            "scores": [s.to_dict() for s in self.scores],
            "fleiss_kappa": self.fleiss_kappa,
            "krippendorff_alpha": self.krippendorff_alpha,
            "calibrated": self.calibrated,
            "token_usage": self.token_usage,
            "cost_usd": self.cost_usd,
        }


def _extract_ground_truth(gt: dict[str, Any]) -> tuple[str, str, list[str]]:
    """Robustly extracts root_cause, entity, and evidence from ground truth dictionary."""
    rc = gt.get("root_cause")
    if isinstance(rc, dict):
        rc_str = str(rc.get("primary_class") or rc.get("class") or "UNKNOWN")
    else:
        rc_str = str(rc or "UNKNOWN")

    entity = gt.get("entity") or gt.get("culprit")
    if isinstance(entity, dict):
        entity_str = str(entity.get("service") or entity.get("name") or "")
    else:
        entity_str = str(entity or "")

    key_ev = gt.get("key_evidence") or gt.get("evidence") or {}
    if isinstance(key_ev, dict):
        metrics = key_ev.get("metrics") or key_ev.get("primary_metrics") or []
        signals = key_ev.get("signals") or []
        evidence_list = [str(m) for m in metrics] + [str(s) for s in signals]
    elif isinstance(key_ev, list):
        evidence_list = [str(e) for e in key_ev]
    else:
        evidence_list = []

    return rc_str.upper(), entity_str.strip().lower(), evidence_list


class JudgeEvaluator:
    """Calibrated LLM-as-a-judge evaluation harness with inter-rater agreement statistics."""

    def __init__(
        self,
        manifest: BenchmarkManifest | None = None,
        num_raters: int = 3,
    ) -> None:
        self.manifest = manifest or load_manifest()
        self.config = self.manifest.judge
        self.num_raters = max(2, num_raters)

    def evaluate(
        self,
        run_result: BenchmarkRunResult,
        ground_truth: dict[str, Any],
    ) -> JudgeEvaluationResult:
        """Evaluates a benchmark run result against scenario ground truth."""
        provider = (self.config.provider or "mock").lower().strip()
        if provider == "mock":
            return self._evaluate_mock(run_result, ground_truth)
        elif provider in ("openai", "openrouter"):
            return self._evaluate_live(run_result, ground_truth)
        else:
            raise ValueError(
                f"Unsupported judge provider '{self.config.provider}'. "
                "Supported providers: 'mock', 'openai', 'openrouter'."
            )

    def _evaluate_mock(
        self,
        run_result: BenchmarkRunResult,
        ground_truth: dict[str, Any],
    ) -> JudgeEvaluationResult:
        """Deterministic, calibrated mock judge evaluation for offline CI test execution."""
        rca = run_result.normalized_rca
        expected_rc_str, expected_entity, expected_evidence = _extract_ground_truth(ground_truth)

        try:
            expected_rc = RootCauseClass(expected_rc_str)
        except ValueError:
            expected_rc = RootCauseClass.UNKNOWN

        # 1. Base Attribution Calculation
        rc_matches = rca.root_cause == expected_rc and expected_rc != RootCauseClass.UNKNOWN
        entity_matches = (rca.entity or "").strip().lower() == expected_entity

        if rc_matches and entity_matches:
            base_attribution = 5
        elif rc_matches and not entity_matches:
            base_attribution = 4
        elif entity_matches and not rc_matches:
            base_attribution = 3
        elif rca.root_cause == RootCauseClass.UNKNOWN:
            base_attribution = 2
        else:
            base_attribution = 1

        # 2. Base Grounding Calculation
        cited_keys = set(rca.evidence_keys)
        exp_keys = set(expected_evidence)
        overlap = len(cited_keys.intersection(exp_keys))
        if exp_keys:
            recall = overlap / len(exp_keys)
        else:
            recall = 1.0

        if recall >= 0.8:
            base_grounding = 5
        elif recall >= 0.4:
            base_grounding = 4
        elif recall > 0.0 or rca.fault_window is not None:
            base_grounding = 3
        elif len(rca.raw_summary) > 20:
            base_grounding = 2
        else:
            base_grounding = 1

        # 3. Base Actionability Calculation
        if base_attribution >= 4 and base_grounding >= 4:
            base_actionability = 5
        elif base_attribution >= 3:
            base_actionability = 4
        elif base_attribution >= 2:
            base_actionability = 2
        else:
            base_actionability = 1

        # Generate num_raters consistent ratings for deterministic CI evaluation
        scores: list[JudgeScore] = []
        for i in range(self.num_raters):
            justification = (
                f"Rater {i+1}: Attribution {base_attribution}/5 (rc_match={rc_matches}, entity_match={entity_matches}). "
                f"Grounding {base_grounding}/5 (evidence overlap={overlap}/{len(exp_keys)}). "
                f"Actionability {base_actionability}/5."
            )
            scores.append(JudgeScore(
                attribution=base_attribution,
                grounding=base_grounding,
                actionability=base_actionability,
                justification=justification,
                judge_id=f"judge-rater-{i+1}",
            ))

        consensus = JudgeScore(
            attribution=base_attribution,
            grounding=base_grounding,
            actionability=base_actionability,
            justification=f"Consensus across {self.num_raters} raters.",
            judge_id="consensus",
        )

        # Build rating matrices for Fleiss' kappa and Krippendorff's alpha
        # Shape: subjects (3 axes) x raters
        ratings_matrix: list[list[int]] = [
            [s.attribution for s in scores],
            [s.grounding for s in scores],
            [s.actionability for s in scores],
        ]

        fleiss_k = calculate_fleiss_kappa(ratings_matrix, num_categories=5)
        kripp_a = calculate_krippendorff_alpha(ratings_matrix, level_of_measurement="ordinal")

        return JudgeEvaluationResult(
            scores=scores,
            consensus=consensus,
            fleiss_kappa=fleiss_k,
            krippendorff_alpha=kripp_a,
            calibrated=True,
            token_usage=0,
            cost_usd=0.0,
        )

    def _evaluate_live(
        self,
        run_result: BenchmarkRunResult,
        ground_truth: dict[str, Any],
    ) -> JudgeEvaluationResult:
        """Live evaluation using frontier LLM judges."""
        client, _ = resolve_llm_client(self.config)

        rca = run_result.normalized_rca
        expected_rc, expected_entity, expected_evidence_list = _extract_ground_truth(ground_truth)
        expected_evidence = ", ".join(expected_evidence_list)

        prompt = JUDGE_RUBRIC_PROMPT.format(
            expected_root_cause=expected_rc,
            expected_entity=expected_entity,
            expected_evidence=expected_evidence,
            diagnosed_root_cause=rca.root_cause.value,
            diagnosed_entity=rca.entity or "unknown",
            diagnosed_evidence=", ".join(rca.evidence_keys) or "None",
            raw_diagnosis=rca.raw_summary or "No summary",
        )

        scores: list[JudgeScore] = []
        total_in_tokens = 0
        total_out_tokens = 0

        for rater_idx in range(self.num_raters):
            resp = client.chat.completions.create(
                model=self.config.model_id,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.config.temperature if self.num_raters > 1 else 0.0,
                response_format={"type": "json_object"},
            )

            if resp.usage:
                total_in_tokens += resp.usage.prompt_tokens
                total_out_tokens += resp.usage.completion_tokens

            content = resp.choices[0].message.content or "{}"
            try:
                data = json.loads(content)
                attr = int(data.get("attribution", 3))
                grd = int(data.get("grounding", 3))
                act = int(data.get("actionability", 3))
                justification = str(data.get("justification", ""))
            except Exception:
                attr, grd, act, justification = 3, 3, 3, "Failed to parse judge JSON."

            scores.append(JudgeScore(
                attribution=max(1, min(5, attr)),
                grounding=max(1, min(5, grd)),
                actionability=max(1, min(5, act)),
                justification=justification,
                judge_id=f"judge-rater-{rater_idx+1}",
            ))

        # Calculate consensus as rounded average
        avg_attr = round(sum(s.attribution for s in scores) / len(scores))
        avg_grd = round(sum(s.grounding for s in scores) / len(scores))
        avg_act = round(sum(s.actionability for s in scores) / len(scores))

        consensus = JudgeScore(
            attribution=avg_attr,
            grounding=avg_grd,
            actionability=avg_act,
            justification=f"Consensus average across {len(scores)} raters.",
            judge_id="consensus",
        )

        ratings_matrix = [
            [s.attribution for s in scores],
            [s.grounding for s in scores],
            [s.actionability for s in scores],
        ]
        fleiss_k = calculate_fleiss_kappa(ratings_matrix, num_categories=5)
        kripp_a = calculate_krippendorff_alpha(ratings_matrix, level_of_measurement="ordinal")
        cost_usd = self.config.pricing.calculate_cost(total_in_tokens, total_out_tokens)

        return JudgeEvaluationResult(
            scores=scores,
            consensus=consensus,
            fleiss_kappa=fleiss_k,
            krippendorff_alpha=kripp_a,
            calibrated=True,
            token_usage=total_in_tokens + total_out_tokens,
            cost_usd=cost_usd,
        )
