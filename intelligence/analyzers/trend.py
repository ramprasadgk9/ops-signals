from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm

from intelligence.analyzers.base import Analyzer
from intelligence.capability import Capability
from intelligence.signals.schema import OperationalSignal


class TrendAnalyzer(Analyzer):
    analyzer_id = "trend"

    def __init__(
        self,
        min_slope_percent: float | None = None,
        finding_rules: dict[str, object] | None = None,
        implementation: dict[str, object] | None = None,
    ) -> None:
        rules = finding_rules or {}
        impl = implementation or {}
        default_min_slope_percent = 10.0 if min_slope_percent is None else float(min_slope_percent)
        self.finding_min_slope_percent = max(
            0.0,
            float(rules.get("min_slope_percent", default_min_slope_percent)),
        )
        self.min_slope_percent = self.finding_min_slope_percent
        self.library = str(impl.get("library", "statsmodels"))
        self.model = str(impl.get("model", "OLS"))

    def capability(self) -> Capability:
        return Capability(
            id="trend_analysis",
            title="Trend Analysis",
            description="Detects long-term metric direction and velocity changes.",
            analyzer_id=self.analyzer_id,
            enabled=True,
            supported_question_ids=[
                "what_changed",
                "long_term_trends",
                "service_health",
                "investigation_priority",
            ],
        )

    def analyze(self, dataframe: pd.DataFrame) -> list[OperationalSignal]:
        signals: list[OperationalSignal] = []
        for _, group in dataframe.groupby(["metric_name", "service", "env"], dropna=False):
            ordered = group.sort_values("timestamp").reset_index(drop=True)
            ordered = ordered.copy()
            ordered["value"] = pd.to_numeric(ordered["value"], errors="coerce")
            ordered = ordered.dropna(subset=["value"])
            if len(ordered) < 3:
                continue
            y_values = ordered["value"].to_numpy(dtype=float)
            if not np.isfinite(y_values).all():
                continue
            slope, intercept, p_value, r_squared, fit = _fit_trend(ordered["timestamp"], y_values)
            # Relative to the window's average level, not its first point: a window that happens
            # to start at a daily low would otherwise inflate every percentage.
            baseline = abs(float(np.mean(y_values)))
            if not np.isfinite(baseline) or baseline <= 1e-9:
                baseline = 1.0
            slope_percent = (slope * (len(ordered) - 1) / baseline) * 100.0
            if not all(np.isfinite(value) for value in [slope, intercept, p_value, r_squared, slope_percent]):
                continue
            finding_rule_matched = bool(abs(slope_percent) >= self.finding_min_slope_percent)
            if not finding_rule_matched:
                continue
            severity = "high" if abs(slope_percent) >= self.finding_min_slope_percent * 2 else "medium"
            effect_confidence = min(1.0, abs(slope_percent) / max(self.finding_min_slope_percent * 2.0, 1e-9))
            statistical_confidence = max(0.0, min(1.0, 1.0 - p_value))
            fit_confidence = max(0.0, min(1.0, r_squared))
            confidence = max(0.0, min(1.0, effect_confidence * 0.6 + statistical_confidence * 0.25 + fit_confidence * 0.15))
            direction = "upward" if slope > 0 else "downward"
            metric_name = ordered.iloc[0]["metric_name"]
            service = ordered.iloc[0].get("service")
            env = ordered.iloc[0].get("env")
            summary = (
                f"{metric_name} shows a sustained {direction} trend of {slope_percent:.1f}% across the batch window."
            )
            signals.append(
                OperationalSignal(
                    signal_type="trend",
                    analyzer_id=self.analyzer_id,
                    metric_name=metric_name,
                    service=service,
                    env=env,
                    severity=severity,
                    confidence=confidence,
                    start_time=ordered["timestamp"].min().to_pydatetime(),
                    end_time=ordered["timestamp"].max().to_pydatetime(),
                    summary=summary,
                    evidence={
                        "slope": round(float(slope), 6),
                        "intercept": round(float(intercept), 6),
                        "slope_percent": round(float(slope_percent), 4),
                        "threshold_percent": self.min_slope_percent,
                        "finding_rules": {
                            "min_slope_percent": self.finding_min_slope_percent,
                        },
                        "finding_rule_matched": finding_rule_matched,
                        "fit": fit,
                        "p_value": round(float(p_value), 6),
                        "r_squared": round(float(r_squared), 6),
                        "implementation": {
                            "library": self.library,
                            "model": self.model,
                        },
                        "library": self.library,
                        "model": self.model,
                    },
                )
            )
        return signals


# A window this many full days long is fitted through its daily means, so a daily cycle cancels out.
MIN_DAYS_FOR_DAILY_FIT = 3


def _fit_trend(timestamps: pd.Series, values: np.ndarray) -> tuple[float, float, float, float, str]:
    """(slope per point, intercept, p-value, r-squared, fit) of the series' overall direction.

    A straight line through every point of a metric with a daily cycle (request rates, taxi rides,
    CPU on a user-facing service) takes its slope from wherever the cycle happens to sit at the two
    ends of the window: a week of a perfectly repeating daily pattern reads as +14% or -34%
    depending only on the hour the window starts. So a window of at least MIN_DAYS_FOR_DAILY_FIT
    full days is fitted through its daily means instead - each whole day averages its cycle out -
    and the per-day slope is converted back to per point. Days with under 90% of the fullest day's
    points (the partial day at the end of a window) are left out. Shorter windows, and those
    without enough full days, keep the straight line through every point.
    """
    stamps = pd.to_datetime(timestamps, utc=True).reset_index(drop=True)
    span_days = (stamps.iloc[-1] - stamps.iloc[0]).total_seconds() / 86400.0
    if span_days >= MIN_DAYS_FOR_DAILY_FIT:
        elapsed_days = (stamps - stamps.iloc[0]).dt.total_seconds().to_numpy() / 86400.0
        days = pd.DataFrame({"day": np.floor(elapsed_days), "t": elapsed_days, "value": values})
        daily = days.groupby("day").agg(t=("t", "mean"), value=("value", "mean"), points=("value", "size"))
        daily = daily[daily["points"] >= 0.9 * daily["points"].max()]
        if len(daily) >= MIN_DAYS_FOR_DAILY_FIT:
            model = sm.OLS(daily["value"].to_numpy(), sm.add_constant(daily["t"].to_numpy())).fit()
            points_per_day = (len(values) - 1) / span_days
            return (
                float(model.params[1]) / points_per_day,
                float(model.params[0]),
                float(model.pvalues[1]),
                float(model.rsquared),
                "daily_means",
            )
    model = sm.OLS(values, sm.add_constant(np.arange(len(values)))).fit()
    return float(model.params[1]), float(model.params[0]), float(model.pvalues[1]), float(model.rsquared), "points"
