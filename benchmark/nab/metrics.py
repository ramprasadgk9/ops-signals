"""Window-level detection metrics over NAB's labeled anomaly windows.

These are this harness's own plain metrics, not NAB's official score (which weights detections by
how early in a window they land and applies three cost profiles). They follow NAB's conventions
where the two overlap:

- The first min(floor(0.15 x rows), 750) rows of each series are NAB's probationary period, and
  alarms there are ignored (NAB's nab/util.py getProbationPeriod).
- A window counts as detected when at least one alarm falls inside it. Only the first alarm in a
  window matters; later alarms in the same window are neither rewarded nor penalized.
- Every alarm outside all windows is a false alarm.

An alarm is a row whose anomaly score is at or above the threshold being evaluated.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

PROBATIONARY_PERCENT = 0.15
THRESHOLDS = (0.01, 0.25, 0.5, 0.75, 0.9)
HEADLINE_THRESHOLD = 0.5


def probation_rows(rows: int) -> int:
    return int(min(math.floor(PROBATIONARY_PERCENT * rows), PROBATIONARY_PERCENT * 5000))


@dataclass(slots=True)
class WindowCounts:
    windows: int = 0
    detected_windows: int = 0
    alarms: int = 0
    alarms_in_windows: int = 0
    false_alarms: int = 0
    # Where in each detected window its first alarm landed, as a fraction of the window's length.
    detection_positions: tuple[float, ...] = ()

    def add(self, other: "WindowCounts") -> None:
        self.windows += other.windows
        self.detected_windows += other.detected_windows
        self.alarms += other.alarms
        self.alarms_in_windows += other.alarms_in_windows
        self.false_alarms += other.false_alarms
        self.detection_positions = self.detection_positions + other.detection_positions

    def summary(self) -> dict[str, Any]:
        recall = self.detected_windows / self.windows if self.windows else None
        precision = self.alarms_in_windows / self.alarms if self.alarms else None
        f1 = (
            2 * recall * precision / (recall + precision)
            if recall is not None and precision is not None and (recall + precision) > 0
            else None
        )
        payload = asdict(self)
        payload.pop("detection_positions")
        payload.update(
            {
                "window_recall": recall,
                "alarm_precision": precision,
                "f1": f1,
                "median_detection_position": float(np.median(self.detection_positions)) if self.detection_positions else None,
            }
        )
        return payload


def score_series(scores: list[float], window_rows: list[tuple[int, int]], threshold: float) -> WindowCounts:
    values = np.asarray(scores, dtype=float)
    alarms = np.nonzero(values >= threshold)[0]
    alarms = alarms[alarms >= probation_rows(len(values))]
    in_window = np.zeros(len(alarms), dtype=bool)
    positions: list[float] = []
    detected = 0
    for start, end in window_rows:
        inside = (alarms >= start) & (alarms <= end)
        in_window |= inside
        if inside.any():
            detected += 1
            first = int(alarms[inside][0])
            positions.append((first - start) / max(1, end - start))
    return WindowCounts(
        windows=len(window_rows),
        detected_windows=detected,
        alarms=int(len(alarms)),
        alarms_in_windows=int(in_window.sum()),
        false_alarms=int((~in_window).sum()),
        detection_positions=tuple(positions),
    )


def window_rows(timestamps: np.ndarray, windows: list[list[str]]) -> list[tuple[int, int]]:
    """Map NAB's [start, end] window timestamps onto row indexes of the series (both inclusive)."""
    rows = []
    for start, end in windows:
        first = int(np.searchsorted(timestamps, np.datetime64(start.replace(" ", "T")), side="left"))
        last = int(np.searchsorted(timestamps, np.datetime64(end.replace(" ", "T")), side="right")) - 1
        if first <= last:
            rows.append((first, last))
    return rows
