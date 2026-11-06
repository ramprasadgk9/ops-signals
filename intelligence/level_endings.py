"""Whether a level change is over: the level went back near where it was before the jump.

A level change's checks (ruptures, baseline_shift) compare the level before the jump with
everything after it, up to the last reading, so its findings always read as still going, and once
the way back is in the window they stop finding a single jump at all. So whether it's over is
decided here, after each run, from the run's own latest readings of the series and the levels the
finding saved: "back" when most of the jump is undone and stays undone for a while.

Each change of state is saved as a new row (PostgresStore.save_level_events); finding rows are
never edited. backend/app/services/active_findings.py problem_states reads them back.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

# Back: the latest readings undid at least this share of the jump, on average.
BACK_SHARE = 0.8
# Partly back: at least this share, but less than BACK_SHARE. Shown on the card, nothing moves.
PARTLY_SHARE = 0.3
# A reading counts towards a stretch that's back (or partly back) once it undid this much of the
# jump on its own, so one noisy reading doesn't end the stretch.
BACK_READING_SHARE = 0.5
PARTLY_READING_SHARE = 0.2
# The stretch must last this long, with at least MIN_READINGS readings.
MIN_STRETCH = timedelta(minutes=15)
MIN_READINGS = 3

ENDED, PARTLY_BACK, REOPENED = "ended", "partly_back", "reopened"


@dataclass(frozen=True)
class OpenLevelChange:
    """A level-change problem on the series, from its first level-change finding: later runs can
    see the way back as a change of its own ("dropped and stayed lower"), linked to the same
    problem, so the newest finding's levels aren't the jump's."""

    problem_id: int
    before: float
    after: float
    change_at: datetime
    # The kind of the problem's latest event, None when it has none (still open).
    state: str | None = None


@dataclass(frozen=True)
class LevelEvent:
    problem_id: int
    kind: str
    # When the stretch that's back (or partly back, or high again) began.
    at: datetime
    # When the level jumped: the problem's first level change.
    changed_at: datetime
    level_before: float
    level_during: float | None
    level_now: float


def _utc(value) -> datetime:
    moment = pd.Timestamp(value)
    return (moment.tz_localize("UTC") if moment.tzinfo is None else moment.tz_convert("UTC")).to_pydatetime()


def _stretch(readings: pd.DataFrame, undone: pd.Series, reading_share: float) -> pd.DataFrame | None:
    """The trailing readings that each undid at least `reading_share` of the jump, if they last."""
    kept = 0
    for value in reversed(undone.to_list()):
        if value < reading_share:
            break
        kept += 1
    if kept < MIN_READINGS:
        return None
    stretch = readings.iloc[-kept:]
    if stretch["timestamp"].iloc[-1] - stretch["timestamp"].iloc[0] < MIN_STRETCH:
        return None
    return stretch


def level_event(problem: OpenLevelChange, points: pd.DataFrame) -> LevelEvent | None:
    """The event this run's readings of the series call for, or None when nothing changed. `points`
    are the run's readings of the problem's series (timestamp, value)."""
    jump = problem.after - problem.before
    if not jump:
        return None
    readings = points[["timestamp", "value"]].copy()
    readings["timestamp"] = pd.to_datetime(readings["timestamp"], utc=True, errors="coerce")
    readings = readings.dropna(subset=["timestamp"]).sort_values("timestamp")
    readings = readings[readings["timestamp"] > pd.Timestamp(problem.change_at)]
    if readings.empty:
        return None
    # A gap at the end of the data is no proof either way: check only readings that all arrived.
    if readings["value"].tail(MIN_READINGS).isna().any():
        return None
    readings = readings.dropna(subset=["value"])
    undone = (problem.after - readings["value"].astype(float)) / jump

    def event(kind: str, stretch: pd.DataFrame) -> LevelEvent:
        at = _utc(stretch["timestamp"].iloc[0])
        during = readings[readings["timestamp"] < stretch["timestamp"].iloc[0]]["value"]
        return LevelEvent(
            problem.problem_id,
            kind,
            at,
            problem.change_at,
            problem.before,
            float(during.median()) if not during.empty else None,
            float(stretch["value"].mean()),
        )

    back = _stretch(readings, undone, BACK_READING_SHARE)
    if back is not None and undone.loc[back.index].mean() >= BACK_SHARE:
        return event(ENDED, back) if problem.state != ENDED else None
    partly = _stretch(readings, undone, PARTLY_READING_SHARE)
    if partly is not None and undone.loc[partly.index].mean() >= PARTLY_SHARE:
        return event(PARTLY_BACK, partly) if problem.state != PARTLY_BACK else None
    if problem.state in (ENDED, PARTLY_BACK):
        # High again: the latest stretch undid little of the jump.
        high = _stretch(readings, 1 - undone, 1 - PARTLY_READING_SHARE)
        if high is not None:
            return event(REOPENED, high)
    return None
