"""The UCR archive's scoring rule: one predicted location per series, correct or not.

From the archive's own slides (UCR_AnomalyDataSets.pptx, "Scoring Function Design Principles"):
with L = end - begin + 1, a prediction P is correct if

    min(begin - L, begin - 100) < P < max(end + L, end + 100)

The slack absorbs whether a method reports the leading edge, centre or trailing edge of a window,
and the 100-point floor covers anomalies as short as one point. Accuracy is the share of series
answered correctly. Positions are 1-based, as in the file names.
"""

from __future__ import annotations

MIN_SLACK = 100


def correct_region(begin: int, end: int) -> tuple[int, int]:
    """The exclusive bounds (low, high): P is correct when low < P < high."""
    length = end - begin + 1
    return min(begin - length, begin - MIN_SLACK), max(end + length, end + MIN_SLACK)


def is_correct(position: int | None, begin: int, end: int) -> bool:
    if position is None:
        return False
    low, high = correct_region(begin, end)
    return low < position < high


def default_rate(n_points: int, train_end: int, begin: int, end: int) -> float:
    """Chance that a uniformly random guess in the test part (positions train_end+1..n) is correct:
    the "random dart" rate the scoring rule is designed to keep close to zero."""
    low, high = correct_region(begin, end)
    first, last = train_end + 1, n_points
    hits = max(0, min(high - 1, last) - max(low + 1, first) + 1)
    return hits / max(1, last - first + 1)
