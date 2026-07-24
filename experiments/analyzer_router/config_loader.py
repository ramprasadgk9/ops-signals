from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import AnalyzerRoutingRequest, RoutingMode


def load_experiment_config(path: str | Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text()) or {}


def build_request(config: dict[str, Any]) -> AnalyzerRoutingRequest:
    routing_mode = RoutingMode(config.get("routing_mode", RoutingMode.AUTOMATIC_WITH_OVERRIDE.value))
    return AnalyzerRoutingRequest(
        csv_path=str(config["csv_path"]),
        timestamp_column=config.get("timestamp_column"),
        value_column=config.get("value_column"),
        routing_mode=routing_mode,
        selected_analyzers=list(config.get("selected_analyzers", [])),
    )
