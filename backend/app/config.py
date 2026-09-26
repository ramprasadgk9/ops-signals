from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from pydantic import BaseModel, Field, field_validator

from intelligence.storage.database_url import database_url_from_env

_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def package_version() -> str:
    """The project version, with pyproject.toml as the single source of truth.

    A source checkout (and the Docker images, which copy pyproject.toml) read it directly, so a stale
    editable install can't report an old version; an installed package falls back to its metadata.
    """
    try:
        return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        pass
    try:
        return version("ops-signals")
    except PackageNotFoundError:
        return "0.0.0+unknown"


@dataclass(slots=True)
class Settings:
    app_name: str = "Ops Signals API"
    app_version: str = field(default_factory=package_version)
    database_url: str = database_url_from_env() or "postgresql+psycopg://ops_signals:ops_signals@localhost:5432/ops_signals"


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
    automatic_on_case_creation: bool = True
    automatic_on_case_update: bool = True
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


class SlackConfig(BaseModel):
    enabled: bool = False
    webhook_url: str | None = None
    minimum_importance: float = 0.7
    timeout_seconds: float = 10.0

    @field_validator("minimum_importance")
    @classmethod
    def minimum_importance_valid(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("minimum_importance must be between 0 and 1")
        return value

    @field_validator("webhook_url")
    @classmethod
    def webhook_url_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            return None
        return value


class AlertEnrichmentConfig(BaseModel):
    """Alertmanager receiver + change-event correlation (docs/design/alert-enrichment-plan.md).

    Durations are seconds. Disabled by default: the receiver returns 200 without doing anything
    until OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED=true.
    """

    enabled: bool = False
    receiver_token: str | None = None
    events_token: str | None = None
    # Slack: enrichment and notification are separate - notify="none" keeps enriching and storing
    # every alert but never posts.
    notify: str = "slack"
    slack_webhook_url: str | None = None
    slack_timeout_seconds: float = 10.0
    notify_severities: list[str] = Field(default_factory=list)
    notify_on_resolve: bool = True
    service_labels: list[str] = Field(default_factory=lambda: ["service", "job", "app", "app_kubernetes_io_name"])
    lookback_seconds: int = 6 * 3600
    min_step_seconds: int = 30
    scrape_interval_seconds: int = 30
    max_points: int = 2000
    min_points: int = 30
    post_change_grace_seconds: int = 600
    min_post_change_points: int = 10
    retry_delays_seconds: list[int] = Field(default_factory=lambda: [180, 360])
    reuse_window_seconds: int = 1800
    dedupe_window_seconds: int = 6 * 3600
    correlation_before_seconds: int = 1800
    correlation_after_seconds: int = 300
    excluded_analyzers: list[str] = Field(default_factory=lambda: ["prophet"])
    ui_base_url: str = "http://localhost:3000"
    max_concurrent_analyses: int = 4

    @field_validator("notify")
    @classmethod
    def notify_valid(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"slack", "none"}:
            raise ValueError("notify must be 'slack' or 'none'")
        return value


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


def get_slack_config() -> SlackConfig:
    return SlackConfig(
        enabled=_parse_bool(os.getenv("OPS_SIGNALS_SLACK_ENABLED"), False),
        webhook_url=os.getenv("OPS_SIGNALS_SLACK_WEBHOOK_URL") or None,
        minimum_importance=float(os.getenv("OPS_SIGNALS_SLACK_MIN_IMPORTANCE", "0.7")),
        timeout_seconds=float(os.getenv("OPS_SIGNALS_SLACK_TIMEOUT_SECONDS", "10")),
    )


def parse_duration_seconds(value: str) -> int:
    """'30s' / '10m' / '6h' / '2d' / '45' (seconds) -> seconds."""
    raw = value.strip().lower()
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if raw and raw[-1] in units:
        return int(float(raw[:-1]) * units[raw[-1]])
    return int(float(raw))


def _env(name: str) -> str | None:
    """Env var, with set-but-empty (`KEY=` in .env) treated as unset so defaults still apply."""
    value = os.getenv(name)
    return value if value is not None and value.strip() else None


def _parse_list(value: str | None) -> list[str] | None:
    """Comma-separated list; None when unset, [] for the literal `none`."""
    if value is None:
        return None
    if value.strip().lower() == "none":
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def get_alert_enrichment_config() -> AlertEnrichmentConfig:
    config = AlertEnrichmentConfig(
        enabled=_parse_bool(_env("OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED"), False),
        receiver_token=_env("OPS_SIGNALS_ALERT_RECEIVER_TOKEN"),
        events_token=_env("OPS_SIGNALS_EVENTS_TOKEN"),
        notify=_env("OPS_SIGNALS_ALERT_NOTIFY") or "slack",
        slack_webhook_url=_env("OPS_SIGNALS_ALERT_SLACK_WEBHOOK_URL") or _env("OPS_SIGNALS_SLACK_WEBHOOK_URL"),
        notify_on_resolve=_parse_bool(_env("OPS_SIGNALS_ALERT_NOTIFY_ON_RESOLVE"), True),
        ui_base_url=(_env("OPS_SIGNALS_UI_BASE_URL") or "http://localhost:3000").rstrip("/"),
    )
    severities = _parse_list(_env("OPS_SIGNALS_ALERT_NOTIFY_SEVERITIES"))
    if severities is not None:
        config.notify_severities = [severity.lower() for severity in severities]
    service_labels = _parse_list(_env("OPS_SIGNALS_ALERT_SERVICE_LABELS"))
    if service_labels:
        config.service_labels = service_labels
    excluded = _parse_list(_env("OPS_SIGNALS_ALERT_EXCLUDED_ANALYZERS"))
    if excluded is not None:
        config.excluded_analyzers = excluded
    if _env("OPS_SIGNALS_ALERT_LOOKBACK"):
        config.lookback_seconds = parse_duration_seconds(os.environ["OPS_SIGNALS_ALERT_LOOKBACK"])
    if _env("OPS_SIGNALS_ALERT_SCRAPE_INTERVAL"):
        config.scrape_interval_seconds = parse_duration_seconds(os.environ["OPS_SIGNALS_ALERT_SCRAPE_INTERVAL"])
    return config


DEFAULT_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
]


class SecurityConfig(BaseModel):
    """API access controls (docs/security-model.md).

    Everything defaults to the safe side except the token: with no OPS_SIGNALS_API_TOKEN the API is
    open, which keeps the local demo frictionless - so it must only be reachable from a trusted network.
    """

    api_token: str | None = None
    enable_testing_api: bool = False
    allow_file_writes: bool = False
    cors_origins: list[str] = Field(default_factory=lambda: list(DEFAULT_CORS_ORIGINS))


def get_security_config() -> SecurityConfig:
    config = SecurityConfig(
        api_token=_env("OPS_SIGNALS_API_TOKEN"),
        enable_testing_api=_parse_bool(_env("OPS_SIGNALS_ENABLE_TESTING_API"), False),
        allow_file_writes=_parse_bool(_env("OPS_SIGNALS_ALLOW_FILE_WRITES"), False),
    )
    origins = _parse_list(_env("OPS_SIGNALS_CORS_ORIGINS"))
    if origins is not None:
        config.cors_origins = origins
    return config


def get_settings() -> Settings:
    return Settings()
