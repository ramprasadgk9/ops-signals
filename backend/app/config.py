from __future__ import annotations

import os
from dataclasses import dataclass
from pydantic import BaseModel, Field, field_validator


@dataclass(slots=True)
class Settings:
    app_name: str = "Ops Intelligence API"
    app_version: str = "1.0.0"
    database_url: str = os.getenv(
        "OPS_INTEL_DATABASE_URL",
        "postgresql+psycopg://ops_signals:ops_signals@localhost:5432/ops_signals",
    )


# Memory Configuration Models
class VectorStoreConfig(BaseModel):
    provider: str = "qdrant"
    url: str = "http://localhost:6333"
    api_key: str | None = None
    collection_name: str = "operational_cases"

    @field_validator("collection_name")
    @classmethod
    def collection_name_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("collection_name must not be blank")
        return v


class EmbeddingConfig(BaseModel):
    provider: str = "sentence_transformers"
    model: str = "sentence-transformers/all-MiniLM-L6-v2"
    dimension: int = 384
    normalize_embeddings: bool = True

    @field_validator("dimension")
    @classmethod
    def dimension_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("dimension must be positive")
        return v


class OllamaAIConfig(BaseModel):
    base_url: str = "http://localhost:11434"
    model: str = "qwen2.5:3b"
    timeout_seconds: float = 30.0


class AIConfig(BaseModel):
    enabled: bool = False
    provider: str = "noop"
    temperature: float = 0.0
    max_tokens: int | None = None
    timeout_seconds: float = 30.0
    retry_on_invalid_output: bool = True
    ollama: OllamaAIConfig = Field(default_factory=OllamaAIConfig)


class IndexingConfig(BaseModel):
    automatic_on_case_creation: bool = False
    automatic_on_case_update: bool = False
    include_open_cases: bool = True
    include_resolved_cases: bool = True


class SearchConfig(BaseModel):
    top_k: int = 5
    minimum_score: float = 0.70
    same_metric_only: bool = True
    same_service_only: bool = False
    exclude_current_case: bool = True

    @field_validator("top_k")
    @classmethod
    def top_k_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("top_k must be greater than zero")
        return v

    @field_validator("minimum_score")
    @classmethod
    def minimum_score_valid(cls, v: float) -> float:
        if not 0 <= v <= 1:
            raise ValueError("minimum_score must be between 0 and 1")
        return v


class MemoryConfig(BaseModel):
    enabled: bool = True
    vector_store: VectorStoreConfig = Field(default_factory=VectorStoreConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    indexing: IndexingConfig = Field(default_factory=IndexingConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)


class AppAIConfig(BaseModel):
    ai: AIConfig = Field(default_factory=AIConfig)


class PrometheusConnectionConfig(BaseModel):
    id: str = "default"
    name: str = "Default Prometheus"
    base_url: str | None = None
    bearer_token: str | None = None
    username: str | None = None
    password: str | None = None
    verify_tls: bool = True
    timeout_seconds: float = 30.0
    headers: dict[str, str] = Field(default_factory=dict)
    max_window_days: int = 30
    max_series: int = 20
    max_samples_per_series: int = 10000
    max_total_samples: int = 100000
    min_step_seconds: int = 1
    max_step_seconds: int = 86400

    @field_validator("base_url")
    @classmethod
    def base_url_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            return None
        return value.rstrip("/") if value else None


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_headers(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    headers: dict[str, str] = {}
    for item in value.split(","):
        if ":" not in item:
            continue
        key, header_value = item.split(":", 1)
        key = key.strip()
        header_value = header_value.strip()
        if key and header_value:
            headers[key] = header_value
    return headers


def get_prometheus_config() -> PrometheusConnectionConfig:
    return PrometheusConnectionConfig(
        base_url=os.getenv("OPS_SIGNALS_PROMETHEUS_URL"),
        bearer_token=os.getenv("OPS_SIGNALS_PROMETHEUS_BEARER_TOKEN") or None,
        username=os.getenv("OPS_SIGNALS_PROMETHEUS_USERNAME") or None,
        password=os.getenv("OPS_SIGNALS_PROMETHEUS_PASSWORD") or None,
        verify_tls=_parse_bool(os.getenv("OPS_SIGNALS_PROMETHEUS_VERIFY_TLS"), True),
        timeout_seconds=float(os.getenv("OPS_SIGNALS_PROMETHEUS_TIMEOUT_SECONDS", "30")),
        headers=_parse_headers(os.getenv("OPS_SIGNALS_PROMETHEUS_HEADERS")),
        max_window_days=int(os.getenv("OPS_SIGNALS_PROMETHEUS_MAX_WINDOW_DAYS", "30")),
        max_series=int(os.getenv("OPS_SIGNALS_PROMETHEUS_MAX_SERIES", "20")),
        max_samples_per_series=int(os.getenv("OPS_SIGNALS_PROMETHEUS_MAX_SAMPLES_PER_SERIES", "10000")),
        max_total_samples=int(os.getenv("OPS_SIGNALS_PROMETHEUS_MAX_TOTAL_SAMPLES", "100000")),
        min_step_seconds=int(os.getenv("OPS_SIGNALS_PROMETHEUS_MIN_STEP_SECONDS", "1")),
        max_step_seconds=int(os.getenv("OPS_SIGNALS_PROMETHEUS_MAX_STEP_SECONDS", "86400")),
    )


def get_settings() -> Settings:
    return Settings()
