from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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
    composite_score: float
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """A diagnosis passes if it correctly isolates the culprit entity AND root-cause."""
        return self.entity_match and self.root_cause_match


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

            inter_start = max(pred_start, exp_start)
            inter_end = min(pred_end, exp_end)

            if inter_end > inter_start:
                intersection = (inter_end - inter_start).total_seconds()
                union = (max(pred_end, exp_end) - min(pred_start, exp_start)).total_seconds()
                window_iou = intersection / union if union > 0 else 0.0
        elif not exp_window_dict and not predicted.fault_window:
            window_iou = 1.0

        # 4. Evidence Precision, Recall & F1
        expected_keys = [str(k).strip().lower() for k in ground_truth.get("key_evidence", [])]
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

        # Composite Score: weighted combination
        # Entity (35%), Root Cause (45%), Window IoU (10%), Evidence F1 (10%)
        composite_score = (
            (0.35 if entity_match else 0.0)
            + (0.45 if root_cause_match else 0.0)
            + (0.10 * window_iou)
            + (0.10 * evidence_f1)
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
            "predicted_raw_summary": predicted.raw_summary,
        }

        return F1EvaluationResult(
            entity_match=entity_match,
            root_cause_match=root_cause_match,
            window_iou=round(window_iou, 4),
            evidence_precision=round(evidence_precision, 4),
            evidence_recall=round(evidence_recall, 4),
            evidence_f1=round(evidence_f1, 4),
            composite_score=round(composite_score, 4),
            details=details,
        )
