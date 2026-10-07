"""Masks secrets and personal data in imported incident text.

Imported text is stored in Postgres, embedded into Qdrant and quoted back by the assistant, so it is
cleaned once, before any of that happens. The patterns favour obvious, low-false-positive shapes;
anything they miss is the exporter's job (docs/importing-incident-history.md lists what to remove).
"""

from __future__ import annotations

import re

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[email]"),
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9\-._~+/]{8,}=*"), r"\1 [secret]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[secret]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "[secret]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), "[secret]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), "[secret]"),
    (
        re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)(\s*[:=]\s*)[\"']?(?!\[secret\])[^\s\"',;]+"),
        r"\1\2[secret]",
    ),
    (re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"), "[ip]"),
]


def redact(text: str) -> tuple[str, int]:
    """Returns the text with each match replaced by a placeholder, and how many were replaced."""
    total = 0
    for pattern, replacement in _PATTERNS:
        text, count = pattern.subn(replacement, text)
        total += count
    return text, total
