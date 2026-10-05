from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from backend.app.ai.config import AIConfig, OllamaConfig as OllamaAIConfig  # noqa: F401  re-exported

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
    # One Mimir/Thanos endpoint can hold several clusters' data, told apart only by an external
    # label. Series that differ by this label are analysed separately. None turns it off.
    cluster_label: str | None = "cluster"
    # HA pairs send the same series twice, differing only by one of these labels; one copy is kept.
    replica_labels: list[str] = Field(default_factory=lambda: ["__replica__", "prometheus_replica"])
    # Alerts carrying all of these labels are analysed on this connection (e.g. {"tenant": "team-b"}).
    match_labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("cluster_label")
    @classmethod
    def cluster_label_not_blank(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None

    @field_validator("base_url")
    @classmethod
    def base_url_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            return None
        return value.rstrip("/") if value else None


class PrometheusConnectionsError(ValueError):
    """The connections file can't be used. Raised at startup so a typo never reaches a query."""


class PrometheusConnections(BaseModel):
    """Every Prometheus-compatible endpoint Ops Signals may query - typically one per Mimir tenant."""

    connections: list[PrometheusConnectionConfig]
    default_id: str

    def model_post_init(self, __context: object) -> None:
        if not self.connections:
            raise PrometheusConnectionsError("the connections file must list at least one connection")
        seen: set[str] = set()
        for connection in self.connections:
            if connection.id in seen:
                raise PrometheusConnectionsError(f"duplicate connection id {connection.id!r}")
            seen.add(connection.id)
        if self.default_id not in seen:
            raise PrometheusConnectionsError(f"default connection {self.default_id!r} is not in the connections list")

    @property
    def default(self) -> PrometheusConnectionConfig:
        return self._by_id(self.default_id)  # type: ignore[return-value]

    def get(self, connection_id: str | None) -> PrometheusConnectionConfig | None:
        """None, and the literal id `default` when no connection is called that, mean the default
        connection - so clients written for the single-connection API keep working."""
        if connection_id is None:
            return self.default
        found = self._by_id(connection_id)
        if found is None and connection_id == "default":
            return self.default
        return found

    def route(self, labels: dict[str, str]) -> PrometheusConnectionConfig:
        """The first connection whose match_labels the alert carries; otherwise the default."""
        for connection in self.connections:
            if connection.match_labels and all(labels.get(key) == value for key, value in connection.match_labels.items()):
                return connection
        return self.default

    def _by_id(self, connection_id: str) -> PrometheusConnectionConfig | None:
        return next((connection for connection in self.connections if connection.id == connection_id), None)


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
    # How far before the alert a step change / a spike can start and still count as its start time
    # (backend/app/alerts/timing.py). None = anywhere in the analysed window.
    step_lookback_seconds: int | None = None
    spike_lookback_seconds: int = 3600
    # Skip change events from a different environment than the alert, when both name one.
    match_env: bool = True
    # Names that mean the same service, e.g. [["cart", "cart-service"]] when CI sends "cart" and
    # the metrics say "cart-service". Used wherever change events are matched to a service.
    service_aliases: list[list[str]] = Field(default_factory=list)
    # A new pod that first reported up to this long after a deploy counts as started by it.
    deploy_rollout_seconds: int = 900
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


class DrillDownConfig(BaseModel):
    """Finding drill-down (intelligence/drilldown.py): after an autonomous Prometheus run creates a
    finding, re-query the same metric grouped by pod (or the next label in `labels`) and record which
    parts the change came from in the finding's comparison_json["breakdown"].

    Disabled by default: until OPS_SIGNALS_DRILLDOWN_ENABLED=true, runs and findings are exactly as
    before. Each drill-down is one or two extra range queries, capped per job by max_findings_per_job
    and by the connection's max_series / max_total_samples limits.
    """

    enabled: bool = False
    labels: list[str] = Field(default_factory=lambda: ["pod", "instance"])
    max_findings_per_job: int = 3

    @field_validator("max_findings_per_job")
    @classmethod
    def max_findings_valid(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_findings_per_job must be at least 1")
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
        cluster_label=_cluster_label_from_env(),
        **_replica_labels_from_env(),
    )


def get_prometheus_connections() -> PrometheusConnections:
    """The connections file named by OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE, or - without one - the
    single `default` connection the OPS_SIGNALS_PROMETHEUS_* variables describe."""
    path = _env("OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE")
    if path is None:
        return PrometheusConnections(connections=[get_prometheus_config()], default_id="default")
    try:
        stat = os.stat(path)
    except OSError as exc:
        raise PrometheusConnectionsError(f"cannot read Prometheus connections file {path}: {exc}") from exc
    return _load_connections_file(path, stat.st_mtime_ns, _secret_env_snapshot())


_SECRET_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
# Only these fields may hold ${ENV} references, so secrets stay out of the file but nothing else
# (a URL, a label) changes meaning because of the environment.
_SECRET_FIELDS = ("bearer_token", "username", "password")


def _secret_env_snapshot() -> tuple[tuple[str, str], ...]:
    # Part of the cache key, so a rotated secret is picked up without a restart.
    return tuple(sorted((key, value) for key, value in os.environ.items()))


@lru_cache(maxsize=4)
def _load_connections_file(path: str, _mtime_ns: int, _env_snapshot: tuple[tuple[str, str], ...]) -> PrometheusConnections:
    try:
        text = Path(path).read_text(encoding="utf-8")
        raw = json.loads(text) if path.endswith(".json") else yaml.safe_load(text)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise PrometheusConnectionsError(f"cannot parse Prometheus connections file {path}: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("connections"), list):
        raise PrometheusConnectionsError(f"{path} must have a `connections:` list")
    items = []
    for item in raw["connections"]:
        if not isinstance(item, dict) or not item.get("id"):
            raise PrometheusConnectionsError(f"{path}: every connection needs an `id`")
        item = dict(item)
        for key in _SECRET_FIELDS:
            if isinstance(item.get(key), str):
                item[key] = _expand_secret(item[key], item["id"], key)
        if isinstance(item.get("headers"), dict):
            item["headers"] = {
                str(name): _expand_secret(str(value), item["id"], f"headers.{name}") for name, value in item["headers"].items()
            }
        try:
            items.append(PrometheusConnectionConfig(**item))
        except ValueError as exc:
            raise PrometheusConnectionsError(f"{path}: connection {item['id']!r} is invalid: {exc}") from exc
    default_id = raw.get("default") or (items[0].id if items else "")
    try:
        return PrometheusConnections(connections=items, default_id=str(default_id))
    except ValidationError as exc:
        raise PrometheusConnectionsError(f"{path}: {exc.errors()[0]['msg'].removeprefix('Value error, ')}") from exc


def _expand_secret(value: str, connection_id: str, field_name: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in os.environ:
            raise PrometheusConnectionsError(
                f"connection {connection_id!r} {field_name} refers to ${{{name}}}, which is not set"
            )
        return os.environ[name]

    return _SECRET_REF.sub(replace, value)


def _cluster_label_from_env() -> str | None:
    value = _env("OPS_SIGNALS_PROMETHEUS_CLUSTER_LABEL")
    if value is None:
        return "cluster"
    return None if value.strip().lower() == "none" else value


def _replica_labels_from_env() -> dict[str, list[str]]:
    labels = _parse_list(_env("OPS_SIGNALS_PROMETHEUS_REPLICA_LABELS"))
    return {} if labels is None else {"replica_labels": labels}


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
    if _env("OPS_SIGNALS_ALERT_MIN_STEP"):
        config.min_step_seconds = max(1, parse_duration_seconds(os.environ["OPS_SIGNALS_ALERT_MIN_STEP"]))
    step_lookback = _env("OPS_SIGNALS_ALERT_STEP_LOOKBACK")
    if step_lookback:
        config.step_lookback_seconds = None if step_lookback.strip().lower() == "window" else parse_duration_seconds(step_lookback)
    if _env("OPS_SIGNALS_ALERT_SPIKE_LOOKBACK"):
        config.spike_lookback_seconds = parse_duration_seconds(os.environ["OPS_SIGNALS_ALERT_SPIKE_LOOKBACK"])
    if _env("OPS_SIGNALS_ALERT_CHANGE_WINDOW_BEFORE"):
        config.correlation_before_seconds = parse_duration_seconds(os.environ["OPS_SIGNALS_ALERT_CHANGE_WINDOW_BEFORE"])
    if _env("OPS_SIGNALS_ALERT_CHANGE_WINDOW_AFTER"):
        config.correlation_after_seconds = parse_duration_seconds(os.environ["OPS_SIGNALS_ALERT_CHANGE_WINDOW_AFTER"])
    config.match_env = _parse_bool(_env("OPS_SIGNALS_ALERT_MATCH_ENV"), True)
    config.service_aliases = parse_service_aliases(_env("OPS_SIGNALS_SERVICE_ALIASES"))
    if _env("OPS_SIGNALS_DEPLOY_ROLLOUT_WINDOW"):
        config.deploy_rollout_seconds = parse_duration_seconds(os.environ["OPS_SIGNALS_DEPLOY_ROLLOUT_WINDOW"])
    return config


def parse_service_aliases(value: str | None) -> list[list[str]]:
    """'cart,cart-service;checkout,checkout-api' -> groups of names for the same service.
    A group with fewer than two names says nothing and is dropped."""
    if not value:
        return []
    groups = [[name.strip() for name in group.split(",") if name.strip()] for group in value.split(";")]
    return [group for group in groups if len(group) >= 2]


def get_drilldown_config() -> DrillDownConfig:
    config = DrillDownConfig(enabled=_parse_bool(_env("OPS_SIGNALS_DRILLDOWN_ENABLED"), False))
    labels = _parse_list(_env("OPS_SIGNALS_DRILLDOWN_LABELS"))
    if labels:
        config.labels = labels
    if _env("OPS_SIGNALS_DRILLDOWN_MAX_FINDINGS"):
        config.max_findings_per_job = max(1, int(os.environ["OPS_SIGNALS_DRILLDOWN_MAX_FINDINGS"]))
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
