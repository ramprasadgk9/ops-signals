from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from experiments.analyzer_router.router import UniversalTimeSeriesRouter
from intelligence.config import AppConfig, InputConfig, load_config
from intelligence.normalize.normalizer import normalize_timeseries


@dataclass(slots=True)
class TimeSeriesRoutingResult:
    normalized: pd.DataFrame
    profile: dict[str, object]
    analyzer_routing: list[dict[str, object]]
    registry_version: str | None


class TimeSeriesRoutingService:
    """Shared production path for dataframe normalization and analyzer routing."""

    def __init__(self, router: UniversalTimeSeriesRouter | None = None) -> None:
        self.router = router or UniversalTimeSeriesRouter()

    def route_dataframe(
        self,
        dataframe: pd.DataFrame,
        input_config: InputConfig,
    ) -> TimeSeriesRoutingResult:
        normalized = normalize_timeseries(dataframe, input_config)
        return self.route_normalized(normalized)

    def route_normalized(self, normalized: pd.DataFrame) -> TimeSeriesRoutingResult:
        if normalized.empty:
            return TimeSeriesRoutingResult(normalized=normalized, profile={}, analyzer_routing=[], registry_version=None)

        validation, profile, _ = self.router.profile_dataframe(normalized, "timestamp", "value")
        if not validation.valid:
            reasons = "; ".join(validation.reasons) or validation.status
            raise ValueError(f"Router rejected input: {reasons}")

        profile.notes.extend(self.router._profile_notes(profile))
        decisions = self.router.recommend_analyzers_for_profile(profile)
        return TimeSeriesRoutingResult(
            normalized=normalized,
            profile=asdict(profile),
            analyzer_routing=[self._serialize_decision(decision) for decision in decisions],
            registry_version=self.router.registry.registry_version,
        )

    @staticmethod
    def _serialize_decision(decision) -> dict[str, object]:
        return {
            "analyzer_id": decision.analyzer,
            "display_name": decision.display_name,
            "eligible": decision.eligible,
            "eligibility_score": decision.eligibility_score,
            "suitability_score": decision.suitability_score,
            "recommendation": decision.recommendation,
            "final_score": decision.final_score,
            "reasons": decision.reasons,
            "warnings": decision.warnings,
            "explanation": decision.explanation,
            "routing_reason": decision.routing_reason,
            "parameters_tested": decision.parameters_tested,
        }


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def provider_defaults(provider: str) -> tuple[dict[str, str], list[str]]:
    provider_lower = provider.lower()
    if provider_lower == "prometheus":
        return ({"metric_name": "metric", "host": "instance"}, ["timestamp", "metric", "value"])
    if provider_lower == "datadog":
        return ({"timestamp": "ts_epoch_ms"}, ["ts_epoch_ms", "metric_name", "value"])
    return ({}, ["timestamp", "metric_name", "value"])


def load_routing_app_config(provider: str = "prometheus") -> AppConfig:
    root = repo_root()
    provider_file = root / "config" / "providers" / f"{provider}.yaml"
    if provider_file.exists():
        return load_config(provider_file)
    return load_config(root / "config" / "config.yaml")


def build_csv_routing_config(
    *,
    provider: str,
    file_path: str | None = None,
    service: str = "uploaded-service",
    metric_name: str = "uploaded_metric",
    interval: str = "5m",
    analyzer_id: str = "all",
    preview: bool = True,
    analyzer_overrides: dict[str, dict[str, object]] | None = None,
) -> AppConfig:
    provider_lower = provider.lower()
    mapping_defaults, required_defaults = provider_defaults(provider_lower)
    config = copy.deepcopy(load_routing_app_config(provider_lower))
    config.input.source_type = "csv"
    config.input.provider = provider_lower
    config.input.file_path = file_path or ""
    config.input.interval = interval
    config.input.service = service
    config.input.metric_name = metric_name
    config.input.provider_mappings = mapping_defaults
    config.input.required_columns = required_defaults
    config.input.timestamp_column = "timestamp"
    config.input.value_column = "value"
    config.input.metric_column = "metric_name"
    config.output.save_normalized_data = True
    config.output.save_signals = True
    config.output.save_question_answers = not preview
    config.output.save_embeddings = False
    config.embeddings.enabled = False

    for override_analyzer_id, override_params in (analyzer_overrides or {}).items():
        analyzer_config = config.analysis.analyzers.get(override_analyzer_id)
        if analyzer_config is None:
            raise ValueError(f"analyzer '{override_analyzer_id}' is not configured")
        analyzer_config.params.update(override_params)

    requested_analyzer_id = analyzer_id.strip()
    if requested_analyzer_id.lower() not in {"all", "router"}:
        if requested_analyzer_id not in config.analysis.analyzers:
            raise ValueError(f"analyzer '{requested_analyzer_id}' is not configured")
        config.analysis.selection_mode = "manual_override"
        config.analysis.selected_analyzers = [requested_analyzer_id]
    return config
