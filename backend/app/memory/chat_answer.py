"""The answer text for operational-memory chat, shared by the API and MCP endpoints."""

from __future__ import annotations

from backend.app.memory.schemas import MemoryChatSource
from backend.app.memory.similarity_service import STRONG_MATCH_SCORE


def chat_answer_lines(sources: list[MemoryChatSource]) -> list[str]:
    """What the chat says about its sources. A match below the strong-match score is still shown,
    but called a possible match: hiding it used to leave the right past case unmentioned for half of
    ordinary questions, which rarely score high (QA-16)."""
    if not sources:
        return [
            "I could not find a related case in operational memory.",
            "Try asking about a specific service, metric, or case, or lower the similarity threshold.",
        ]
    top = sources[0]
    if top.similarity_score >= STRONG_MATCH_SCORE:
        closest = f"The closest match is case #{top.case_id} ({top.title}) with a similarity score of {top.similarity_score:.2f}."
    else:
        closest = (
            f"The closest match is case #{top.case_id} ({top.title}), a possible match with a similarity "
            f"score of {top.similarity_score:.2f}: check that it fits before relying on it."
        )
    lines = [f"I found {len(sources)} related case{'s' if len(sources) != 1 else ''} in operational memory.", closest]
    if top.root_cause_summary:
        lines.append(f"That case recorded this RCA summary: {top.root_cause_summary}")
    elif top.outcome_summary:
        lines.append(f"That case recorded this outcome: {top.outcome_summary}")
    else:
        lines.append("The match contains useful operational context, but no RCA or outcome summary yet.")
    lines.append("Use the source cases below to inspect the evidence before treating this as a final conclusion.")
    return lines
