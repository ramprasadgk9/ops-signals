from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from benchmark.iam_vs_llm.evaluators.normalization import NormalizedRCA
from benchmark.iam_vs_llm.evaluators.taxonomy import RootCauseClass


@dataclass(slots=True)
class F1EvaluationResult:
    """Quantitative scoring result of an RCA diagnosis against ground truth."""
    entity_match: bool
    root_cause_match: bool
    window_iou: float
    evidence_precision: float
    evidence_recall: float
    evidence_f1: float
    semantic_similarity: float
    composite_score: float
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> str:
        """Tri-state status: SUCCESS, PARTIAL, or FAILED.
        
        Prevents overstating success when fault windows or evidence recall are degraded.
        """
        if not (self.entity_match and self.root_cause_match):
            return "FAILED"
        if self.window_iou >= 0.50 and self.evidence_recall >= 0.70 and self.composite_score >= 0.80:
            return "SUCCESS"
        return "PARTIAL"

    @property
    def passed(self) -> bool:
        """A diagnosis passes strictly if it achieves full SUCCESS."""
        return self.status == "SUCCESS"


class F1Evaluator:
    """Deterministic evaluator for root-cause diagnosis against curated ground truth."""

    def evaluate(self, predicted: NormalizedRCA, ground_truth: dict[str, Any]) -> F1EvaluationResult:
        expected_entity = str(ground_truth.get("entity", "")).strip().lower()
        expected_rc_str = str(ground_truth.get("root_cause", "")).strip().upper()
        
        try:
            expected_root_cause = RootCauseClass(expected_rc_str)
        except ValueError:
            expected_root_cause = RootCauseClass.UNKNOWN

        # 1. Entity Match
        pred_entity = str(predicted.entity or "").strip().lower()
        entity_match = bool(pred_entity and pred_entity == expected_entity)

        # 2. Root Cause Match
        root_cause_match = bool(predicted.root_cause == expected_root_cause and expected_root_cause != RootCauseClass.UNKNOWN)

        # 3. Window IoU
        window_iou = 0.0
        exp_window_dict = ground_truth.get("fault_window")
        if exp_window_dict and predicted.fault_window:
            exp_start = datetime.fromisoformat(str(exp_window_dict["start"]).replace("Z", "+00:00"))
            exp_end = datetime.fromisoformat(str(exp_window_dict["end"]).replace("Z", "+00:00"))
            pred_start, pred_end = predicted.fault_window

            # Normalize tzinfo to UTC to avoid offset-naive vs offset-aware comparison crashes
            if pred_start.tzinfo is None:
                pred_start = pred_start.replace(tzinfo=timezone.utc)
            if pred_end.tzinfo is None:
                pred_end = pred_end.replace(tzinfo=timezone.utc)
            if exp_start.tzinfo is None:
                exp_start = exp_start.replace(tzinfo=timezone.utc)
            if exp_end.tzinfo is None:
                exp_end = exp_end.replace(tzinfo=timezone.utc)

            inter_start = max(pred_start, exp_start)
            inter_end = min(pred_end, exp_end)

            if inter_end > inter_start:
                intersection = (inter_end - inter_start).total_seconds()
                union = (max(pred_end, exp_end) - min(pred_start, exp_start)).total_seconds()
                window_iou = intersection / union if union > 0 else 0.0
        elif not exp_window_dict and not predicted.fault_window:
            window_iou = 1.0

        # 4. Evidence Precision, Recall & F1
        raw_evidence = ground_truth.get("key_evidence", [])
        if isinstance(raw_evidence, dict):
            expected_keys = [
                str(k).strip().lower()
                for sublist in raw_evidence.values()
                for k in (sublist if isinstance(sublist, list) else [sublist])
            ]
        else:
            expected_keys = [str(k).strip().lower() for k in raw_evidence]
        pred_keys = [str(k).strip().lower() for k in predicted.evidence_keys]

        if pred_keys and expected_keys:
            pred_set = set(pred_keys)
            exp_set = set(expected_keys)
            tp = len(pred_set & exp_set)
            evidence_precision = tp / len(pred_set)
            evidence_recall = tp / len(exp_set)
            denom = evidence_precision + evidence_recall
            evidence_f1 = (2 * evidence_precision * evidence_recall / denom) if denom > 0 else 0.0
        elif not expected_keys and not pred_keys:
            evidence_precision = 1.0
            evidence_recall = 1.0
            evidence_f1 = 1.0
        else:
            evidence_precision = 0.0
            evidence_recall = 0.0
            evidence_f1 = 0.0

        # 5. Semantic Concept Similarity (deterministic token overlap against ground truth concepts)
        pred_words = set(re.findall(r"[a-zA-Z0-9]+", (predicted.raw_summary or "").lower()))
        exp_concepts = [expected_entity, expected_root_cause.value.lower()] + [
            str(s).lower() for s in ground_truth.get("secondary_symptoms", [])
        ]
        exp_words = set(re.findall(r"[a-zA-Z0-9]+", " ".join(exp_concepts).lower()))
        if pred_words and exp_words:
            overlap = len(pred_words & exp_words)
            semantic_similarity = overlap / len(exp_words) if exp_words else 0.0
            semantic_similarity = min(1.0, max(0.0, semantic_similarity))
        else:
            semantic_similarity = 0.0

        # Composite Score: weighted combination
        # Entity (30%), Root Cause (35%), Window IoU (10%), Evidence F1 (15%), Semantic Similarity (10%)
        composite_score = (
            (0.30 if entity_match else 0.0)
            + (0.35 if root_cause_match else 0.0)
            + (0.10 * window_iou)
            + (0.15 * evidence_f1)
            + (0.10 * semantic_similarity)
        )

        details = {
            "expected_entity": expected_entity,
            "predicted_entity": pred_entity,
            "expected_root_cause": expected_root_cause.value,
            "predicted_root_cause": predicted.root_cause.value,
            "window_iou": window_iou,
            "evidence_precision": evidence_precision,
            "evidence_recall": evidence_recall,
            "evidence_f1": evidence_f1,
            "semantic_similarity": semantic_similarity,
            "predicted_raw_summary": predicted.raw_summary,
        }
        result = F1EvaluationResult(
            entity_match=entity_match,
            root_cause_match=root_cause_match,
            window_iou=round(window_iou, 4),
            evidence_precision=round(evidence_precision, 4),
            evidence_recall=round(evidence_recall, 4),
            evidence_f1=round(evidence_f1, 4),
            semantic_similarity=round(semantic_similarity, 4),
            composite_score=round(composite_score, 4),
            details=details,
        )
        result.details["status"] = result.status
        return result
