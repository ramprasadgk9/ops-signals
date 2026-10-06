"""Keyword (BM25-style) sparse vectors for hybrid recall.

The MiniLM embedding blurs the exact tokens ops text depends on - service names, metric names,
error codes, versions ("checkout-api", "http_requests_errors_total", "5xx", "v2.3", "oomkilled").
A sparse vector keeps them, so hybrid search can rank a past case that names the same service and
error above one that is only about something similar.

Only term frequency is computed here. The collection's sparse vector is configured with
Modifier.IDF, so Qdrant applies inverse document frequency itself from the current collection;
nothing here needs corpus statistics, and they never go out of date as cases are added.
"""

from __future__ import annotations

import re
import zlib
from collections import Counter

from qdrant_client.models import SparseVector

# Name of the sparse vector in a hybrid collection; the dense vector stays the unnamed default.
TEXT_VECTOR = "text"

# BM25 term-frequency saturation. AVERAGE_LENGTH is a fixed stand-in for the corpus average (the
# same simplification Qdrant's own BM25 model makes); case documents run 60-200 tokens.
K1 = 1.2
B = 0.75
AVERAGE_LENGTH = 120.0

# Lowercase words, keeping joined compounds whole: checkout-api, http_requests_errors_total, v2.3.
_TOKEN = re.compile(r"[a-z0-9]+(?:[._\-/:][a-z0-9]+)*")
_PARTS = re.compile(r"[a-z0-9]+")

_STOPWORDS = frozenset(
    """a an and are as at be been but by for from had has have in into is it its of on or that the
    their there this to was were which while with after before during over under up down than then
    not no so if when what who how all any each per via""".split()
)


def tokenize(text: str) -> list[str]:
    """Words, plus the parts of each compound, so "checkout-api" also matches a plain "checkout"."""
    tokens: list[str] = []
    for match in _TOKEN.finditer((text or "").lower()):
        word = match.group(0)
        parts = _PARTS.findall(word)
        candidates = [word, *parts] if len(parts) > 1 else [word]
        tokens.extend(token for token in candidates if len(token) > 1 and token not in _STOPWORDS)
    return tokens


def _index(token: str) -> int:
    # Stable across processes (unlike hash()), so stored vectors and later queries agree.
    return zlib.crc32(token.encode("utf-8"))


def document_vector(text: str) -> SparseVector | None:
    """The sparse vector stored with a case; None when the text has no usable words."""
    tokens = tokenize(text)
    if not tokens:
        return None
    counts = Counter(tokens)
    length_norm = K1 * (1 - B + B * len(tokens) / AVERAGE_LENGTH)
    weights: dict[int, float] = {}
    for token, tf in counts.items():
        index = _index(token)
        weights[index] = weights.get(index, 0.0) + tf * (K1 + 1) / (tf + length_norm)
    indices = sorted(weights)
    return SparseVector(indices=indices, values=[weights[index] for index in indices])


def query_vector(text: str) -> SparseVector | None:
    """The sparse query: each distinct word once; Qdrant's IDF does the weighting."""
    indices = sorted({_index(token) for token in tokenize(text)})
    if not indices:
        return None
    return SparseVector(indices=indices, values=[1.0] * len(indices))
