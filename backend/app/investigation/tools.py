"""The checks a guided investigation may run. All read-only, all limited in code (the prompt also
says so, but a model can ignore a prompt):

- Prometheus queries go to the finding's own connection, chosen here; the model never sees a URL
  or a credential. A range query covers at most MAX_WINDOW, returns at most MAX_SERIES series and
  about POINTS points each, and comes back summarised in a few lines, not as raw points.
- Change events, past cases and other findings come from Postgres.
- The starting checks (starting_calls) are range queries the code runs before the model's first
  turn: the query that found the finding, whether its scrape targets were up, and how many samples
  they returned. A finding from a run that didn't keep its query gets its metric selector instead
  (request_latency_p95{service="mixed-lab"}), built from the series Prometheus has for the service,
  so the model never has to guess how the metric and service names fit together. Prometheus' own `up` and `scrape_samples_scraped`, so they hold in any domain.

A check that fails returns a message for the model, never an exception: the loop counts failures
to tell a broken source from a bad query. A range query that names a metric Prometheus doesn't have
fails too, and lists the service's real metric names, so a wrong name never reads as "nothing there".
Only the metric names are checked, from Prometheus' own list of names: a wrong label value still
comes back as plain no data.
"""

from __future__ import annotations

import logging
import math
import re
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.app.ai.tool_calls import ToolCall, ToolSpec, new_call_id
from backend.app.alerts.correlation import as_utc, service_names
from backend.app.investigation.context import FindingContext
from backend.app.models.entities import ChangeEventEntity, FindingEntity, OperationalCaseEntity
from backend.app.services.finding_plain import finding_plain, significant, utc_text
from backend.app.services.prometheus_service import PrometheusQueryService

logger = logging.getLogger(__name__)

MAX_WINDOW = timedelta(hours=12)
MAX_SERIES = 20
POINTS = 120
MIN_STEP_SECONDS = 15
SERIES_LIMIT = 2000
MAX_METRICS_LISTED = 60
MAX_VALUES_LISTED = 50
MAX_QUERY_LENGTH = 2000
MAX_CASES = 5
MAX_FINDINGS = 10
MAX_NAMES_SHOWN = 15
NO_DATA = "No data for that query"
UP_PURPOSE = "Were its scrape targets up?"
MAX_JOBS = 5
MAX_GAPS_LISTED = 3
# A gap between points this many times the usual spacing is reported as missing data.
GAP_FACTOR = 2.5
# Statuses that mean Prometheus itself is unreachable, not that the query was wrong.
SOURCE_DOWN_STATUSES = {502, 503, 504}

_PURPOSE = {"type": "string", "description": "Why you are running this check, in a few plain words; shown to the engineer."}
_TIME = {"type": "string", "description": "UTC time, ISO 8601 (2026-11-05T22:00:00Z). Leave out to use the finding's time range."}


@dataclass(slots=True)
class CheckResult:
    ok: bool
    text: str
    purpose: str | None = None
    query: str | None = None
    # Prometheus couldn't be reached (not a bad query).
    source_down: bool = False
    # A series of a range query has no data when the problem started.
    gap_at_start: bool = False


class ToolBox:
    def __init__(
        self,
        db: Session,
        context: FindingContext,
        prometheus: PrometheusQueryService,
        service_labels: list[str],
        aliases: list[list[str]] | None = None,
        skipped: list[str] | None = None,
    ) -> None:
        self.db = db
        self.context = context
        self.prometheus = prometheus
        self.service_labels = service_labels
        self.aliases = aliases or []
        self.skipped = set(skipped or [])
        self._service_label: str | None = None
        self._metric_names: set[str] | None = None
        self._tools: dict[str, tuple[ToolSpec, Callable[[dict[str, Any]], CheckResult]]] = {}
        self._add(
            ToolSpec(
                "list_series",
                "List the metrics that carry this service's label, with their label names. Use it to find metrics about "
                "dependencies (database, cache, queue, other services) and saturation. `match` filters metric names (regex).",
                _schema({"match": {"type": "string", "description": "Regex on metric names, e.g. db|pool|redis. Optional."}}),
            ),
            self.list_series,
        )
        self._add(
            ToolSpec(
                "label_values",
                "List the values of one label of one metric for this service, e.g. pod, route, code, version.",
                _schema({"metric": {"type": "string"}, "label": {"type": "string"}}, required=["metric", "label"]),
            ),
            self.label_values,
        )
        self._add(
            ToolSpec(
                "query_range",
                f"Run a PromQL range query and get each series summarised: its level before and after the change, min, max "
                f"and when it changed most. At most {MAX_SERIES} series (aggregate with sum by (...) when there are more) and "
                f"{int(MAX_WINDOW.total_seconds() // 3600)} hours.",
                _schema({"promql": {"type": "string"}, "start": _TIME, "end": _TIME}, required=["promql"]),
            ),
            self.query_range,
        )
        if "changes" not in self.skipped:
            self._add(
                ToolSpec("changes", "Deploys, rollbacks, config changes and scaling recorded for a service in a time range.",
                         _schema({"service": {"type": "string", "description": "Defaults to the finding's service."}, "start": _TIME, "end": _TIME})),
                self.changes,
            )
        if "cases" not in self.skipped:
            self._add(
                ToolSpec("similar_cases", "Past cases on this service with their recorded root cause and fix.", _schema({})),
                self.similar_cases,
            )
        self._add(
            ToolSpec("findings_for", "Other Ops Signals findings on the given services in a time range, e.g. its dependencies.",
                     _schema({"services": {"type": "array", "items": {"type": "string"}}, "start": _TIME, "end": _TIME}, required=["services"])),
            self.findings_for,
        )

    def _add(self, spec: ToolSpec, handler: Callable[[dict[str, Any]], CheckResult]) -> None:
        self._tools[spec.name] = (spec, handler)

    @property
    def specs(self) -> list[ToolSpec]:
        return [spec for spec, _ in self._tools.values()]

    def run(self, call: ToolCall) -> CheckResult:
        entry = self._tools.get(call.name)
        purpose = str(call.arguments.get("purpose") or "").strip()[:300] or None
        if entry is None:
            return CheckResult(False, f"There is no tool called {call.name!r}. Use one of: {', '.join(self._tools)}.", purpose)
        try:
            result = entry[1](call.arguments)
        except HTTPException as exc:
            down = exc.status_code in SOURCE_DOWN_STATUSES
            text = "Prometheus couldn't be reached." if down else f"The check failed: {exc.detail}"
            result = CheckResult(False, text, source_down=down)
        except Exception as exc:  # noqa: BLE001 - a check must never break the investigation
            logger.warning("Investigation check %s failed", call.name, exc_info=True)
            result = CheckResult(False, f"The check failed: {type(exc).__name__}.")
        result.purpose = purpose
        return result

    def starting_calls(self) -> list[ToolCall]:
        """The checks every investigation starts with, run by the code before the model's first turn."""
        try:
            label, series = self._service_series(*self.context.window)
        except Exception:  # noqa: BLE001 - the model can still look itself
            logger.info("Investigation: couldn't list the series of %s", self.context.service, exc_info=True)
            label, series = "", []
        calls = []
        if self.context.promql:
            calls.append(ToolCall(new_call_id(), "query_range", {"promql": self.context.promql, "purpose": "The query that found it"}))
        elif series and any(row.get("__name__") == self.context.metric_name for row in series):
            selector = f'{self.context.metric_name}{{{label}="{_escape(self.context.service or "")}"}}'
            calls.append(ToolCall(new_call_id(), "query_range", {"promql": selector, "purpose": "The metric that found it"}))
        jobs = sorted({row["job"] for row in series if row.get("job")})[:MAX_JOBS]
        if jobs:
            matcher = f'job="{_escape(jobs[0])}"' if len(jobs) == 1 else 'job=~"' + "|".join(_escape(re.escape(job)) for job in jobs) + '"'
            calls.append(ToolCall(new_call_id(), "query_range", {"promql": f"sum by (job) (up{{{matcher}}})", "purpose": UP_PURPOSE}))
            calls.append(ToolCall(new_call_id(), "query_range", {"promql": f"sum by (job) (scrape_samples_scraped{{{matcher}}})", "purpose": "Did Prometheus get as many samples as usual?"}))
        return calls

    # --- Prometheus ------------------------------------------------------------------------

    def list_series(self, args: dict[str, Any]) -> CheckResult:
        start, end = self._window(args)
        label, series = self._service_series(start, end)
        if not series:
            return CheckResult(True, f"No series carry {self.context.service} under any of these labels: {', '.join(self.service_labels)}.")
        pattern = _regex(args.get("match"))
        metrics: dict[str, set[str]] = {}
        for row in series:
            name = row.get("__name__", "")
            if pattern and not pattern.search(name):
                continue
            metrics.setdefault(name, set()).update(key for key in row if key not in {"__name__", label})
        if not metrics:
            return CheckResult(True, f"No metric of {self.context.service} matches {args.get('match')!r}.")
        names = sorted(metrics)
        lines = [f"{name} (labels: {', '.join(sorted(metrics[name])) or 'none'})" for name in names[:MAX_METRICS_LISTED]]
        more = f"\n... and {len(names) - MAX_METRICS_LISTED} more; narrow it with match." if len(names) > MAX_METRICS_LISTED else ""
        return CheckResult(True, f'Metrics with {label}="{self.context.service}":\n' + "\n".join(lines) + more, query=f'{{{label}="{self.context.service}"}}')

    def label_values(self, args: dict[str, Any]) -> CheckResult:
        metric, label = str(args.get("metric") or "").strip(), str(args.get("label") or "").strip()
        if not _NAME.match(metric) or not _NAME.match(label):
            return CheckResult(False, "metric and label must be plain metric and label names.")
        start, end = self._window(args)
        service_label = self._find_service_label(start, end)
        matcher = f'{{__name__="{metric}",{service_label}="{_escape(self.context.service or "")}"}}'
        values = self.prometheus.label_values(label, [matcher], start=start, end=end)
        if not values:
            return CheckResult(True, f"{metric} has no {label} values for {self.context.service} in that range.", query=matcher)
        shown = ", ".join(values[:MAX_VALUES_LISTED]) + (f" ... ({len(values)} in all)" if len(values) > MAX_VALUES_LISTED else "")
        return CheckResult(True, f"{label} of {metric}: {shown}", query=matcher)

    def query_range(self, args: dict[str, Any]) -> CheckResult:
        promql = str(args.get("promql") or "").strip()
        if not promql or len(promql) > MAX_QUERY_LENGTH:
            return CheckResult(False, f"promql is required and must be under {MAX_QUERY_LENGTH} characters.")
        start, end = self._window(args)
        step = max(MIN_STEP_SECONDS, math.ceil((end - start).total_seconds() / POINTS))
        try:
            result = self.prometheus.query_result(promql, start=start, end=end, step_seconds=step, max_series=MAX_SERIES)
        except HTTPException as exc:
            if "exceeds max_series" in str(exc.detail):
                return CheckResult(False, f"That query returns more than {MAX_SERIES} series. Aggregate it, e.g. sum by (<label>) (...).", query=promql)
            raise
        if not result:
            unknown = self.unknown_metrics(metric_names_in(promql))
            if unknown:
                return CheckResult(False, f"{NO_DATA}: Prometheus has no metric called {', '.join(unknown)}. {self._names_hint()}".strip(), query=promql)
            return CheckResult(True, f"{NO_DATA} between {_hhmm(start)} and {_hhmm(end)} UTC. If you expected data, check the label values with label_values.", query=promql)
        lines = [summarise_series(item, self.context.anchor) for item in result]
        text = f"{len(result)} series, {_hhmm(start)}–{_hhmm(end)} UTC, a point every {step} s:\n" + "\n".join(lines)
        return CheckResult(True, text, query=promql, gap_at_start=any(GAP_AT_START in line for line in lines))

    # --- Postgres --------------------------------------------------------------------------

    def changes(self, args: dict[str, Any]) -> CheckResult:
        service = str(args.get("service") or self.context.service or "")
        start, end = self._window(args)
        rows = change_rows(self.db, service, start, end, self.aliases)
        if not rows:
            return CheckResult(True, f"No deploy or other change recorded for {service} between {_hhmm(start)} and {_hhmm(end)} UTC.")
        return CheckResult(True, "\n".join(row["line"] for row in rows))

    def similar_cases(self, args: dict[str, Any]) -> CheckResult:
        rows = self.db.execute(
            select(OperationalCaseEntity)
            .where(or_(OperationalCaseEntity.root_cause_summary.is_not(None), OperationalCaseEntity.corrective_action.is_not(None)))
            .order_by(OperationalCaseEntity.updated_at.desc())
            .limit(200)
        ).scalars().all()
        names = {name.lower() for name in service_names(self.context.service or "", self.aliases)}
        cases = [case for case in rows if str((case.finding_snapshot or {}).get("service") or "").lower() in names][:MAX_CASES]
        if not cases:
            return CheckResult(True, f"No past case on {self.context.service} has a recorded cause or fix.")
        lines = [
            f"case #{case.id} ({case.created_at:%Y-%m-%d}): {case.case_title}. Cause: {case.root_cause_summary or 'not recorded'}. "
            f"Fix: {case.corrective_action or case.outcome_summary or 'not recorded'}."
            for case in cases
        ]
        return CheckResult(True, "\n".join(lines))

    def findings_for(self, args: dict[str, Any]) -> CheckResult:
        services = [str(name) for name in args.get("services") or [] if str(name).strip()][:10]
        if not services:
            return CheckResult(False, "services is required.")
        start, end = self._window(args)
        rows = self.db.execute(
            select(FindingEntity)
            .where(
                func.lower(FindingEntity.service).in_([name.lower() for name in services]),
                FindingEntity.id != self.context.finding_id,
                or_(
                    FindingEntity.event_start.between(start, end),
                    (FindingEntity.event_start.is_(None) & FindingEntity.created_at.between(start, end)),
                ),
            )
            .order_by(FindingEntity.event_start.desc().nullslast())
            .limit(MAX_FINDINGS)
        ).scalars().all()
        if not rows:
            watched = self.db.execute(select(func.lower(FindingEntity.service)).where(func.lower(FindingEntity.service).in_([name.lower() for name in services])).distinct()).scalars().all()
            unwatched = [name for name in services if name.lower() not in watched]
            extra = f" Ops Signals has never had a finding on {', '.join(unwatched)}, so it may not watch them." if unwatched else ""
            return CheckResult(True, f"No findings on {', '.join(services)} between {_hhmm(start)} and {_hhmm(end)} UTC.{extra}")
        try:
            plain = finding_plain(self.db, list(rows))
        except Exception:  # noqa: BLE001 - the stored titles still answer the question
            logger.info("Investigation: no plain wording for findings_for", exc_info=True)
            plain = {}
        lines = [
            f"{row.service} · {row.metric_name}: {_said(row, plain.get(row.id))}" + (f" (from {_hhmm(as_utc(row.event_start))} UTC)" if row.event_start else "")
            for row in rows
        ]
        return CheckResult(True, "\n".join(lines))

    # --- helpers ---------------------------------------------------------------------------

    def window(self, args: dict[str, Any]) -> tuple[datetime, datetime]:
        """The time range a check with these arguments covers."""
        return self._window(args)

    def _window(self, args: dict[str, Any]) -> tuple[datetime, datetime]:
        default_start, default_end = self.context.window
        start = _parse_time(args.get("start")) or default_start
        end = _parse_time(args.get("end")) or default_end
        if end <= start:
            start, end = default_start, default_end
        if end - start > MAX_WINDOW:
            end = start + MAX_WINDOW
        return start, end

    def _service_series(self, start: datetime, end: datetime) -> tuple[str, list[dict[str, str]]]:
        for label in [self._service_label] if self._service_label else self.service_labels:
            if not label:
                continue
            rows = self.prometheus.direct_scoped_series(f'{{{label}="{_escape(self.context.service or "")}"}}', start=start, end=end, limit=SERIES_LIMIT)
            if rows:
                self._service_label = label
                return label, rows
        return self.service_labels[0] if self.service_labels else "service", []

    def metric_names(self) -> set[str] | None:
        """Every metric name Prometheus has around the finding, or None when it can't be listed."""
        if self._metric_names is None:
            start, end = self.context.window
            try:
                self._metric_names = set(self.prometheus.label_values("__name__", start=start - MAX_WINDOW, end=end))
            except Exception:  # noqa: BLE001 - without the list nothing is flagged
                logger.info("Investigation: couldn't list metric names", exc_info=True)
                self._metric_names = set()
        return self._metric_names or None

    def unknown_metrics(self, names: list[str]) -> list[str]:
        known = self.metric_names() if names else None
        return [name for name in names if name not in known] if known else []

    def _names_hint(self) -> str:
        try:
            label, series = self._service_series(*self.context.window)
        except Exception:  # noqa: BLE001 - the hint is optional
            return ""
        names = sorted({row.get("__name__", "") for row in series} - {""})
        if not names:
            return ""
        shown = ", ".join(names[:MAX_NAMES_SHOWN]) + (f" ... ({len(names)} in all; list_series shows them)" if len(names) > MAX_NAMES_SHOWN else "")
        return f'Metrics with {label}="{self.context.service}": {shown}.'

    def _find_service_label(self, start: datetime, end: datetime) -> str:
        if self._service_label is None:
            self._service_series(start, end)
        return self._service_label or (self.service_labels[0] if self.service_labels else "service")


def change_rows(db: Session, service: str, start: datetime, end: datetime, aliases: list[list[str]] | None) -> list[dict[str, Any]]:
    names = [name.lower() for name in service_names(service, aliases)]
    rows = db.execute(
        select(ChangeEventEntity)
        .where(func.lower(ChangeEventEntity.service).in_(names), ChangeEventEntity.timestamp.between(start, end))
        .order_by(ChangeEventEntity.timestamp)
        .limit(30)
    ).scalars().all()
    result = []
    for row in rows:
        parts = [row.event_type] + ([row.version] if row.version else []) + ([f"({row.description})"] if row.description else [])
        result.append({"at": as_utc(row.timestamp), "line": f"{as_utc(row.timestamp):%Y-%m-%d %H:%M} UTC {row.service}: {' '.join(parts)}"})
    return result


def summarise_series(item: dict[str, Any], changed_at: datetime | None) -> str:
    """One line per series: its labels, level before and after the change, range, and when it
    moved most. Enough for the model to compare series, far smaller than the points."""
    labels = {key: value for key, value in (item.get("metric") or {}).items() if key != "__name__"}
    name = "{" + ", ".join(f'{key}="{value}"' for key, value in sorted(labels.items())) + "}" if labels else "(one series)"
    points = []
    for stamp, raw in item.get("values") or []:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            points.append((datetime.fromtimestamp(float(stamp), tz=timezone.utc), value))
    if not points:
        return f"{name}: no numeric data."
    values = [value for _, value in points]
    if changed_at and points[0][0] < changed_at < points[-1][0]:
        before = [value for moment, value in points if moment < changed_at]
        after = [value for moment, value in points if moment >= changed_at]
        level = f"before {_hhmm(changed_at)} about {significant(statistics.median(before))}, after about {significant(statistics.median(after))}"
    else:
        third = max(1, len(values) // 3)
        level = f"first third about {significant(statistics.median(values[:third]))}, last third about {significant(statistics.median(values[-third:]))}"
    gaps = _gaps([moment for moment, _ in points])
    if changed_at:
        # The gap at the problem's start first: it is the one that matters, and the list is cut short.
        gaps.sort(key=lambda gap: not gap[0] <= changed_at <= gap[1])
    smoothed = [statistics.median(values[max(0, index - 1): index + 2]) for index in range(len(values))]
    jumps = [abs(smoothed[index] - smoothed[index - 1]) for index in range(1, len(smoothed))]
    moved = ""
    if jumps and max(jumps) > 0:
        index = jumps.index(max(jumps)) + 1
        moved = f"; changed most at {_hhmm(points[index][0])}"
    missing = ""
    if gaps:
        listed = ", ".join(
            f"{_hhmm(start)}–{_hhmm(end)}" + (GAP_AT_START if changed_at and start <= changed_at <= end else "") for start, end in gaps[:MAX_GAPS_LISTED]
        )
        missing = f"; no data {listed}" + (f" and {len(gaps) - MAX_GAPS_LISTED} more gaps" if len(gaps) > MAX_GAPS_LISTED else "")
    return f"{name}: {level} (min {significant(min(values))}, max {significant(max(values))}, last {significant(values[-1])}){moved}{missing}."


def _gaps(moments: list[datetime]) -> list[tuple[datetime, datetime]]:
    """Stretches with no points: between two points much further apart than the usual spacing."""
    if len(moments) < 3:
        return []
    spacings = [(later - earlier).total_seconds() for earlier, later in zip(moments, moments[1:])]
    usual = statistics.median(spacings)
    if usual <= 0:
        return []
    return [(moments[index], moments[index + 1]) for index, spacing in enumerate(spacings) if spacing > usual * GAP_FACTOR]


_NAME = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
# What metric_names_in strips from PromQL before reading the names left: strings, label matchers,
# durations and grouping label lists. A name followed by "(" is a function; these words are syntax.
_STRING = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`[^`]*`')
_BRACES = re.compile(r"\{[^}]*\}")
_BRACKETS = re.compile(r"\[[^\]]*\]")
_GROUPING = re.compile(r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)", re.IGNORECASE)
_IDENT = re.compile(r"(?<![\w:.])([a-zA-Z_:][a-zA-Z0-9_:]*)(?![\w:])\s*(\()?")
_PROMQL_WORDS = {"by", "without", "on", "ignoring", "group_left", "group_right", "offset", "bool", "and", "or", "unless", "atan2", "inf", "nan"}
# In free text (a step for the engineer), only a name directly followed by a selector or a range is
# taken as a metric, so commands and prose are never read as PromQL.
_SELECTOR = re.compile(r"(?<![\w:])([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{|\[\d+[smhdwy]\])")


def metric_names_in(promql: str) -> list[str]:
    """The metric names a PromQL expression reads."""
    text = _GROUPING.sub(" ", _BRACKETS.sub(" ", _BRACES.sub(" ", _STRING.sub(" ", promql or ""))))
    names: list[str] = []
    for match in _IDENT.finditer(text):
        name, call = match.group(1), match.group(2)
        if not call and name.lower() not in _PROMQL_WORDS and name not in names:
            names.append(name)
    return names


def selector_names_in(text: str) -> list[str]:
    """Metric names written as selectors (name{...} or name[5m]) in free text."""
    names: list[str] = []
    for name in _SELECTOR.findall(_STRING.sub(" ", text or "")):
        if name not in names:
            names.append(name)
    return names
GAP_AT_START = " (when the problem started)"


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {**properties, "purpose": _PURPOSE},
        "required": [*(required or []), "purpose"],
        "additionalProperties": False,
    }


def _regex(value: Any) -> re.Pattern[str] | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return re.compile(text[:200], re.IGNORECASE)
    except re.error:
        return re.compile(re.escape(text[:200]), re.IGNORECASE)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _hhmm(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%H:%M")


def _said(row: FindingEntity, plain: dict[str, Any] | None) -> str:
    """A finding as its card says it, with the numbers and times; its stored title without one."""
    if not plain or not plain.get("headline"):
        return row.title
    return utc_text(f"{plain['headline']}. {plain.get('what') or ''}".strip())


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
