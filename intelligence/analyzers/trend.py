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
            x_values = np.arange(len(ordered))
            y_values = ordered["value"].to_numpy(dtype=float)
            if not np.isfinite(y_values).all():
                continue
            model = sm.OLS(y_values, sm.add_constant(x_values)).fit()
            intercept = float(model.params[0])
            slope = float(model.params[1])
            p_value = float(model.pvalues[1])
            r_squared = float(model.rsquared)
            baseline = abs(y_values[0]) if abs(y_values[0]) > 1e-9 else 1.0
            if not np.isfinite(baseline) or baseline <= 0:
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
