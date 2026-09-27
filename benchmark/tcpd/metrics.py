"""TCPD's evaluation metrics: F1 against multiple annotators, and segmentation covering.

Ported unchanged in logic from TCPDBench (analysis/scripts/metrics.py, van den Burg & Williams,
"An Evaluation of Change Point Detection Algorithms", 2020). The TCPD suite checks this port by
recomputing every published score in TCPDBench's summaries from the published change points and
confirming they match.

Original notice:

    Copyright (c) 2020 - The Alan Turing Institute

    Permission is hereby granted, free of charge, to any person obtaining a copy of this software
    and associated documentation files (the "Software"), to deal in the Software without
    restriction, including without limitation the rights to use, copy, modify, merge, publish,
    distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the
    Software is furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all copies or
    substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING
    BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
    NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
    DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

All change point locations are 0-based indexes of the first observation of a new segment.
Index 0 is always treated as a change point, for both annotators and predictions.
"""

from __future__ import annotations

from typing import Iterable, Mapping

MARGIN = 5


def true_positives(T: Iterable[int], X: Iterable[int], margin: int = MARGIN) -> set[int]:
    """Annotated points in T matched by a distinct prediction in X within `margin`, nearest first."""
    X = set(list(X))
    TP = set()
    for tau in T:
        close = [(abs(tau - x), x) for x in X if abs(tau - x) <= margin]
        close.sort()
        if not close:
            continue
        _, xstar = close[0]
        TP.add(tau)
        X.remove(xstar)
    return TP


def f_measure(
    annotations: Mapping[str, Iterable[int]],
    predictions: Iterable[int],
    margin: int = MARGIN,
    alpha: float = 0.5,
    return_PR: bool = False,
):
    """F-measure against several annotators: precision against the union of everyone's change
    points, recall averaged over annotators."""
    Tks = {k + 1: set(annotations[uid]) for k, uid in enumerate(annotations)}
    for Tk in Tks.values():
        Tk.add(0)

    X = set(predictions)
    X.add(0)

    # Built one element at a time, as in the original: matching is greedy over set iteration
    # order, and that order depends on how the set was built.
    Tstar = set()
    for Tk in Tks.values():
        for tau in Tk:
            Tstar.add(tau)

    K = len(Tks)
    P = len(true_positives(Tstar, X, margin=margin)) / len(X)
    TPk = {k: true_positives(Tks[k], X, margin=margin) for k in Tks}
    R = 1 / K * sum(len(TPk[k]) / len(Tks[k]) for k in Tks)

    F = P * R / (alpha * R + (1 - alpha) * P)
    if return_PR:
        return F, P, R
    return F


def overlap(A: set[int], B: set[int]) -> float:
    """Jaccard index of two sets."""
    return len(A.intersection(B)) / len(A.union(B))


def partition_from_cps(locations: Iterable[int], n_obs: int) -> list[set[int]]:
    """The partition of [0, n_obs - 1] the change point locations define."""
    partition = []
    current: set[int] = set()
    all_cps = iter(sorted(set(locations)))
    cp = next(all_cps, None)
    for i in range(n_obs):
        if i == cp:
            if current:
                partition.append(current)
            current = set()
            cp = next(all_cps, None)
        current.add(i)
    partition.append(current)
    return partition


def cover_single(S: list[set[int]], Sprime: list[set[int]]) -> float:
    """Covering of segmentation S by Sprime (Arbelaez et al., 2010, eq. 8)."""
    T = sum(map(len, Sprime))
    assert T == sum(map(len, S))
    C = 0.0
    for R in S:
        C += len(R) * max(overlap(R, Rprime) for Rprime in Sprime)
    return C / T


def covering(annotations: Mapping[str, Iterable[int]], predictions: Iterable[int], n_obs: int) -> float:
    """Segmentation covering of the predictions, averaged over annotators."""
    Ak = {k + 1: partition_from_cps(annotations[uid], n_obs) for k, uid in enumerate(annotations)}
    pX = partition_from_cps(predictions, n_obs)
    Cs = [cover_single(Ak[k], pX) for k in Ak]
    return sum(Cs) / len(Cs)
