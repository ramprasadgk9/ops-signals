from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class InputConfig:
    source_type: str
    file_path: str
    history: str
    interval: str
    timestamp_column: str
    value_column: str
    metric_column: str
    required_columns: list[str]
    optional_columns: list[str]
    service: str | None = None
    metric_name: str | None = None
    provider: str = "generic"
    schema_version: str = "v1"
    provider_mappings: dict[str, str] | None = None
    validation: dict[str, Any] | None = None


@dataclass(slots=True)
class AnalyzerConfig:
    enabled: bool
    params: dict[str, Any]


@dataclass(slots=True)
class AnalysisConfig:
    mode: str
    window: str
    analyzers: dict[str, AnalyzerConfig]


@dataclass(slots=True)
class OutputConfig:
    save_normalized_data: bool
    save_signals: bool
    save_embeddings: bool
    save_question_answers: bool = True


@dataclass(slots=True)
class CapabilitiesConfig:
    auto_register: bool = True


@dataclass(slots=True)
class QuestionsConfig:
    auto_generate_from_capabilities: bool = True


@dataclass(slots=True)
class PostgresConfig:
    host: str
    port: int
    database: str
    user: str
    password: str
    table_prefix: str


@dataclass(slots=True)
class StorageConfig:
    postgres: PostgresConfig


@dataclass(slots=True)
class EmbeddingsConfig:
    enabled: bool
    provider: str
    model: str


@dataclass(slots=True)
class UiConfig:
    enabled: bool = True
    default_status: str = "new"
    default_page: str = "overview"
    show_technical_signals: bool = True
    theme: str = "system"


@dataclass(slots=True)
class AppConfig:
    input: InputConfig
    analysis: AnalysisConfig
    output: OutputConfig
    storage: StorageConfig
    embeddings: EmbeddingsConfig
    capabilities: CapabilitiesConfig
    questions: QuestionsConfig
    ui: UiConfig
    config_path: Path


def load_config(config_path: str | Path) -> AppConfig:
    path = Path(config_path).expanduser().resolve()
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    analyzers = {
        name: AnalyzerConfig(enabled=details.get("enabled", False), params={k: v for k, v in details.items() if k != "enabled"})
        for name, details in raw["analysis"]["analyzers"].items()
    }

    return AppConfig(
        input=InputConfig(**raw["input"]),
        analysis=AnalysisConfig(
            mode=raw["analysis"]["mode"],
            window=raw["analysis"]["window"],
            analyzers=analyzers,
        ),
        output=OutputConfig(**raw["output"]),
        storage=StorageConfig(postgres=PostgresConfig(**raw["storage"]["postgres"])),
        embeddings=EmbeddingsConfig(**raw["embeddings"]),
        capabilities=CapabilitiesConfig(**raw.get("capabilities", {})),
        questions=QuestionsConfig(**raw.get("questions", {})),
        ui=UiConfig(**raw.get("ui", {})),
        config_path=path,
    )
