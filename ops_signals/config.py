from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
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
    raw = _load_yaml(path)

    if _should_use_modular_merge(path, raw):
        raw = _build_modular_config(path, raw)

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


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Configuration at {path} must contain a YAML mapping")
    return data


def _should_use_modular_merge(path: Path, raw: dict[str, Any]) -> bool:
    if "analysis" in raw:
        return False
    if "input" not in raw:
        return False
    config_dir = _find_config_dir(path)
    return config_dir is not None and (config_dir / "config.yaml").exists()


def _build_modular_config(path: Path, provider_config: dict[str, Any]) -> dict[str, Any]:
    config_dir = _find_config_dir(path)
    if config_dir is None:
        return provider_config

    base_config = _load_yaml(config_dir / "config.yaml") if (config_dir / "config.yaml").exists() else {}
    analyzer_config = _load_yaml(config_dir / "analyzers.yaml") if (config_dir / "analyzers.yaml").exists() else {}
    return _deep_merge(base_config, analyzer_config, provider_config)


def _find_config_dir(path: Path) -> Path | None:
    candidates: list[Path] = []
    if path.parent.name == "providers" and path.parent.parent.exists():
        candidates.append(path.parent.parent)
    candidates.extend([path.parent / "config", path.parent])

    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            if (candidate / "config.yaml").exists() and (candidate / "analyzers.yaml").exists():
                return candidate
    return None


def _deep_merge(*configs: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for config in configs:
        merged = _merge_two(merged, config)
    return merged


def _merge_two(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(left)
    for key, value in right.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_two(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result
