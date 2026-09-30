"""Equal-alert-budget check: for the same number of alerts, which method catches more incidents?

A method can send fewer false alarms just by alerting less. To tell smarter from quieter, each
method's sensitivity is turned through many settings, one setting for all series at once, and each
setting gives a point (alerts sent, incident windows caught). The best a method does within an alert
budget is the most windows any of its settings catches without going over it.

- Ops Signals, live (replay) and batch, and the z-score baseline: the confidence cutoff (KNOBS).
- Static threshold: its probationary [min, max] limits widened by a fraction of that range
  (MARGINS), the way a team moves the line to get fewer alerts. It is computed from the series'
  own values, so it is available even when the static-threshold method was skipped. Choosing its
  best margin needs the answer key, so its curve is the best a threshold can do with hindsight.

Alerts are counted as a person sees them: flags less than max(15 minutes, one sampling interval)
apart are one alert, for every method alike. Flags in NAB's probationary period don't count. A
window is caught when at least one flag falls inside it.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from benchmark.nab import metrics
from benchmark.nab.detector import static_threshold_scores

KNOBS = (0.01, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.88, 0.9, 0.92, 0.94, 0.96, 0.98, 0.99)
MARGINS = (0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)
USUAL = {"live": metrics.HEADLINE_THRESHOLD, "batch": metrics.HEADLINE_THRESHOLD,
         "zscore_only": metrics.HEADLINE_THRESHOLD, "static_threshold": 0.0}
LABELS = {
    "live": "Ops Signals, live alerts",
    "batch": "Ops Signals, batch review",
    "zscore_only": "Z-score only",
    "static_threshold": "Static threshold",
}
BUDGET_FRACTIONS = (0.1, 0.2, 0.3, 0.5, 0.75, 1.0)
MIN_GAP = np.timedelta64(15, "m")


class AlertBudget:
    """Adds up (alerts, windows caught) per method and setting, one series at a time."""

    def __init__(self) -> None:
        self.windows = 0
        self.points: dict[str, dict[float, list[int]]] = {}

    def add_series(self, timestamps: np.ndarray, values: np.ndarray, window_rows: list[tuple[int, int]],
                   scores: dict[str, list[float] | np.ndarray]) -> None:
        self.windows += len(window_rows)
        probation = metrics.probation_rows(len(values))
        diffs = np.sort(np.diff(timestamps))  # keeps the timestamps' own time unit
        gap = max(MIN_GAP, diffs[len(diffs) // 2]) if len(diffs) else MIN_GAP
        for method, method_scores in scores.items():
            values_ = np.asarray(method_scores, dtype=float)
            for knob in KNOBS:
                self._add(method, knob, np.nonzero(values_ >= knob)[0], timestamps, window_rows, probation, gap)
        for margin in MARGINS:
            flags = np.nonzero(static_threshold_scores(values, margin) > 0)[0]
            self._add("static_threshold", margin, flags, timestamps, window_rows, probation, gap)

    def _add(self, method: str, knob: float, rows: np.ndarray, timestamps: np.ndarray,
             window_rows: list[tuple[int, int]], probation: int, gap) -> None:
        rows = rows[rows >= probation]
        alerts = 1 + int((np.diff(timestamps[rows]) > gap).sum()) if len(rows) else 0
        caught = sum(1 for start, end in window_rows if ((rows >= start) & (rows <= end)).any())
        point = self.points.setdefault(method, {}).setdefault(knob, [0, 0])
        point[0] += alerts
        point[1] += caught

    def summary(self) -> dict[str, Any]:
        curves = {
            method: [{"setting": knob, "alerts": alerts, "caught": caught} for knob, (alerts, caught) in sorted(by_knob.items())]
            for method, by_knob in self.points.items()
        }
        usual = {method: next(p for p in curve if p["setting"] == USUAL[method]) for method, curve in curves.items()}
        threshold_alerts = usual["static_threshold"]["alerts"] if "static_threshold" in usual else 0
        budgets = sorted({max(1, round(threshold_alerts * f)) for f in BUDGET_FRACTIONS}
                         | {usual[m]["alerts"] for m in ("live", "batch") if m in usual and usual[m]["alerts"]})
        return {
            "windows": self.windows,
            "labels": {method: LABELS[method] for method in curves},
            "curves": curves,
            "usual": usual,
            "budgets": [{"alerts": budget, "caught": {method: best_under(curve, budget) for method, curve in curves.items()}}
                        for budget in budgets],
        }


def best_under(curve: list[dict[str, Any]], budget: int) -> int | None:
    """The most windows any setting catches with at most `budget` alerts; None when no setting is that quiet."""
    fits = [point["caught"] for point in curve if point["alerts"] <= budget]
    return max(fits) if fits else None
