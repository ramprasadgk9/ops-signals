"""What a guided investigation starts from: the finding in plain words, where to query its series
again, what changed around it, and what the team knows about the service.

A finding can be investigated when its run queried Prometheus through a configured connection: the
checks query that connection. CSV and OTLP findings can't (nothing to query again), and neither can
a finding with no service.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.alerts.correlation import as_utc
from backend.app.config import AlertEnrichmentConfig, get_prometheus_connections
from backend.app.models.entities import AnalysisRunEntity, FindingEntity, SignalEntity
from backend.app.services import service_notes
from backend.app.services.finding_changes import change_time
from backend.app.services.finding_plain import finding_plain

logger = logging.getLogger(__name__)

SOURCES = ("notes", "changes", "cases")
# How far before the problem started the checks look by default, to see what normal was.
LEAD = timedelta(hours=1)
# ...and at most this long after it.
SPAN = timedelta(hours=6)


@dataclass(slots=True)
class FindingContext:
    finding_id: int
    service: str | None
    metric_name: str
    cluster: str | None
    connection_id: str | None
    connection_name: str | None
    promql: str | None
    started_at: datetime | None
    changed_at: datetime | None
    ended_at: datetime | None
    ongoing: bool
    headline: str
    what: str
    eligible: bool
    reason: str | None = None
    breakdown: dict[str, Any] | None = None
    note: dict[str, Any] = field(default_factory=dict)

    @property
    def anchor(self) -> datetime | None:
        """When the problem started: the change point, else the finding's start."""
        return self.changed_at or self.started_at

    @property
    def window(self) -> tuple[datetime, datetime]:
        """The default time range for checks: an hour before the start, to the end (or now), at
        most SPAN after the start, so it always shows the change and what normal was before it."""
        now = datetime.now(timezone.utc)
        anchor = self.anchor or now - timedelta(hours=1)
        end = self.ended_at if self.ended_at and not self.ongoing else now
        return anchor - LEAD, min(max(end, anchor + timedelta(minutes=30)), anchor + SPAN)


def finding_context(db: Session, finding: FindingEntity) -> FindingContext:
    run = db.get(AnalysisRunEntity, finding.analysis_run_id) if finding.analysis_run_id else None
    connections = get_prometheus_connections()
    connection = connections.get(run.connection_id) if run and run.connection_id else None
    plain = _plain(db, finding)
    signals = {
        row.signal_id: row
        for row in db.execute(select(SignalEntity).where(SignalEntity.signal_id.in_(list(finding.signal_ids or [])))).scalars()
    } if finding.signal_ids else {}
    try:
        changed_at = change_time(finding, signals)
    except Exception:  # noqa: BLE001 - the window falls back to the finding's start
        logger.info("No change time for finding %s", finding.id, exc_info=True)
        changed_at = None

    eligible, reason = True, None
    if not finding.service or finding.service == "unknown":
        eligible, reason = False, "This finding has no service, so there's nothing to start from."
    elif run is None or run.source_type != "prometheus":
        eligible, reason = False, "This finding came from an uploaded file or OTLP data, so there's no query to run again."
    elif connection is None or not connection.base_url:
        eligible, reason = False, "The Prometheus connection this finding came from isn't set up any more."

    return FindingContext(
        finding_id=finding.id,
        service=finding.service,
        metric_name=finding.metric_name,
        cluster=finding.cluster,
        connection_id=run.connection_id if run else None,
        connection_name=getattr(connection, "name", None) if connection else None,
        promql=run.promql if run else None,
        started_at=as_utc(finding.event_start) if finding.event_start else None,
        changed_at=as_utc(changed_at) if changed_at else None,
        ended_at=as_utc(finding.event_end) if finding.event_end else None,
        ongoing=bool(finding.ongoing),
        headline=(plain or {}).get("headline") or finding.title,
        what=(plain or {}).get("what") or finding.summary,
        eligible=eligible,
        reason=reason,
        breakdown=(finding.comparison_json or {}).get("breakdown") if isinstance(finding.comparison_json, dict) else None,
        note=service_notes.get_note(db, finding.service) if finding.service else {},
    )


def first_message(context: FindingContext, changes: list[str], today: str | None, skipped: list[str]) -> str:
    """The investigation's first user message: the facts, in plain words."""
    start, end = context.window
    lines = [
        f"Finding {context.finding_id} · {'still happening' if context.ongoing else 'over'}",
        f"Service: {context.service} · Metric: {context.metric_name}" + (f" · Cluster: {context.cluster}" if context.cluster else ""),
        f"What happened: {context.headline}. {context.what}".strip(),
    ]
    if context.changed_at:
        lines.append(f"It changed at about {_hhmm(context.changed_at)} UTC on {context.changed_at:%Y-%m-%d}.")
    lines.append(f"Time range to check (UTC): {start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M}. Tools use it unless you give another.")
    if context.promql:
        lines.append(f"Query that found it: {context.promql}")
    breakdown_line = _breakdown_line(context.breakdown)
    if breakdown_line:
        lines.append(f"Already checked by Ops Signals: {breakdown_line}")
    if "changes" not in skipped:
        lines.append("Changes recorded near the start: " + ("; ".join(changes) if changes else "none."))
    notes = service_notes.notes_text(context.note) if "notes" not in skipped else None
    lines.append(f"What the team knows about {context.service}:\n{notes}" if notes else f"Nobody has written down what {context.service} depends on.")
    if today:
        lines.append(f'The engineer\'s note for today: "{today}"')
    available = ["Prometheus metrics"] + [label for key, label in (("changes", "deploys and changes"), ("cases", "past cases")) if key not in skipped]
    lines.append(f"Sources you can use: {', '.join(available)}. Not available: logs, traces, the databases and services themselves.")
    lines.append("Suggest where to look next. Start with the checks that rule out the most.")
    return "\n".join(lines)


def _breakdown_line(breakdown: dict[str, Any] | None) -> str | None:
    """The finding's own breakdown (by pod or instance), in one sentence."""
    if not breakdown:
        return None
    label = breakdown.get("label") or "part"
    if breakdown.get("status") == "ok":
        changed, total = breakdown.get("parts_changed"), breakdown.get("parts_total")
        top = ", ".join(str(row.get("value")) for row in (breakdown.get("top") or [])[:3] if row.get("value"))
        return f"by {label}: {changed} of {total} changed" + (f" (most: {top})" if top else "") + "."
    if breakdown.get("reason") == "single_part":
        return f"by {label}: only one {label} reports this metric."
    return None


def _plain(db: Session, finding: FindingEntity) -> dict[str, Any] | None:
    try:
        return finding_plain(db, [finding]).get(finding.id)
    except Exception:  # noqa: BLE001 - the stored title and summary still work
        logger.info("Plain wording failed for finding %s", finding.id, exc_info=True)
        return None


def _hhmm(moment: datetime) -> str:
    return moment.strftime("%H:%M")


def change_lines(db: Session, context: FindingContext, config: AlertEnrichmentConfig) -> list[str]:
    """Deploys and other changes on the service from an hour before the change to its end."""
    from backend.app.investigation.tools import change_rows

    start, end = context.window
    return [row["line"] for row in change_rows(db, context.service or "", start, end, config.service_aliases)]
