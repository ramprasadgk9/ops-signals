"""Recorded AI answers: replays what a real model answered, for the hosted demo (docs/demo.md).

Recording: with OPS_SIGNALS_AI_RECORD_TO=<file>, every answer the configured provider gives is
saved there with its question (RecordingLLMClient). Replay: OPS_SIGNALS_AI_PROVIDER=recorded answers
from such a file (OPS_SIGNALS_AI_RECORDED_FILE) without any model running.

The demo is seeded again on every reset, so the same question comes back with other times, case
numbers and durations. A question is matched with every number taken out: the system message (which
feature is asking) must be the same, and the closest recorded question must be at least
MATCH_THRESHOLD alike. With no match the call fails like a model that's down, and the feature shows
its usual "not available" fallback; a recorded answer is never stretched to another question. An
answer that quotes a number from its recorded question that today's question doesn't have (a
percentage, a case number) isn't replayed either, since not every feature checks its answer.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from difflib import SequenceMatcher
from pathlib import Path

from backend.app.ai.exceptions import LLMRequestError
from backend.app.ai.interfaces import LLMClient, LLMRequest, LLMResponse

logger = logging.getLogger(__name__)

MATCH_THRESHOLD = 0.8
_NUMBER = re.compile(r"\d+(?:[.:,]\d+)*")
_SPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """The question without the parts a new seed changes: numbers (times, ids, durations, sizes)."""
    return _SPACE.sub(" ", _NUMBER.sub("#", text.lower())).strip()


def stale_numbers(reply: str, recorded_question: str, question: str) -> set[str]:
    """Numbers the recorded answer took from its recorded question that today's question doesn't
    have. Numbers the answer didn't take from the question ("1-3 steps", a list's "1.") don't count."""
    from_data = set(_NUMBER.findall(reply)) & set(_NUMBER.findall(recorded_question))
    return from_data - set(_NUMBER.findall(question))


def _split(request: LLMRequest) -> tuple[str, str]:
    system = "\n".join(message.content for message in request.messages if message.role == "system")
    user = "\n".join(message.content for message in request.messages if message.role != "system")
    return system, user


class RecordedLLMClient(LLMClient):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        entries = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []
        self.model = "recorded"
        self._by_system: dict[str, list[tuple[str, dict]]] = {}
        for entry in entries:
            self._by_system.setdefault(normalize(entry["system"]), []).append((normalize(entry["user"]), entry))
        logger.info("Recorded AI answers: %d from %s", len(entries), self.path)

    def generate(self, request: LLMRequest) -> LLMResponse:
        start = time.perf_counter()
        system, user = _split(request)
        candidates = self._by_system.get(normalize(system), [])
        question = normalize(user)
        best, score = None, 0.0
        for recorded, entry in candidates:
            ratio = 1.0 if recorded == question else SequenceMatcher(None, recorded, question, autojunk=False).ratio()
            if ratio > score:
                best, score = entry, ratio
        if best is None or score < MATCH_THRESHOLD:
            raise LLMRequestError("No recorded answer for this question")
        if stale_numbers(best["reply"], best["user"], user):
            # The answer quotes data from the day it was recorded ("up 2616%", "case #7") that today's
            # question doesn't have. Not every feature checks its answer, so it's never shown.
            raise LLMRequestError("The recorded answer quotes numbers today's data doesn't have")
        return LLMResponse(
            content=best["reply"],
            model=best.get("model") or "recorded",
            provider="recorded",
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
        )


class RecordingLLMClient(LLMClient):
    """Passes every request to the real provider and saves each answer with its question."""

    def __init__(self, inner: LLMClient, path: str | Path, model: str | None = None) -> None:
        self.inner = inner
        self.path = Path(path)
        self.model = model
        self._lock = threading.Lock()

    def __getattr__(self, name: str):
        return getattr(self.inner, name)

    def generate(self, request: LLMRequest) -> LLMResponse:
        response = self.inner.generate(request)
        system, user = _split(request)
        entry = {"system": system, "user": user, "reply": response.content, "model": response.model or self.model}
        with self._lock:
            entries = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []
            # One answer per question (numbers aside): the latest wins, so re-recording replaces.
            key = (normalize(system), normalize(user))
            entries = [item for item in entries if (normalize(item["system"]), normalize(item["user"])) != key]
            entries.append(entry)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return response
