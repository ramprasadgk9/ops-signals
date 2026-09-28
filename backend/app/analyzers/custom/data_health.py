from __future__ import annotations

import numpy as np
import pandas as pd

from intelligence.analyzers.base import Analyzer
from intelligence.capability import Capability
from intelligence.signals.schema import OperationalSignal

# The same identity columns normalize_timeseries resamples on, so each group here is exactly one
# resampled series - two hosts' points are never read as one series.
_SERIES_COLUMNS = ["metric_name", "service", "env", "host", "namespace", "pod", "source", "unit", "metric_type"]


class DataHealthAnalyzer(Analyzer):
    """Reports metrics that stopped reporting (a gap) or stopped changing (a flatline).

    Input:
        dataframe: normalized time-series rows. After normalization, a time bucket with no data
        is a row whose value is NaN - that is how a gap shows up here.

    Output:
        `data_gap` and `flatline` signals. Nothing for a healthy series.

    Both checks compare a stretch against the series' own normal behavior, so they stay quiet on
    metrics that are sparse or constant by design:
      - a gap is only reported for a series that normally reports (little missing data elsewhere);
      - a flatline is only reported for a series that normally changes from point to point, so an
        error counter sitting at 0 or a replica count that is always 3 is not flagged;
      - a series that only jitters around one value (e.g. the rate of a counter that ticks once per
        scrape) counts as constant, not as "normally changing";
      - a flatline at the metric's own floor or ceiling is not reported: an error rate parked at
        its minimum while load is low is clamped, not stalled. It counts as a floor or ceiling only
        if the metric also sits at exactly that value at other times - a counter or a climbing
        gauge that freezes at its latest (and so highest) value never has, so that stall is still
        reported, as is a value frozen mid-range or beyond where the metric normally goes.
        One exception: a run of exact zeros is still reported if the metric has never before
        stayed at zero for even half as long. A busy count that drops to 0 and stays there (every
        NAB tweet-volume series hit 0 at the same moment for two hours - a collector outage) is
        a source that stopped sending, not a floor; a stray zero now and then doesn't excuse it.

    Known blind spots, accepted rather than fixed:
      - a series where long runs of zeros are normal (a low-volume count that is often 0) can't
        tell an outage from a quiet period, so an outage there is not reported;
      - the other way round, a busy service's error rate that drops to exactly 0 for a long
        stretch, for the first time in the window, is reported as stuck at 0 even if errors
        really did stop. An error rate that touches 0 routinely is not affected.

    A series that went silent before the end of the window can't be seen in the data alone -
    normalization ends each series at its last point. Runs that know the requested window end
    (Prometheus-backed runs) pass it in through set_analysis_window_end; the trailing silence is
    then reported as an ongoing `data_gap`. Without it (CSV uploads, OTLP pushes) that check is off.
    """

    analyzer_id = "data_health"

    def __init__(
        self,
        gap_multiple: float = 5.0,
        max_normal_missing_ratio: float = 0.2,
        min_flatline_minutes: float = 30.0,
        min_flatline_points: int = 5,
        min_normal_change_ratio: float = 0.8,
        max_constant_spread_ratio: float = 1e-4,
        edge_tolerance_ratio: float = 0.05,
        min_edge_repeats: int = 3,
        min_zero_floor_run_ratio: float = 0.5,
        **config: object,
    ) -> None:
        self.gap_multiple = float(gap_multiple)
        self.max_normal_missing_ratio = float(max_normal_missing_ratio)
        self.min_flatline_minutes = float(min_flatline_minutes)
        self.min_flatline_points = max(2, int(min_flatline_points))
        self.min_normal_change_ratio = float(min_normal_change_ratio)
        self.max_constant_spread_ratio = float(max_constant_spread_ratio)
        self.edge_tolerance_ratio = float(edge_tolerance_ratio)
        self.min_edge_repeats = max(1, int(min_edge_repeats))
        self.min_zero_floor_run_ratio = float(min_zero_floor_run_ratio)
        self.config = config
        self.analysis_window_end: pd.Timestamp | None = None

    def set_analysis_window_end(self, window_end: pd.Timestamp) -> None:
        self.analysis_window_end = window_end

    def capability(self) -> Capability:
        return Capability(
            id="data_health",
            title="Data Health",
            description="Detects metrics that stopped reporting or stopped changing.",
            analyzer_id=self.analyzer_id,
            enabled=True,
            supported_question_ids=["service_health", "investigation_priority"],
        )

    def analyze(self, dataframe: pd.DataFrame) -> list[OperationalSignal]:
        if dataframe.empty:
            return []
        group_columns = [column for column in _SERIES_COLUMNS if column in dataframe.columns]
        signals: list[OperationalSignal] = []
        for _, group in dataframe.groupby(group_columns, dropna=False):
            ordered = group.sort_values("timestamp").reset_index(drop=True)
            if len(ordered) < 3:
                continue
            interval = ordered["timestamp"].diff().dropna().median()
            if pd.isna(interval) or interval <= pd.Timedelta(0):
                continue
            signals.extend(self._gaps(ordered, interval))
            signals.extend(self._flatlines(ordered, interval))
            signals.extend(self._trailing_silence(ordered, interval))
        return signals

    def _trailing_silence(self, ordered: pd.DataFrame, interval: pd.Timedelta) -> list[OperationalSignal]:
        if self.analysis_window_end is None:
            return []
        present = ordered[ordered["value"].notna()]
        if present.empty:
            return []
        last_seen = present["timestamp"].iloc[-1]
        silence = self.analysis_window_end - last_seen
        if silence < interval * self.gap_multiple:
            return []
        normal_missing_ratio = float(ordered["value"].isna().mean())
        if normal_missing_ratio > self.max_normal_missing_ratio:
            return []
        missed = int(silence / interval)
        summary = (
            f"{_series_label(ordered)} has not reported since {last_seen.strftime('%Y-%m-%d %H:%M UTC')} - "
            f"{_duration_text(silence)} before the end of the analysis window ({missed} expected point(s) missing)."
        )
        return [
            self._signal(
                ordered,
                signal_type="data_gap",
                severity="high",
                confidence=0.9,
                start=last_seen,
                end=self.analysis_window_end,
                summary=summary,
                evidence={
                    "gap_minutes": round(silence.total_seconds() / 60.0, 2),
                    "missing_points": missed,
                    "interval_seconds": interval.total_seconds(),
                    "normal_missing_ratio": round(normal_missing_ratio, 4),
                    "last_seen": last_seen.isoformat(),
                    "resumed_at": None,
                    "ongoing": True,
                    "analysis_window_end": self.analysis_window_end.isoformat(),
                },
            )
        ]

    def _gaps(self, ordered: pd.DataFrame, interval: pd.Timedelta) -> list[OperationalSignal]:
        missing = ordered["value"].isna().to_numpy()
        signals: list[OperationalSignal] = []
        runs = [(start, end) for start, end in _runs(missing) if missing[start]]
        for start, end in runs:
            gap_duration = ordered["timestamp"].iloc[end - 1] - ordered["timestamp"].iloc[start] + interval
            if gap_duration < interval * self.gap_multiple:
                continue
            outside = np.concatenate([missing[:start], missing[end:]])
            normal_missing_ratio = float(outside.mean()) if len(outside) else 1.0
            if normal_missing_ratio > self.max_normal_missing_ratio:
                continue
            last_seen = ordered["timestamp"].iloc[start - 1] if start > 0 else None
            resumed = ordered["timestamp"].iloc[end] if end < len(ordered) else None
            missed = end - start
            severity = "high" if gap_duration >= interval * self.gap_multiple * 3 else "medium"
            summary = (
                f"{_series_label(ordered)} stopped reporting for {_duration_text(gap_duration)} "
                f"({missed} expected point(s) missing)."
            )
            signals.append(
                self._signal(
                    ordered,
                    signal_type="data_gap",
                    severity=severity,
                    confidence=0.9,
                    start=last_seen if last_seen is not None else ordered["timestamp"].iloc[start],
                    end=resumed if resumed is not None else ordered["timestamp"].iloc[end - 1],
                    summary=summary,
                    evidence={
                        "gap_minutes": round(gap_duration.total_seconds() / 60.0, 2),
                        "missing_points": missed,
                        "interval_seconds": interval.total_seconds(),
                        "normal_missing_ratio": round(normal_missing_ratio, 4),
                        "last_seen": last_seen.isoformat() if last_seen is not None else None,
                        "resumed_at": resumed.isoformat() if resumed is not None else None,
                    },
                )
            )
        return signals

    def _flatlines(self, ordered: pd.DataFrame, interval: pd.Timedelta) -> list[OperationalSignal]:
        present = ordered[ordered["value"].notna()].reset_index(drop=True)
        if len(present) < self.min_flatline_points + 2:
            return []
        values = present["value"].to_numpy(dtype=float)
        if self._constant_by_design(values):
            return []
        unchanged = np.isclose(values[1:], values[:-1], rtol=0.0, atol=1e-12)
        signals: list[OperationalSignal] = []
        for start, end in _runs(np.concatenate([[False], unchanged])):
            # A run of True at [start, end) means points start-1 .. end-1 all share one value.
            if start == 0 or not unchanged[start - 1]:
                continue
            first, last = start - 1, end - 1
            points = last - first + 1
            duration = present["timestamp"].iloc[last] - present["timestamp"].iloc[first]
            if points < self.min_flatline_points or duration < pd.Timedelta(minutes=self.min_flatline_minutes):
                continue
            outside = np.concatenate([unchanged[: max(first - 1, 0)], unchanged[last + 1 :]])
            if len(outside) < self.min_flatline_points:
                continue
            normal_change_ratio = float(1.0 - outside.mean())
            if normal_change_ratio < self.min_normal_change_ratio:
                continue
            value = float(values[first])
            if self._at_floor_or_ceiling(value, np.concatenate([values[:first], values[last + 1 :]]), points):
                continue
            still_flat = last == len(present) - 1
            summary = (
                f"{_series_label(ordered)} was stuck at {value:g} for {_duration_text(duration)} "
                f"({points} identical points)"
                + (" and is still stuck at the end of the window." if still_flat else ".")
                + f" It normally changes on {normal_change_ratio:.0%} of points."
                + (" The source may have stopped sending, or activity really stopped." if value == 0.0 else "")
            )
            signals.append(
                self._signal(
                    ordered,
                    signal_type="flatline",
                    severity="high" if still_flat else "medium",
                    confidence=round(min(1.0, 0.6 + 0.4 * normal_change_ratio), 4),
                    start=present["timestamp"].iloc[first],
                    end=present["timestamp"].iloc[last],
                    summary=summary,
                    evidence={
                        "stuck_value": value,
                        "flatline_minutes": round(duration.total_seconds() / 60.0, 2),
                        "identical_points": points,
                        "normal_change_ratio": round(normal_change_ratio, 4),
                        "still_flat_at_end": still_flat,
                        "interval_seconds": interval.total_seconds(),
                    },
                )
            )
        return signals

    def _constant_by_design(self, values: np.ndarray) -> bool:
        """True for a series that only jitters around one level: its typical point-to-point change
        (the median of the non-zero changes) is under max_constant_spread_ratio of its typical
        magnitude. Measured on the changes rather than the overall spread, so a long stuck stretch
        can't make a series that otherwise moves look constant. A rising counter total is exempt:
        its steps are small next to its magnitude too, but a counter that stops increasing is
        exactly a stall worth reporting."""
        steps = np.abs(np.diff(values))
        moving = steps[steps > 1e-12]
        if len(moving) == 0 or bool(np.all(np.diff(values) >= 0)):
            return False
        return float(np.median(moving)) <= self.max_constant_spread_ratio * float(np.median(np.abs(values)))

    def _at_floor_or_ceiling(self, value: float, outside: np.ndarray, points: int) -> bool:
        """True when a flat value is a level the metric is clamped to: it sits at the edge of where
        the rest of the series goes (within edge_tolerance_ratio of its range from the minimum or
        maximum) AND the metric is at exactly that value at least min_edge_repeats other times.
        The second test is what separates a floor from a stall at the series' latest high: an
        error rate returns to exactly its floor whenever load drops, while a counter or climbing
        gauge never repeats the value it freezes at.

        A floor of exactly zero must also have held before for at least min_zero_floor_run_ratio
        of this run's `points`: a few isolated zeros don't make hours of zeros a floor. Only zero
        gets this check - a nonzero floor (an error rate clamped at its minimum) that holds for a
        long quiet stretch looks the same in the data and is still treated as a floor."""
        if len(outside) == 0:
            return False
        low, high = float(np.min(outside)), float(np.max(outside))
        tolerance = self.edge_tolerance_ratio * (high - low)
        if abs(value - low) > tolerance and abs(value - high) > tolerance:
            return False
        at_value = np.isclose(outside, value, rtol=0.0, atol=1e-12)
        if int(np.sum(at_value)) < self.min_edge_repeats:
            return False
        if value != 0.0:
            return True
        longest = max((end - start for start, end in _runs(at_value) if at_value[start]), default=0)
        return longest >= self.min_zero_floor_run_ratio * points

    def _signal(
        self,
        ordered: pd.DataFrame,
        *,
        signal_type: str,
        severity: str,
        confidence: float,
        start: pd.Timestamp,
        end: pd.Timestamp,
        summary: str,
        evidence: dict[str, object],
    ) -> OperationalSignal:
        first_row = ordered.iloc[0]
        identity = {
            column: first_row.get(column)
            for column in ("host", "namespace", "pod")
            if column in ordered.columns and pd.notna(first_row.get(column))
        }
        return OperationalSignal(
            signal_type=signal_type,
            analyzer_id=self.analyzer_id,
            metric_name=str(first_row["metric_name"]),
            service=first_row.get("service"),
            env=first_row.get("env"),
            severity=severity,
            confidence=confidence,
            start_time=pd.Timestamp(start).to_pydatetime(),
            end_time=pd.Timestamp(end).to_pydatetime(),
            summary=summary,
            evidence={"library": "pandas", "finding_rule_matched": True, **identity, **evidence},
        )


def _runs(flags: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) index ranges of consecutive equal values in a boolean array."""
    if len(flags) == 0:
        return []
    boundaries = np.flatnonzero(np.diff(flags.astype(np.int8))) + 1
    starts = np.concatenate([[0], boundaries])
    ends = np.concatenate([boundaries, [len(flags)]])
    return list(zip(starts.tolist(), ends.tolist()))


def _series_label(ordered: pd.DataFrame) -> str:
    first_row = ordered.iloc[0]
    label = str(first_row["metric_name"])
    host = first_row.get("host") if "host" in ordered.columns else None
    pod = first_row.get("pod") if "pod" in ordered.columns else None
    where = pod if pd.notna(pod) and pod else host if pd.notna(host) and host else None
    return f"{label} on {where}" if where else label


def _duration_text(duration: pd.Timedelta) -> str:
    minutes = duration.total_seconds() / 60.0
    if minutes < 90:
        return f"{minutes:.0f} minutes"
    return f"{minutes / 60.0:.1f} hours"
