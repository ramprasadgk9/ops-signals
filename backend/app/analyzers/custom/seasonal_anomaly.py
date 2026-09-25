from __future__ import annotations

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import STL

from experiments.analyzer_router.feature_extractor import calendar_seasonality
from intelligence.analyzers.base import Analyzer
from intelligence.capability import Capability
from intelligence.signals.schema import OperationalSignal

# Scales MAD so that, on normally distributed data, the robust z-score matches a standard z-score
# (Iglewicz & Hoaglin, 1993).
_MAD_TO_Z = 0.6745


class SeasonalAnomalyAnalyzer(Analyzer):
    """Flags points that are unusual for their time of day or week - e.g. 3am traffic at a daytime
    level - rather than unusual for the window as a whole.

    1. Finds a daily or weekly cycle with calendar_seasonality, the same measure the router's
       profile carries, so the two never disagree. Series without one (below
       min_calendar_strength, or under three cycles of data) are left alone - z-score and PyOD
       are the right tools there. The router's shape-based seasonality is deliberately not used:
       it reads regularly spaced spikes as a cycle, and STL then learns the spikes as "normal".
    2. Splits the series with STL (statsmodels) into trend + repeating pattern + residual.
    3. Scores the residual with a MAD-based robust z-score, so a few large spikes can't inflate the
       spread and hide themselves, and reports contiguous runs above zscore_threshold.
    4. Also requires the deviation to matter in practice: at least min_deviation_ratio of the
       metric's normal swing over a cycle (the 5th-95th percentile range of its expected values),
       and at least min_relative_deviation of the expected value itself. On a clean series the
       residual spread is so tight that sub-1% wiggles clear the z-score alone.

    Empty time buckets (NaN after normalization) are interpolated for the STL fit only; they are
    never reported as anomalies themselves.
    """

    analyzer_id = "seasonal_anomaly"

    def __init__(
        self,
        zscore_threshold: float = 3.5,
        min_calendar_strength: float = 0.5,
        min_deviation_ratio: float = 0.2,
        min_relative_deviation: float = 0.05,
        grouping_gap: str = "15m",
        **config: object,
    ) -> None:
        self.zscore_threshold = float(zscore_threshold)
        self.min_calendar_strength = float(min_calendar_strength)
        self.min_relative_deviation = float(min_relative_deviation)
        self.min_deviation_ratio = float(min_deviation_ratio)
        self.grouping_gap = pd.to_timedelta(grouping_gap)
        self.config = config

    def capability(self) -> Capability:
        return Capability(
            id="seasonal_anomaly",
            title="Seasonal Anomaly",
            description="Detects values that are unusual for their time of day or week.",
            analyzer_id=self.analyzer_id,
            enabled=True,
            supported_question_ids=["unusual_activity", "investigation_priority", "what_changed", "service_health"],
        )

    def analyze(self, dataframe: pd.DataFrame) -> list[OperationalSignal]:
        signals: list[OperationalSignal] = []
        for _, group in dataframe.groupby(["metric_name", "service", "env"], dropna=False):
            ordered = group.sort_values("timestamp").reset_index(drop=True)
            signals.extend(self._analyze_series(ordered))
        return signals

    def _analyze_series(self, ordered: pd.DataFrame) -> list[OperationalSignal]:
        observed = pd.to_numeric(ordered["value"], errors="coerce")
        present = observed.notna().to_numpy()
        if present.sum() < 24:
            return []
        filled = observed.interpolate(limit_direction="both").to_numpy(dtype=float)

        interval = ordered["timestamp"].diff().dropna().median()
        interval_seconds = int(interval.total_seconds()) if pd.notna(interval) else None
        strength, period = calendar_seasonality(filled, interval_seconds)
        if period is None or strength < self.min_calendar_strength:
            return []

        fit = STL(filled, period=int(period), robust=True).fit()
        expected = fit.trend + fit.seasonal
        residual = filled - expected
        median = float(np.median(residual[present]))
        mad = float(np.median(np.abs(residual[present] - median)))
        if mad <= 1e-12:
            return []
        robust_z = _MAD_TO_Z * (residual - median) / mad

        normal_swing = float(np.percentile(expected, 95) - np.percentile(expected, 5))
        min_deviation = self.min_deviation_ratio * normal_swing
        flagged = (
            present
            & (np.abs(robust_z) >= self.zscore_threshold)
            & (np.abs(residual) >= min_deviation)
            & (np.abs(residual) >= self.min_relative_deviation * np.abs(expected))
        )
        if not flagged.any():
            return []

        frame = ordered.assign(expected=expected, robust_z=robust_z)[flagged]
        groups = frame["timestamp"].diff().gt(self.grouping_gap).cumsum()
        return [
            self._signal(window, period=int(period), strength=strength, interval=interval)
            for _, window in frame.groupby(groups)
        ]

    def _signal(self, window: pd.DataFrame, *, period: int, strength: float, interval: pd.Timedelta) -> OperationalSignal:
        peak = window.loc[window["robust_z"].abs().idxmax()]
        max_abs_z = float(abs(peak["robust_z"]))
        actual, expected = float(peak["value"]), float(peak["expected"])
        direction = "above" if actual > expected else "below"
        ratio = actual / expected if expected > 0 and actual > 0 else None
        ratio_text = f" ({ratio:.1f}x the usual level)" if ratio is not None and ratio >= 1.5 else ""
        cycle_text = _cycle_text(period, interval)
        metric_name = str(peak["metric_name"])
        summary = (
            f"{metric_name} was {actual:g} at {peak['timestamp'].strftime('%Y-%m-%d %H:%M UTC')}, {direction} the "
            f"~{expected:.3g} expected for that point in its {cycle_text} cycle{ratio_text}; "
            f"{len(window)} unusual point(s) in this window."
        )
        return OperationalSignal(
            signal_type="anomaly",
            analyzer_id=self.analyzer_id,
            metric_name=metric_name,
            service=peak.get("service"),
            env=peak.get("env"),
            severity="high" if max_abs_z >= self.zscore_threshold * 1.5 else "medium",
            confidence=round(min(1.0, max_abs_z / (self.zscore_threshold * 2.0)), 4),
            start_time=window["timestamp"].min().to_pydatetime(),
            end_time=window["timestamp"].max().to_pydatetime(),
            summary=summary,
            evidence={
                "library": "statsmodels",
                "method": "stl_mad",
                "finding_rule_matched": True,
                # Same key anomaly_zscore uses, so importance scoring weighs it the same way.
                "max_abs_zscore": round(max_abs_z, 4),
                "zscore_threshold": self.zscore_threshold,
                "anomalous_points": int(len(window)),
                "peak_timestamp": peak["timestamp"].isoformat(),
                "actual_value": actual,
                "expected_value": round(expected, 4),
                "direction": direction,
                "period_points": period,
                "calendar_seasonality_strength": round(strength, 4),
            },
        )


def _cycle_text(period: int, interval: pd.Timedelta) -> str:
    if pd.isna(interval) or interval <= pd.Timedelta(0):
        return f"{period}-point"
    cycle = interval * period
    for label, length in (("weekly", pd.Timedelta(days=7)), ("daily", pd.Timedelta(days=1)), ("hourly", pd.Timedelta(hours=1))):
        if abs(cycle - length) <= length * 0.05:
            return label
    hours = cycle.total_seconds() / 3600.0
    return f"{hours:.1f}-hour" if hours >= 1 else f"{cycle.total_seconds() / 60.0:.0f}-minute"
