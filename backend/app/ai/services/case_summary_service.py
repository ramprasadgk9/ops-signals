"""Case summarization helper."""

from __future__ import annotations


class CaseSummaryService:
    def summarize(self, case_title: str, root_cause: str | None = None, outcome: str | None = None) -> str:
        parts = [case_title]
        if root_cause:
            parts.append(f"RCA: {root_cause}")
        if outcome:
            parts.append(f"Outcome: {outcome}")
        return " | ".join(parts)
