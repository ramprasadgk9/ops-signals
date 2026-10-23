"""Deploys and other change events near a finding's change, looked up when the finding is read.

Looked up at read time, not stored by the run: a CI webhook can arrive after the run that found the
change, and findings stored before this existed get the same answer.

Never raises. Every way the data can be missing becomes a `status` (and `reason`) that the UI turns
into a plain sentence, and the finding itself is always returned:

  matched                 change events in the window; `matches` nearest first, plus `pods`
  none_in_window          the service has change events, none near this change
  no_events_for_service   no change event has ever been recorded for this service (or its aliases)
  unavailable             reason: no_service | no_change_time | error

`pods` (only when matched) says whether the breakdown's new pods started with the nearest deploy:
  linked                  `parts` first reported within the rollout window after the deploy
  not_linked              reason: no_breakdown | no_new_parts | no_start_times | no_deploy |
                          started_outside_rollout
A link is a timing match on pod start times, never a claim that the deploy caused the change.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.alerts.correlation import as_utc, changes_to_dict, correlate_changes, service_names
from backend.app.config import AlertEnrichmentConfig, get_deploy_discovery_config
from backend.app.models.entities import AutonomousMetricJobEntity, ChangeEventEntity, FindingEntity, SignalEntity

logger = logging.getLogger(__name__)

# Change events that start new pods. A config change or a flag flip doesn't.
_POD_STARTING_TYPES = {"deploy", "rollback"}
_LOCALIZED_SIGNAL_TYPES = {"anomaly", "spike", "outlier"}
# Pods can report a little before the deploy's own timestamp (CI posts the event after kubectl
# returns, clocks differ), so the window opens slightly early.
_EARLY_START_SECONDS = 120


def finding_changes(db: Session, findings: list[FindingEntity], config: AlertEnrichmentConfig) -> dict[int, dict[str, Any]]:
    """Change context per finding id. One failure marks that finding `unavailable`, never the list."""
    if not findings:
        return {}
    try:
        with_events = _services_with_events(db, findings, config.service_aliases)
        candidates = [finding for finding in findings if finding.service in with_events]
        signals = _signals(db, candidates)
        envs = _run_envs(db, candidates) if config.match_env else {}
    except Exception:  # noqa: BLE001 - deploy context is extra; the findings must still load
        logger.warning("Change lookup for findings failed", exc_info=True)
        db.rollback()
        return {finding.id: _unavailable("error") for finding in findings}

    result: dict[int, dict[str, Any]] = {}
    for finding in findings:
        try:
            result[finding.id] = _finding_changes(db, finding, with_events, signals, envs, config)
        except Exception:  # noqa: BLE001
            logger.warning("Change lookup failed for finding %s", finding.id, exc_info=True)
            db.rollback()
            result[finding.id] = _unavailable("error")
    return result


def _finding_changes(
    db: Session,
    finding: FindingEntity,
    with_events: set[str],
    signals: dict[str, SignalEntity],
    envs: dict[str, str],
    config: AlertEnrichmentConfig,
) -> dict[str, Any]:
    if not finding.service:
        return _unavailable("no_service")
    if finding.service not in with_events:
        return {"status": "no_events_for_service", "service": finding.service, "deploy_discovery": get_deploy_discovery_config().enabled}
    anchor = change_time(finding, signals)
    if anchor is None:
        return {**_unavailable("no_change_time"), "service": finding.service}

    correlation = correlate_changes(
        db,
        finding.service,
        anchor,
        before=timedelta(seconds=config.correlation_before_seconds),
        after=timedelta(seconds=config.correlation_after_seconds),
        env=envs.get(finding.analysis_run_id or ""),
        aliases=config.service_aliases,
        cluster=finding.cluster,
    )
    changes = changes_to_dict(correlation) or {}
    if not correlation.matches:
        return {**changes, "status": "none_in_window", "service": finding.service}
    deploy = next((match for match in correlation.matches if match.event_type in _POD_STARTING_TYPES), None)
    pods = pod_link(
        _breakdown(finding),
        deploy_id=deploy.id if deploy else None,
        deploy_time=deploy.timestamp if deploy else None,
        rollout=timedelta(seconds=config.deploy_rollout_seconds),
    )
    return {**changes, "status": "matched", "service": finding.service, "pods": pods}


def change_time(finding: FindingEntity, signals: dict[str, SignalEntity]) -> datetime | None:
    """When the finding's change started: the breakdown's split if there is one, else the earliest
    change point among its signals, else the start of its earliest short unusual stretch. A trend or
    a forecast has no single moment, so it gives None."""
    window_after = (_breakdown(finding) or {}).get("window_after")
    if isinstance(window_after, list) and window_after:
        parsed = _parse_time(window_after[0])
        if parsed is not None:
            return parsed

    detections = [
        signal
        for signal_id in finding.signal_ids or []
        if (signal := signals.get(signal_id)) is not None and (signal.evidence_json or {}).get("finding_rule_matched", True) is not False
    ]
    change_points = [
        point for point in (_parse_time((signal.evidence_json or {}).get("change_point_time")) for signal in detections) if point
    ]
    if change_points:
        return min(change_points)
    starts = [as_utc(signal.start_time) for signal in detections if signal.signal_type in _LOCALIZED_SIGNAL_TYPES and signal.start_time]
    return min(starts) if starts else None


def pod_link(
    breakdown: dict[str, Any] | None,
    *,
    deploy_id: int | None,
    deploy_time: datetime | None,
    rollout: timedelta,
) -> dict[str, Any]:
    """Whether the breakdown's new pods first reported within the rollout window after the deploy."""
    if not breakdown or breakdown.get("status") != "ok":
        return {"status": "not_linked", "reason": "no_breakdown"}
    label = str(breakdown.get("label") or "pod")
    if not breakdown.get("new_parts"):
        return {"status": "not_linked", "reason": "no_new_parts", "label": label}
    if deploy_time is None:
        return {"status": "not_linked", "reason": "no_deploy", "label": label}
    first_seen = breakdown.get("new_parts_first_seen")
    if not isinstance(first_seen, dict) or not first_seen:
        return {"status": "not_linked", "reason": "no_start_times", "label": label}

    opens = deploy_time - timedelta(seconds=_EARLY_START_SECONDS)
    closes = deploy_time + rollout
    linked: list[str] = []
    for name, raw in first_seen.items():
        started = _parse_time(raw)
        if started is not None and opens <= started <= closes:
            linked.append(str(name))
    rollout_minutes = int(rollout.total_seconds() // 60)
    if not linked:
        return {"status": "not_linked", "reason": "started_outside_rollout", "label": label, "rollout_minutes": rollout_minutes}

    parts_total = int(breakdown.get("parts_total") or 0)
    new_parts = int(breakdown.get("new_parts") or 0)
    gone_parts = int(breakdown.get("gone_parts") or 0)
    return {
        "status": "linked",
        "method": "pod_start_time",
        "event_id": deploy_id,
        "label": label,
        "parts": linked,
        "new_parts": new_parts,
        "old_parts_running": max(parts_total - new_parts - gone_parts, 0),
        "old_parts_gone": gone_parts,
        "rollout_minutes": rollout_minutes,
    }


def _services_with_events(db: Session, findings: list[FindingEntity], aliases: list[list[str]]) -> set[str]:
    """The findings' services that have at least one change event under any of their names."""
    names_by_service = {finding.service: service_names(finding.service, aliases) for finding in findings if finding.service}
    if not names_by_service:
        return set()
    all_names = {name for names in names_by_service.values() for name in names}
    recorded = set(
        db.execute(select(ChangeEventEntity.service).where(ChangeEventEntity.service.in_(all_names)).distinct()).scalars()
    )
    return {service for service, names in names_by_service.items() if recorded.intersection(names)}


def _signals(db: Session, findings: list[FindingEntity]) -> dict[str, SignalEntity]:
    # Only findings without a usable breakdown window need their signals.
    ids = {
        signal_id
        for finding in findings
        if not (_breakdown(finding) or {}).get("window_after")
        for signal_id in finding.signal_ids or []
    }
    if not ids:
        return {}
    rows = db.execute(select(SignalEntity).where(SignalEntity.signal_id.in_(ids))).scalars()
    return {row.signal_id: row for row in rows}


def _run_envs(db: Session, findings: list[FindingEntity]) -> dict[str, str]:
    """Environment of each finding's autonomous run, so a staging deploy isn't matched to prod.
    CSV / OTLP runs have no job row and no environment: their findings match events from any env."""
    run_ids = {finding.analysis_run_id for finding in findings if finding.analysis_run_id}
    if not run_ids:
        return {}
    rows = db.execute(
        select(AutonomousMetricJobEntity.analysis_run_id, AutonomousMetricJobEntity.environment).where(
            AutonomousMetricJobEntity.analysis_run_id.in_(run_ids)
        )
    ).all()
    return {run_id: env for run_id, env in rows if run_id and env}


def _breakdown(finding: FindingEntity) -> dict[str, Any] | None:
    breakdown = (finding.comparison_json or {}).get("breakdown")
    return breakdown if isinstance(breakdown, dict) else None


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(timestamp):
        return None
    return as_utc(timestamp.to_pydatetime())


def _unavailable(reason: str) -> dict[str, Any]:
    return {"status": "unavailable", "reason": reason}
