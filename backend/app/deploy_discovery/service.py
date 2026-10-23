"""Find deploys in each Prometheus connection and store them as change events (detect.py says how).

Runs from the scheduler every few minutes. Each run looks back `lookback_hours`, so it also finds
what happened before Ops Signals started, and it skips a deploy already recorded for the service
close in time: by CI, by an earlier run, or by the other detector. A deploy CI reports later
replaces the found one (api/events.py), since CI knows more (author, link).

Stored deploys are a timing hint like CI's: findings say "after deploy X", never "caused by".
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, or_, select, text, true
from sqlalchemy.orm import Session

from backend.app.alerts.correlation import service_names
from backend.app.config import (
    DeployDiscoveryConfig,
    PrometheusConnectionConfig,
    get_alert_enrichment_config,
    get_deploy_discovery_config,
    get_prometheus_connections,
)
from backend.app.deploy_discovery.detect import (
    SOURCE_PREFIX,
    DetectedDeploy,
    build_info_deploys,
    build_info_query,
    replicaset_deploys,
    replicaset_query,
)
from backend.app.models.entities import ChangeEventEntity

logger = logging.getLogger(__name__)

DEPLOY_TYPES = ("deploy", "rollback")
# Any fixed 64-bit number, unique to this lock among the app's advisory locks.
DISCOVERY_LOCK_KEY = 7_140_020_262

# query(connection, promql, **kwargs) -> Prometheus `result` list; PrometheusQueryService.query_result.
Query = Callable[..., list[dict]]


@dataclass
class ConnectionResult:
    connection_id: str
    found: int = 0
    stored: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class DiscoveryStatus:
    """The last run, for the Setup check. Per process: it resets on restart."""

    ran_at: datetime | None = None
    connections: list[ConnectionResult] = field(default_factory=list)
    # Another backend sharing the database held the lock and ran it instead.
    skipped: bool = False


LAST_RUN = DiscoveryStatus()
_last_started: float | None = None


def is_detected(source: str | None) -> bool:
    return bool(source) and source.startswith(SOURCE_PREFIX)


def _prometheus_query(connection: PrometheusConnectionConfig, promql: str, **kwargs) -> list[dict]:
    from backend.app.services.prometheus_service import PrometheusQueryService

    return PrometheusQueryService(connection).query_result(promql, **kwargs)


def _cluster_matches(column, cluster: str | None):
    # An event without a cluster counts for every cluster, as in alerts/correlation.py.
    if not cluster:
        return true()
    return or_(column.is_(None), column == "", func.lower(column) == cluster.lower())


def already_recorded(db: Session, deploy: DetectedDeploy, merge: timedelta, aliases: list[list[str]]) -> bool:
    """True when a deploy of this service is already stored close in time and is the same one: sent
    by CI, found with the same version, or found by the other detector (one rollout seen twice).
    Two versions found the same way minutes apart are two deploys, and both are kept."""
    rows = db.execute(
        select(ChangeEventEntity.source, ChangeEventEntity.version).where(
            ChangeEventEntity.service.in_(service_names(deploy.service, aliases)),
            ChangeEventEntity.event_type.in_(DEPLOY_TYPES),
            ChangeEventEntity.timestamp >= deploy.timestamp - merge,
            ChangeEventEntity.timestamp <= deploy.timestamp + merge,
            _cluster_matches(ChangeEventEntity.cluster, deploy.cluster),
        )
    ).all()
    return any(not is_detected(source) or version == deploy.version or source != deploy.source for source, version in rows)


def store(db: Session, deploys: list[DetectedDeploy], config: DeployDiscoveryConfig, aliases: list[list[str]], now: datetime) -> int:
    merge = timedelta(minutes=config.merge_minutes)
    stored = 0
    for deploy in deploys:
        if already_recorded(db, deploy, merge, aliases):
            continue
        db.add(ChangeEventEntity(
            service=deploy.service,
            event_type="deploy",
            timestamp=deploy.timestamp,
            version=deploy.version,
            cluster=deploy.cluster,
            source=deploy.source,
            description=deploy.description,
            attributes_json=deploy.attributes or None,
            received_at=now,
        ))
        # Seen by the next deploy's check, so the two detectors don't both store one rollout.
        db.flush()
        stored += 1
    return stored


def discover(
    db: Session,
    connection: PrometheusConnectionConfig,
    config: DeployDiscoveryConfig,
    now: datetime,
    query: Query = _prometheus_query,
) -> ConnectionResult:
    """One connection: query, detect, store. A detector that fails (no such metric, a timeout) is
    reported and the other one still runs."""
    alerts = get_alert_enrichment_config()
    start = now - timedelta(hours=config.lookback_hours)
    result = ConnectionResult(connection.id)
    deploys: list[DetectedDeploy] = []
    try:
        series = query(
            connection,
            build_info_query(alerts.service_labels, config.version_labels, connection.cluster_label),
            start=start, end=now, step_seconds=config.step_seconds, max_series=config.max_series,
        )
        deploys += build_info_deploys(series, service_labels=alerts.service_labels, version_labels=config.version_labels,
                                      cluster_label=connection.cluster_label)
    except HTTPException as exc:
        result.errors.append(f"build_info: {exc.detail}")
    if config.kube_replicasets:
        try:
            rows = query(connection, replicaset_query(connection.cluster_label), at=now, max_series=config.max_series)
            deploys += replicaset_deploys(rows, cluster_label=connection.cluster_label, since=start, until=now)
        except HTTPException as exc:
            result.errors.append(f"kube_replicaset: {exc.detail}")
    result.found = len(deploys)
    # build_info first: when both see one rollout, the stored event carries the app's own version.
    result.stored = store(db, deploys, config, alerts.service_aliases, now)
    return result


def _lock(db: Session) -> bool:
    """Only one backend at a time (the web UI and plugin backends can share a database). SQLite
    serializes writers on its own."""
    if db.get_bind().dialect.name != "postgresql":
        return True
    return bool(db.execute(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": DISCOVERY_LOCK_KEY}).scalar())


def run_once(db: Session, config: DeployDiscoveryConfig, now: datetime | None = None, query: Query = _prometheus_query) -> DiscoveryStatus:
    now = now or datetime.now(timezone.utc)
    status = DiscoveryStatus(ran_at=now)
    if not _lock(db):
        logger.info("Deploy discovery skipped: another backend is running it")
        status.skipped = True
        return status
    for connection in get_prometheus_connections().connections:
        if not connection.base_url:
            continue
        try:
            status.connections.append(discover(db, connection, config, now, query))
        except Exception:
            logger.exception("Deploy discovery failed for connection %s", connection.id)
            status.connections.append(ConnectionResult(connection.id, errors=["unexpected error, see the backend log"]))
    db.commit()
    for item in status.connections:
        if item.stored:
            logger.info("Deploy discovery stored %s deploy(s) from connection %s", item.stored, item.connection_id)
    return status


def run_if_due() -> None:
    """Called on every scheduler tick; runs every `interval_minutes`."""
    global _last_started
    config = get_deploy_discovery_config()
    if not config.enabled:
        return
    clock = time.monotonic()
    if _last_started is not None and clock - _last_started < config.interval_minutes * 60:
        return
    _last_started = clock

    from backend.app.models.db import get_session_local

    with get_session_local()() as db:
        status = run_once(db, config)
    if not status.skipped:
        LAST_RUN.ran_at, LAST_RUN.connections = status.ran_at, status.connections
