"""Grounded explanation helper."""

from __future__ import annotations


class ExplanationService:
    def explain(self, title: str, evidence: list[str], context: str | None = None) -> str:
        parts = [title]
        if context:
            parts.append(context)
        if evidence:
            parts.append("Evidence: " + "; ".join(evidence))
        return " ".join(parts)
