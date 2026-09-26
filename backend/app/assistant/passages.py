"""Picks the passage of a retrieved documentation section that answers the question, and checks
that a passage an LLM claims to quote really is in the evidence.

A section chunk is up to ~900 characters; the answer to a question is usually one sentence,
list item, table row or code block inside it. Quoting that passage word for word, with its
citation, is what makes an answer checkable without AI - and verifying an LLM's quotes against
the evidence is a cheap guard against invented text when AI is on.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence

import numpy as np

# Longest quote returned; a code block or table row longer than this is cut, not dropped.
MAX_QUOTE_CHARS = 600
# A sentence next to the best one is quoted with it when it scores within this much of it.
NEIGHBOUR_MARGIN = 0.05

_FENCE = re.compile(r"^\s*(```|~~~)")
_IMAGE_OR_LINK = re.compile(r"(?:[-*+]\s+)?!?\[[^\]]*\]\([^)]*\)")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z`*(\[])")
_WORD = re.compile(r"[a-z0-9][a-z0-9_./:-]*")
_STOPWORDS = frozenset(
    "a an and are as at be by can could do does for from has have how i if in is it its my of on or "
    "our should so that the their them then there this to use used using was we what when where "
    "which who why will with would you your me any all get got into about ops signals".split()
)


def split_units(text: str) -> list[str]:
    """The quotable units of a section: prose sentences, list items, table rows, and whole fenced
    code blocks (never split - half a command is worse than none)."""
    return [unit for _, unit in _split_units(text)]


def _split_units(text: str) -> list[tuple[str, str]]:
    """split_units, with each unit's kind: "prose", "item", "row" or "code"."""
    units: list[tuple[str, str]] = []
    paragraph: list[str] = []
    fence: list[str] | None = None
    fence_marker = ""
    in_list_item = False

    def flush_paragraph() -> None:
        if paragraph:
            prose = " ".join(line.strip() for line in paragraph)
            units.extend(("prose", part.strip()) for part in _SENTENCE_END.split(prose) if part.strip())
            paragraph.clear()

    for line in text.splitlines():
        if fence is not None:
            fence.append(line)
            closing = _FENCE.match(line)
            if closing and closing.group(1) == fence_marker:
                units.append(("code", "\n".join(fence)))
                fence = None
            continue
        if _FENCE.match(line):
            flush_paragraph()
            fence = [line]
            fence_marker = _FENCE.match(line).group(1)
            in_list_item = False
        elif not line.strip():
            flush_paragraph()
            in_list_item = False
        elif _LIST_ITEM.match(line) or line.lstrip().startswith("|"):
            flush_paragraph()
            if not re.fullmatch(r"\s*\|[\s|:-]*\|\s*", line):
                units.append(("item" if _LIST_ITEM.match(line) else "row", line.strip()))
            in_list_item = bool(_LIST_ITEM.match(line))
        elif in_list_item and line.startswith(" "):
            # A wrapped list item's continuation line belongs to the item, not a new paragraph.
            units[-1] = (units[-1][0], f"{units[-1][1]} {line.strip()}")
        else:
            paragraph.append(line)
            in_list_item = False
    if fence is not None:
        units.append(("code", "\n".join(fence)))
    flush_paragraph()
    # An image or a bare link is not an answer to quote.
    return [(kind, unit) for kind, unit in units if unit.strip() and not _IMAGE_OR_LINK.fullmatch(unit.strip())]


def _terms(text: str) -> set[str]:
    return {word.strip("./:-") for word in _WORD.findall(text.lower()) if word not in _STOPWORDS and len(word) > 2}


def _is_identifier(term: str) -> bool:
    """Env vars, paths, file names, versions, ports - exact tokens an embedding blurs together."""
    return any(char in term for char in "_./:") or any(char.isdigit() for char in term)


def select_passage(
    question: str,
    text: str,
    encode_all: Callable[[Sequence[str]], list[list[float]]] | None = None,
) -> str | None:
    """The passage of `text` that best answers `question`.

    Units are ranked by embedding similarity to the question when `encode_all` is given, plus
    overlap with the question's words - weighted heavily for identifiers like
    OPS_SIGNALS_API_TOKEN that a question names exactly. The best unit is then widened to what it
    needs to make sense: the code block a lead-in ending in ":" introduces (or the lead-in of a
    chosen code block), the rest of a short list it belongs to, and a neighbouring sentence that
    scores nearly as well."""
    units = _split_units(text)
    if not units:
        return None
    question_terms = _terms(question)
    scores = np.zeros(len(units))
    if encode_all is not None:
        try:
            vectors = np.asarray(encode_all([question, *(unit for _, unit in units)]), dtype=float)
            scores += vectors[1:] @ vectors[0]
        except Exception:
            pass
    for index, (_, unit) in enumerate(units):
        overlap = question_terms & _terms(unit)
        if question_terms:
            scores[index] += 0.3 * len(overlap) / len(question_terms)
        scores[index] += 0.3 * sum(1 for term in overlap if _is_identifier(term))

    best = int(np.argmax(scores))
    first, last = best, best
    kind, unit = units[best]
    if unit.rstrip().endswith(":") and best + 1 < len(units):
        last = best + 1
    elif kind == "code" and best > 0:
        first = best - 1
    elif kind == "item":
        while first > 0 and units[first - 1][0] == "item" and _length(units, first - 1, last) <= MAX_QUOTE_CHARS:
            first -= 1
        while last + 1 < len(units) and units[last + 1][0] == "item" and _length(units, first, last + 1) <= MAX_QUOTE_CHARS:
            last += 1
    else:
        neighbours = [index for index in (best - 1, best + 1) if 0 <= index < len(units) and units[index][0] == kind]
        close = [index for index in neighbours if scores[index] >= scores[best] - NEIGHBOUR_MARGIN]
        if close:
            neighbour = max(close, key=lambda index: scores[index])
            if _length(units, min(best, neighbour), max(best, neighbour)) <= MAX_QUOTE_CHARS:
                first, last = min(best, neighbour), max(best, neighbour)

    quote = "\n".join(unit for _, unit in units[first : last + 1])
    return quote if len(quote) <= MAX_QUOTE_CHARS else quote[: MAX_QUOTE_CHARS - 3].rstrip() + "..."


def _length(units: list[tuple[str, str]], first: int, last: int) -> int:
    return sum(len(unit) + 1 for _, unit in units[first : last + 1])


def _normalize(text: str) -> str:
    text = re.sub(r"[`*_>\"“”‘’']", "", text.lower())
    return re.sub(r"\s+", " ", text).strip(" .…")


def quote_is_in(quote: str, evidence: str) -> bool:
    """Whether `quote` appears in `evidence`, ignoring case, whitespace, quotation marks and
    Markdown emphasis. An ellipsis splits a quote into parts that must each appear, in order."""
    haystack = _normalize(evidence)
    position = 0
    for part in re.split(r"\.\.\.|…", quote):
        needle = _normalize(part)
        if not needle:
            continue
        found = haystack.find(needle, position)
        if found < 0:
            return False
        position = found + len(needle)
    return True
