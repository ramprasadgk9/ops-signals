from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from intelligence.analyzers.base import Analyzer
from intelligence.capability import Capability
from intelligence.signals.schema import OperationalSignal

try:  # pragma: no cover - optional dependency
    from prophet import Prophet as _Prophet
except Exception:  # pragma: no cover - optional dependency
    _Prophet = None


@dataclass(slots=True)
class ProphetConfig:
    horizon_points: int = 10
    changepoint_prior_scale: float = 0.05
    uncertainty_threshold: float = 0.15
    library: str = "prophet"
    finding_min_relative_error: float = 0.25


class ProphetAnalyzer(Analyzer):
    analyzer_id = "prophet"

    def __init__(
        self,
        horizon_points: int = 10,
        changepoint_prior_scale: float = 0.05,
        uncertainty_threshold: float = 0.15,
        finding_rules: dict[str, object] | None = None,
        implementation: dict[str, object] | None = None,
    ) -> None:
        rules = finding_rules or {}
        impl = implementation or {}
        horizon_points = int(impl.get("horizon_points", horizon_points))
        changepoint_prior_scale = float(impl.get("changepoint_prior_scale", changepoint_prior_scale))
        uncertainty_threshold = float(impl.get("uncertainty_threshold", uncertainty_threshold))
        self.config = ProphetConfig(
            horizon_points=max(3, int(horizon_points)),
            changepoint_prior_scale=float(changepoint_prior_scale),
            uncertainty_threshold=float(uncertainty_threshold),
            library=str(impl.get("library", "prophet")),
            finding_min_relative_error=max(0.0, float(rules.get("min_relative_error", 0.25))),
        )

    def capability(self) -> Capability:
        return Capability(
            id="forecasting",
            title="Forecasting",
            description="Forecasts future values and highlights deviations from the expected trajectory.",
            analyzer_id=self.analyzer_id,
            enabled=True,
            supported_question_ids=[
                "long_term_trends",
                "what_changed",
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
            if len(ordered) < 8:
                continue

            forecast = self._forecast(ordered)
            if forecast is None:
                continue

            metric_name = ordered.iloc[0]["metric_name"]
            service = ordered.iloc[0].get("service")
            env = ordered.iloc[0].get("env")
            severity = "high" if forecast["relative_error"] >= self.config.uncertainty_threshold * 2 else "medium"
            confidence = max(0.1, min(1.0, 1.0 - forecast["relative_error"]))
            finding_rule_matched = forecast["relative_error"] >= self.config.finding_min_relative_error
            direction = "above" if forecast["residual"] > 0 else "below"
            signals.append(
                OperationalSignal(
                    signal_type="forecast",
                    analyzer_id=self.analyzer_id,
                    metric_name=metric_name,
                    service=service,
                    env=env,
                    severity=severity,
                    confidence=confidence,
                    start_time=ordered["timestamp"].min().to_pydatetime(),
                    end_time=ordered["timestamp"].max().to_pydatetime(),
                    summary=(
                        f"{metric_name} is projected to move {direction} the expected path by "
                        f"{forecast['relative_error'] * 100:.1f}%."
                    ),
                    evidence={
                        "forecast_value": round(forecast["forecast_value"], 4),
                        "actual_value": round(forecast["actual_value"], 4),
                        "residual": round(forecast["residual"], 4),
                        "relative_error": round(forecast["relative_error"], 4),
                        "horizon_points": self.config.horizon_points,
                        "implementation": {
                            "library": self.config.library if _Prophet is not None else "fallback",
                            "horizon_points": self.config.horizon_points,
                            "changepoint_prior_scale": self.config.changepoint_prior_scale,
                            "uncertainty_threshold": self.config.uncertainty_threshold,
                        },
                        "library": self.config.library if _Prophet is not None else "fallback",
                        "finding_rules": {
                            "min_relative_error": self.config.finding_min_relative_error,
                        },
                        "finding_rule_matched": finding_rule_matched,
                    },
                )
            )
        return signals

    def _forecast(self, ordered: pd.DataFrame) -> dict[str, float] | None:
        values = ordered["value"].to_numpy(dtype=float)
        if not np.isfinite(values).all():
            return None
        actual_value = float(values[-1])
        if not np.isfinite(actual_value):
            return None
        if _Prophet is not None:
            try:  # pragma: no cover - optional dependency
                frame = pd.DataFrame(
                    {
                        "ds": pd.to_datetime(ordered["timestamp"], utc=True, errors="coerce").dt.tz_convert(None),
                        "y": values,
                    }
                )
                frame = frame.dropna(subset=["ds", "y"])
                if len(frame) < 8:
                    return None
                model = _Prophet(changepoint_prior_scale=self.config.changepoint_prior_scale)
                model.fit(frame)
                future = model.make_future_dataframe(periods=self.config.horizon_points, freq="infer")
                forecast = model.predict(future)
                predicted = float(forecast["yhat"].iloc[-1])
                if not np.isfinite(predicted):
                    return None
                residual = actual_value - predicted
                relative_error = abs(residual) / max(abs(predicted), 1e-9)
                return {"forecast_value": predicted, "actual_value": actual_value, "residual": residual, "relative_error": relative_error}
            except Exception:
                return None

        x = np.arange(len(values), dtype=float)
        slope, intercept = np.polyfit(x, values, 1)
        forecast_value = float(intercept + slope * (len(values) - 1 + self.config.horizon_points))
        if not np.isfinite(forecast_value):
            return None
        residual = actual_value - forecast_value
        relative_error = abs(residual) / max(abs(forecast_value), 1e-9)
        return {"forecast_value": forecast_value, "actual_value": actual_value, "residual": residual, "relative_error": relative_error}
