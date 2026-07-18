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


def get_settings() -> Settings:
    return Settings()
