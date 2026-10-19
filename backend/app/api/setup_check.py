"""GET /api/setup/check - the Setup check page: each part of an install, whether it works, and what
to do when it doesn't.

Read-only and best-effort like /api/ingestion/status: a lookup that fails becomes a failed check,
never a failed request. Nothing returned carries a secret: URLs lose any user:password@ part, and
tokens are only ever reported as set or not set.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.api.ai import ai_status
from backend.app.api.ingestion_status import _as_utc, _grafana_reachable, _scalar
from backend.app.api.memory import get_memory_config, get_memory_health, get_vector_store
from backend.app.api.services import database_reachable
from backend.app.config import (
    MemoryConfig,
    PrometheusConnectionConfig,
    PrometheusConnectionsError,
    get_alert_enrichment_config,
    get_metric_usage_config,
    get_prometheus_connections,
    get_security_config,
    get_settings,
    get_slack_config,
    get_ticketing_config,
)
from backend.app.memory.vector_store import VectorStore
from backend.app.models.db import get_db
from backend.app.models.entities import (
    AlertEnrichmentEntity,
    AnalysisRunEntity,
    AutonomousPolicyEntity,
    ChangeEventEntity,
    OtlpPendingPointEntity,
)
from backend.app.otlp.metrics import last_received_at as otlp_last_received_at
from backend.app.services.prometheus_service import ConnectionProbe, PrometheusQueryService, display_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/setup", tags=["setup"])

# Each connection is tested with this timeout, all at once, so a page of unreachable tenants still
# answers in a few seconds.
CONNECTION_CHECK_TIMEOUT_SECONDS = 5.0
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
# A Collector sends every few seconds, so this long without a batch means it stopped.
OTLP_QUIET_AFTER = timedelta(hours=1)

Group = Literal["required", "recommended", "optional"]
Status = Literal["ok", "fail", "warn", "off"]


class SetupCheck(BaseModel):
    id: str
    group: Group
    status: Status
    title: str
    detail: str
    # Only on checks that aren't ok: the request that was tried, why it likely failed, the steps
    # to fix it, and config to copy.
    tried: str | None = None
    cause: str | None = None
    fix: list[str] = Field(default_factory=list)
    snippet: str | None = None
    # A page in docs/, e.g. "docs/security-model.md"; the UI links it.
    docs: str | None = None
    # Something the UI can offer as a button: test_connection, run_analysis, send_test_alert.
    action: str | None = None
    connection_id: str | None = None


class SetupCheckOut(BaseModel):
    generated_at: datetime
    version: str
    checks: list[SetupCheck]


def _ago(value: datetime | None, now: datetime) -> str:
    if value is None:
        return "never"
    seconds = max(0, int((now - value).total_seconds()))
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit} ago"
    return "just now"


def _probe(connection: PrometheusConnectionConfig) -> ConnectionProbe:
    try:
        return PrometheusQueryService(connection.model_copy(update={"timeout_seconds": CONNECTION_CHECK_TIMEOUT_SECONDS})).probe()
    except Exception as exc:  # noqa: BLE001 - a broken connection is a failed check, not a failed page
        logger.warning("setup check: testing connection %s failed", connection.id, exc_info=True)
        return ConnectionProbe(False, None, None, f"The test itself failed: {type(exc).__name__}")


def _connection_snippet(connection: PrometheusConnectionConfig, with_token: bool) -> str:
    env = f"{connection.id.upper().replace('-', '_')}_TOKEN"
    lines = [f"- id: {connection.id}", f"  base_url: {display_url(connection.base_url or 'https://prometheus.example.com')}"]
    if with_token:
        lines.append(f"  bearer_token: ${{{env}}}")
    return "\n".join(lines)


def connection_check(connection: PrometheusConnectionConfig, probe: ConnectionProbe, single: bool) -> SetupCheck:
    """One metrics connection, with a fix that fits how its test failed."""
    title = f"Metrics: {connection.name or connection.id}"
    base = dict(id=f"connection:{connection.id}", group="required", title=title, docs="docs/standalone-prometheus-analysis.md",
                action="test_connection", connection_id=connection.id)
    if probe.available:
        version = f" · version {probe.version}" if probe.version else ""
        return SetupCheck(**base, status="ok", detail=f"Answered in {probe.latency_ms} ms{version}")

    url = display_url(connection.base_url or "")
    tried = f"GET {url}{probe.path or ''}\n-> {f'{probe.status_code} ' if probe.status_code else ''}{probe.message}"
    if probe.latency_ms is not None:
        tried += f"  (after {probe.latency_ms} ms)"
    token_setting = "OPS_SIGNALS_PROMETHEUS_BEARER_TOKEN" if single else f"bearer_token: ${{{connection.id.upper().replace('-', '_')}_TOKEN}} on this connection"
    host = urlsplit(connection.base_url or "").hostname or ""

    if probe.status_code in (401, 403):
        rejected = "Login rejected" if probe.status_code == 401 else "Access denied"
        return SetupCheck(
            **base, status="fail", tried=tried,
            detail=f"{rejected} ({probe.status_code}). The token for this connection is missing or wrong.",
            cause="The connection has no token, the token has expired, or it can't read this tenant.",
            fix=[
                f"Get a read-only token for {connection.id} from whoever runs it.",
                f"Set it with {token_setting}." if single else "Add it to the connection in your connections file, as below.",
                "Restart the backend, then check again.",
            ],
            snippet=None if single else _connection_snippet(connection, with_token=True),
        )
    if probe.status_code == 404:
        return SetupCheck(
            **base, status="fail", tried=tried,
            detail="Reached the server, but it has no Prometheus API at this address (404).",
            cause="The URL is missing a path prefix. Mimir and some gateways serve the API under /prometheus.",
            fix=[
                "Open the URL with /api/v1/query?query=up added in a browser, and adjust it until it answers.",
                "For Mimir, end the URL with /prometheus.",
                "Update the URL, restart the backend, then check again.",
            ],
        )
    if probe.status_code == 504:
        return SetupCheck(
            **base, status="fail", tried=tried,
            detail=f"No answer within {int(CONNECTION_CHECK_TIMEOUT_SECONDS)} seconds.",
            cause="The server is overloaded, or a firewall drops the traffic without refusing it.",
            fix=["Check the server is up, and that the backend's network may reach it.", "Then check again."],
        )
    if probe.status_code == 503:
        local = host in LOCAL_HOSTS
        return SetupCheck(
            **base, status="fail", tried=tried,
            detail=f"Can't reach {host or 'the server'}.",
            cause=(
                f"{host} is the backend's own machine. In a container that is the container itself, not your computer."
                if local else "The host name or port is wrong, the name doesn't resolve, or the server is down."
            ),
            fix=(
                ["Use the Prometheus service name (in Compose or Kubernetes), or host.docker.internal for one on your computer.",
                 "Update the URL, restart the backend, then check again."]
                if local else
                ["Check the URL: host name, port, http or https.", "Check the backend's network can reach that host.", "Then check again."]
            ),
        )
    return SetupCheck(
        **base, status="fail", tried=tried,
        detail=f"The test failed: {probe.message}",
        fix=["Check the URL and the server's logs, then check again."],
    )


def metrics_checks(db: Session, now: datetime) -> list[SetupCheck]:
    try:
        connections = get_prometheus_connections()
    except PrometheusConnectionsError as exc:
        return [SetupCheck(
            id="connections", group="required", status="fail", title="Metrics connections",
            detail="The connections file can't be read.", cause=str(exc),
            fix=["Fix the file named by OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE, then restart the backend."],
            docs="docs/standalone-prometheus-analysis.md",
        )]
    configured = [connection for connection in connections.connections if connection.base_url]
    otlp_last = _as_utc(otlp_last_received_at()) or _as_utc(
        _scalar(db, select(func.max(OtlpPendingPointEntity.received_at)), "otlp pending points")
    ) or _as_utc(_scalar(db, select(func.max(AnalysisRunEntity.created_at)).where(AnalysisRunEntity.source_type == "otel"), "otlp runs"))

    checks: list[SetupCheck] = []
    if configured:
        with ThreadPoolExecutor(max_workers=min(len(configured), 8)) as pool:
            probes = list(pool.map(_probe, configured))
        checks.extend(connection_check(connection, probe, single=len(connections.connections) == 1) for connection, probe in zip(configured, probes))

    otlp_group: Group = "optional" if configured else "required"
    if otlp_last is not None and now - otlp_last <= OTLP_QUIET_AFTER:
        checks.append(SetupCheck(id="otlp", group=otlp_group, status="ok", title="Metrics: OpenTelemetry",
                                 detail=f"Receiving metrics · last batch {_ago(otlp_last, now)}"))
    elif otlp_last is not None:
        checks.append(SetupCheck(
            id="otlp", group=otlp_group, status="warn" if configured else "fail", title="Metrics: OpenTelemetry",
            detail=f"Stopped: the last batch came {_ago(otlp_last, now)}.",
            fix=["If a Collector should be sending, check it is running and its exporter still points at /api/otlp/v1/metrics."],
            docs="docs/integrations.md",
        ))
    elif configured:
        checks.append(SetupCheck(id="otlp", group="optional", status="off", title="Metrics: OpenTelemetry",
                                 detail="Not receiving any. An OpenTelemetry Collector can send metrics to /api/otlp/v1/metrics.",
                                 docs="docs/integrations.md"))
    else:
        checks.append(SetupCheck(
            id="metrics", group="required", status="fail", title="Metrics source",
            detail="No metrics source is set up, so there is nothing to analyze.",
            fix=[
                "Point Ops Signals at Prometheus or Mimir: set OPS_SIGNALS_PROMETHEUS_URL and restart the backend.",
                "Or send metrics from an OpenTelemetry Collector to /api/otlp/v1/metrics.",
                "Then check again.",
            ],
            snippet="OPS_SIGNALS_PROMETHEUS_URL=http://prometheus:9090",
            docs="docs/integrations.md",
        ))
    return checks


def memory_check(store: VectorStore | None, config: MemoryConfig | None) -> SetupCheck:
    try:
        health = get_memory_health(store, config)
    except Exception as exc:  # noqa: BLE001
        logger.warning("setup check: memory health failed", exc_info=True)
        return SetupCheck(id="memory", group="required", status="fail", title="Memory search",
                          detail=f"The check failed: {type(exc).__name__}", docs="docs/operational-memory.md")
    if health.status == "disabled":
        return SetupCheck(id="memory", group="optional", status="off", title="Memory search",
                          detail="Off. Findings work, but past cases aren't matched to new problems.",
                          docs="docs/operational-memory.md")
    if health.status == "healthy":
        return SetupCheck(id="memory", group="required", status="ok", title="Memory search",
                          detail="Connected · past cases can be matched")
    if health.status == "initializing":
        return SetupCheck(id="memory", group="required", status="warn", title="Memory search",
                          detail="Starting up. Check again in a minute.")
    return SetupCheck(
        id="memory", group="required", status="fail", title="Memory search",
        detail=health.detail or "The vector store can't be reached.",
        cause="Qdrant isn't running, or the backend points at the wrong address.",
        fix=["Start Qdrant, or fix the vector store address in config.yaml (memory: block).", "Restart the backend, then check again."],
        docs="docs/operational-memory.md",
    )


def security_checks() -> list[SetupCheck]:
    security = get_security_config()
    checks = [
        SetupCheck(id="login", group="recommended", status="ok", title="Login",
                   detail="An API token is required on every request.")
        if security.api_token else
        SetupCheck(
            id="login", group="recommended", status="warn", title="Login",
            detail="Open: no API token is set, so anyone who can reach the backend can change things.",
            fix=[
                "Create a token and set it on the backend (and the web container):",
                "Restart, then enter the token in the plugin's API token field, or give it to your scripts.",
            ],
            snippet='OPS_SIGNALS_API_TOKEN="$(openssl rand -hex 32)"',
            docs="docs/security-model.md",
        )
    ]
    risky = [name for name, on in (
        ("OPS_SIGNALS_ENABLE_TESTING_API (deletes all data on request)", security.enable_testing_api),
        ("OPS_SIGNALS_ALLOW_FILE_WRITES (writes files on the backend)", security.allow_file_writes),
    ) if on]
    if risky:
        checks.append(SetupCheck(
            id="risky_switches", group="recommended", status="warn", title="Risky switches",
            detail=f"{len(risky)} switch{'es are' if len(risky) > 1 else ' is'} on that should be off outside development.",
            fix=[f"Turn off {name}." for name in risky] + ["Restart the backend."],
            docs="docs/security-model.md",
        ))
    else:
        checks.append(SetupCheck(id="risky_switches", group="recommended", status="ok", title="Risky switches",
                                 detail="Data reset and file writes are off."))
    return checks


def activity_checks(db: Session, now: datetime) -> list[SetupCheck]:
    runs = _scalar(db, select(func.count()).select_from(AnalysisRunEntity).where(AnalysisRunEntity.status != "failed"), "analysis runs")
    latest = _as_utc(_scalar(db, select(func.max(AnalysisRunEntity.created_at)), "latest run"))
    policies = _scalar(db, select(func.count()).select_from(AutonomousPolicyEntity).where(AutonomousPolicyEntity.enabled.is_(True)), "policies")
    checks = [
        SetupCheck(id="first_analysis", group="recommended", status="ok", title="First analysis",
                   detail=f"{runs:,} analysis run{'s' if runs != 1 else ''} · latest {_ago(latest, now)}")
        if runs else
        SetupCheck(id="first_analysis", group="recommended", status="warn", title="First analysis",
                   detail="Nothing analyzed yet. Run one to see your first findings.", action="run_analysis")
    ]
    checks.append(
        SetupCheck(id="schedule", group="optional", status="ok", title="Scheduled analysis",
                   detail=f"{policies} schedule{'s' if policies != 1 else ''} running")
        if policies else
        SetupCheck(id="schedule", group="optional", status="off", title="Scheduled analysis",
                   detail="No schedule yet. Autonomous Analysis can watch your services without you.",
                   docs="docs/autonomous-analysis-preview.md")
    )
    return checks


def integration_checks(db: Session, now: datetime) -> list[SetupCheck]:
    checks: list[SetupCheck] = []
    alerts = get_alert_enrichment_config()
    alerts_last = _as_utc(_scalar(db, select(func.max(AlertEnrichmentEntity.created_at)), "alerts"))
    if not alerts.enabled:
        checks.append(SetupCheck(id="alerts", group="optional", status="off", title="Alerts receiver",
                                 detail="Off. Connect your alert manager to add context to findings.",
                                 snippet="OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED=true", docs="docs/alert-enrichment.md"))
    elif alerts_last is None:
        checks.append(SetupCheck(id="alerts", group="optional", status="warn", title="Alerts receiver",
                                 detail="On, but no alerts received yet. Point an alert manager receiver at /api/integrations/alertmanager.",
                                 docs="docs/alert-enrichment.md", action="send_test_alert"))
    else:
        checks.append(SetupCheck(id="alerts", group="optional", status="ok", title="Alerts receiver",
                                 detail=f"Receiving alerts · last {_ago(alerts_last, now)}", action="send_test_alert"))

    events_last = _as_utc(_scalar(db, select(func.max(ChangeEventEntity.received_at)), "change events"))
    checks.append(
        SetupCheck(id="events", group="optional", status="ok", title="Deploy events", detail=f"Receiving · last {_ago(events_last, now)}")
        if events_last else
        SetupCheck(id="events", group="optional", status="off", title="Deploy events",
                   detail="None received. Send deploys from CI to /api/events so findings show what changed.",
                   docs="docs/alert-enrichment.md")
    )

    slack = get_slack_config()
    if slack.enabled and slack.webhook_url:
        checks.append(SetupCheck(id="notifications", group="optional", status="ok", title="Notifications", detail="Findings are posted to Slack."))
    elif slack.enabled:
        checks.append(SetupCheck(id="notifications", group="optional", status="warn", title="Notifications",
                                 detail="Turned on, but no webhook URL is set, so nothing is sent.",
                                 fix=["Set OPS_SIGNALS_SLACK_WEBHOOK_URL and restart the backend."], docs="docs/configuration.md"))
    else:
        checks.append(SetupCheck(id="notifications", group="optional", status="off", title="Notifications",
                                 detail="Off. Findings can be posted to a chat channel.", docs="docs/configuration.md"))

    ticketing = get_ticketing_config()
    checks.append(
        SetupCheck(id="ticketing", group="optional", status="ok", title="Ticketing", detail=f"On · cases open tickets in {ticketing.active_provider}")
        if ticketing.enabled else
        SetupCheck(id="ticketing", group="optional", status="off", title="Ticketing", detail="Off. Cases can open and follow tickets.",
                   docs="docs/integrations.md")
    )

    grafana = get_metric_usage_config().grafana
    if grafana.base_url:
        reachable = _grafana_reachable(grafana)
        checks.append(
            SetupCheck(id="grafana", group="optional", status="ok", title="Grafana (metric usage)", detail="Reachable · dashboards can be read")
            if reachable else
            SetupCheck(id="grafana", group="optional", status="fail", title="Grafana (metric usage)",
                       detail=f"Can't reach {display_url(grafana.base_url)} or its token was refused.",
                       fix=["Check the Grafana URL and service account token, then restart the backend."], docs="docs/configuration.md")
        )

    try:
        ai = ai_status()
    except Exception:  # noqa: BLE001
        logger.warning("setup check: AI status failed", exc_info=True)
        ai = None
    if ai is None or not ai.enabled:
        checks.append(SetupCheck(id="ai", group="optional", status="off", title="AI assistant",
                                 detail="Off. Ask Ops Signals works on built-in search without it.", docs="docs/ask-ops-signals-assistant.md"))
    elif ai.issue:
        checks.append(SetupCheck(id="ai", group="optional", status="warn", title="AI assistant", detail=ai.issue,
                                 docs="docs/ask-ops-signals-assistant.md"))
    else:
        checks.append(SetupCheck(id="ai", group="optional", status="ok", title="AI assistant",
                                 detail=f"On · {ai.provider}{f' · {ai.model}' if ai.model else ''}"))
    return checks


@router.get("/check", response_model=SetupCheckOut)
def setup_check(
    db: Session = Depends(get_db),
    store: VectorStore | None = Depends(get_vector_store),
    memory_config: MemoryConfig | None = Depends(get_memory_config),
) -> SetupCheckOut:
    now = datetime.now(timezone.utc)
    version = get_settings().app_version
    checks = [SetupCheck(id="backend", group="required", status="ok", title="Backend", detail=f"Answering · version {version}")]

    if database_reachable():
        checks.append(SetupCheck(id="database", group="required", status="ok", title="Database", detail="Connected"))
    else:
        checks.append(SetupCheck(
            id="database", group="required", status="fail", title="Database",
            detail="Postgres can't be reached, so nothing can be stored or shown.",
            fix=["Check Postgres is running and OPS_SIGNALS_DATABASE_URL points at it.", "Restart the backend, then check again."],
            docs="docs/configuration.md",
        ))

    checks.extend(metrics_checks(db, now))
    checks.append(memory_check(store, memory_config))
    checks.extend(security_checks())
    checks.extend(activity_checks(db, now))
    checks.extend(integration_checks(db, now))
    return SetupCheckOut(generated_at=now, version=version, checks=checks)
