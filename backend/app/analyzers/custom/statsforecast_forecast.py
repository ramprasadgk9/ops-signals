from __future__ import annotations

import pandas as pd

from intelligence.analyzers.base import Analyzer
from intelligence.capability import Capability
from intelligence.signals.schema import OperationalSignal


class StatsforecastForecastAnalyzer(Analyzer):
    """Adapter stub for Statsforecast Forecast.

    Input:
        dataframe: normalized time-series rows with timestamp, value, metric_name,
        service, and env columns.

    Output:
        A list of OperationalSignal objects. Return an empty list when the
        analyzer does not find meaningful behavior.
    """

    analyzer_id = "statsforecast_forecast"

    def __init__(self, **config: object) -> None:
        self.config = config

    def capability(self) -> Capability:
        return Capability(
            id="statsforecast_forecast",
            title="Statsforecast Forecast",
            description="Custom analyzer adapter. Implement analyze() before enabling execution.",
            analyzer_id=self.analyzer_id,
            enabled=True,
            supported_question_ids=["what_changed", "service_health", "investigation_priority"],
        )

    def analyze(self, dataframe: pd.DataFrame) -> list[OperationalSignal]:
        # TODO: Call statsforecast or your API/model here.
        # Expected dataframe columns:
        #   timestamp, value, metric_name, service, env
        #
        # Return OperationalSignal objects, for example:
        #   OperationalSignal(
        #       signal_type="forecast",
        #       analyzer_id=self.analyzer_id,
        #       metric_name=str(dataframe.iloc[0]["metric_name"]),
        #       service=dataframe.iloc[0].get("service"),
        #       env=dataframe.iloc[0].get("env"),
        #       severity="medium",
        #       confidence=0.8,
        #       start_time=dataframe["timestamp"].min().to_pydatetime(),
        #       end_time=dataframe["timestamp"].max().to_pydatetime(),
        #       summary="Describe what the analyzer found.",
        #       evidence={"library": "statsforecast"},
        #   )
        return []
