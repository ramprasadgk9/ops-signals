"""Plain-words wording for a finding: a badge, a headline, what changed, why it matters, what to check.

Built when a finding is read, from the finding and its signals' evidence, using the wording in
config/finding_templates.yaml. Nothing is stored: a finding's title and summary stay as they are
(alerts, cases, search and the assistant read them), and old findings get the same wording as new
ones. A finding without enough evidence gets no plain wording, and the card shows its summary.

Times are written as markers, `[[time:2026-10-19T22:54:17Z]]`, so each screen can show them in the
reader's own time zone (frontend/src/utils/findingPlain.ts, notifications/message_builder.py).
"""

from __future__ import annotations

import logging
import math
import re
import string
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.entities import FindingEntity, SignalEntity

logger = logging.getLogger(__name__)

TEMPLATES_PATH = Path(__file__).resolve().parents[3] / "config" / "finding_templates.yaml"
TIME_MARKER = re.compile(r"\[\[time:([^\]]+)\]\]")
_CHUNK = 500
# Level changes of one service this close together are shown as one event, and findings created
# this close together are searched for them.
RELATED_WINDOW = timedelta(minutes=10)  # also in RELATED_HINT (frontend/src/utils/findingPlain.ts)
RELATED_SEARCH = timedelta(hours=24)
RELATED_SEARCH_LIMIT = 500
CHECK_WINDOW = timedelta(minutes=30)
SHARP_PERCENT = 50.0
STEADY_R_SQUARED = 0.5
UNEVEN_R_SQUARED = 0.2
BLIP_MAX = timedelta(minutes=2)
DATA_HEALTH_TYPES = {"data_gap", "flatline"}
ANOMALY_TYPES = {"anomaly", "spike", "outlier"}

COMMON_FIELDS = {"plain_name", "service", "metric"}
# The placeholders each template may use, on top of COMMON_FIELDS.
TEMPLATE_FIELDS: dict[str, set[str]] = {
    "level_change": {"rose_or_dropped", "sharply", "higher_or_lower", "before", "after", "change", "change_time", "window_start", "window_end"},
    "trend": {"climbing_or_falling", "steadily_or_unevenly", "first_half", "second_half", "half", "change", "peak", "down_or_up"},
    "spikes": {"above_or_below", "times", "up_or_down", "peak", "first_time", "last_time", "normal_low", "normal_high", "duration", "typical", "count"},
    "odd_stretch": {"first_time", "last_time"},
    "data_gap": {"duration", "first_time", "last_time", "missing_points", "gap_count"},
    "flatline": {"stuck_value", "duration", "first_time", "last_time", "normal_change"},
    "forecast": {"higher_or_lower", "actual", "expected", "off"},
    # Lines comparing a finding with the service's own target (the `services` section).
    "targets": {"target", "breach_side", "since", "until", "duration", "half", "peak", "value"},
}
REQUIRED_LINES: dict[str, tuple[str, ...]] = {
    "spikes": ("headline", "what", "noise_headline", "noise_what"),
    "targets": (),
}
SERVICE_IMPORTANCE = ("critical", "normal", "low")
BADGES = ("worse", "better", "changed", "gap", "noise", "blip")


# ---------------------------------------------------------------------------------------------
# Wording file


@dataclass(frozen=True)
class Wording:
    badges: dict[str, str]
    concepts: dict[str, dict[str, str]]
    unknown_meaning: str | None
    metrics: dict[str, dict[str, str]]
    patterns: list[tuple[re.Pattern[str], dict[str, str]]]
    templates: dict[str, dict[str, str]]
    services: dict[str, "ServiceContext"] = field(default_factory=dict)
    importance_labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Target:
    limit: float
    # "below": the value should stay below the limit (error rate, latency); "above": it should
    # stay above it (requests, free disk).
    keep: str


@dataclass(frozen=True)
class ServiceContext:
    about: str | None
    importance: str | None
    targets: dict[str, Target]


def _parse_services(raw: Any) -> dict[str, ServiceContext]:
    """The `services` section; a wrong entry is left out and logged, the rest of it stays."""
    services: dict[str, ServiceContext] = {}
    for name, block in (raw or {}).items():
        if not isinstance(block, dict):
            logger.warning("finding_templates: service %r is ignored (expected about, importance, targets)", name)
            continue
        importance = block.get("importance")
        if importance is not None and importance not in SERVICE_IMPORTANCE:
            logger.warning("finding_templates: service %r has importance %r (use critical, normal or low); left out", name, importance)
            importance = None
        targets: dict[str, Target] = {}
        for metric, rule in (block.get("targets") or {}).items():
            keep = next((key for key in ("below", "above") if isinstance(rule, dict) and key in rule), None)
            limit = _number(rule.get(keep)) if keep else None
            if keep is None or limit is None or len(rule) != 1:
                logger.warning("finding_templates: target %r of service %r is left out (write {below: 0.01} or {above: 100})", metric, name)
                continue
            targets[str(metric)] = Target(limit, keep)
        about = block.get("about")
        services[str(name).lower()] = ServiceContext(str(about).strip() if about else None, importance, targets)
    return services


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}


def _bad_fields(text: str, allowed: set[str]) -> set[str]:
    try:
        return _fields(text) - allowed
    except ValueError:
        return {"(unbalanced braces)"}


def parse_wording(raw: dict[str, Any]) -> Wording:
    """Checks every line against the placeholders it may use. A template with a wrong placeholder
    is switched off; a concept line with one is dropped. Each problem is logged once."""
    templates: dict[str, dict[str, str]] = {}
    for name, block in (raw.get("templates") or {}).items():
        allowed = TEMPLATE_FIELDS.get(name)
        if allowed is None or not isinstance(block, dict):
            logger.warning("finding_templates: unknown template %r is ignored", name)
            continue
        lines = {key: str(value) for key, value in block.items() if value is not None}
        problems = {key: bad for key, text in lines.items() if (bad := _bad_fields(text, allowed | COMMON_FIELDS))}
        missing = [key for key in REQUIRED_LINES.get(name, ("headline", "what")) if key not in lines]
        if problems or missing:
            logger.warning(
                "finding_templates: template %r is switched off (unknown placeholders %s, missing lines %s); its findings show the stored summary",
                name,
                {key: sorted(bad) for key, bad in problems.items()},
                missing,
            )
            continue
        templates[name] = lines

    concepts: dict[str, dict[str, str]] = {}
    for name, block in (raw.get("concepts") or {}).items():
        if not isinstance(block, dict):
            continue
        entry: dict[str, str] = {}
        for key, value in block.items():
            text = str(value)
            if key == "bad_when":
                if text not in {"up", "down", "either"}:
                    logger.warning("finding_templates: concept %r has bad_when %r (use up, down or either); treated as unknown", name, text)
                    continue
            elif bad := _bad_fields(text, COMMON_FIELDS):
                logger.warning("finding_templates: concept %r line %r uses unknown placeholders %s and is left out", name, key, sorted(bad))
                continue
            entry[key] = text
        concepts[name] = entry

    patterns: list[tuple[re.Pattern[str], dict[str, str]]] = []
    for rule in raw.get("patterns") or []:
        try:
            patterns.append((re.compile(str(rule["match"])), {key: str(value) for key, value in rule.items() if key != "match"}))
        except (KeyError, TypeError, re.error) as exc:
            logger.warning("finding_templates: pattern rule %r is ignored (%s)", rule, exc)

    unknown = raw.get("unknown_meaning")
    if unknown and _bad_fields(str(unknown), COMMON_FIELDS):
        logger.warning("finding_templates: unknown_meaning uses unknown placeholders and is left out")
        unknown = None
    badges = {key: str((raw.get("badges") or {}).get(key) or key.replace("_", " ").capitalize()) for key in BADGES}
    metrics = {str(name): {key: str(value) for key, value in (entry or {}).items()} for name, entry in (raw.get("metrics") or {}).items()}
    labels = {key: str(value) for key, value in (raw.get("service_importance") or {}).items() if key in SERVICE_IMPORTANCE and value}
    return Wording(badges, concepts, str(unknown) if unknown else None, metrics, patterns, templates, _parse_services(raw.get("services")), labels)


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> Wording | None:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.error("finding_templates: %s can't be read (%s); findings show their stored summary", path, exc)
        return None
    return parse_wording(raw)


def load_wording(path: Path | None = None) -> Wording | None:
    """The wording file, re-read when it changes. None when it is missing or broken."""
    path = path or TEMPLATES_PATH
    if not path.exists():
        return None
    return _load(str(path), path.stat().st_mtime)


# ---------------------------------------------------------------------------------------------
# Numbers, durations and times


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def significant(value: float, digits: int = 2) -> str:
    """`digits` significant figures, never scientific notation, thousands separated."""
    if value == 0:
        return "0"
    decimals = digits - 1 - math.floor(math.log10(abs(value)))
    if decimals <= 0:
        return f"{round(value, decimals):,.0f}"
    text = f"{value:.{decimals}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _trim(text: str) -> str:
    return text[:-2] if text.endswith(".0") else text


def _percent(value: float) -> str:
    if abs(value) < 1:
        return f"{significant(value, 2)}%"
    if abs(value) < 100:
        return f"{_trim(f'{value:.1f}')}%"
    return f"{value:,.0f}%"


def format_value(value: Any, unit: str | None) -> str | None:
    """A value in its metric's unit: 0.1131 as a ratio is "11.3%", 43736678 bytes is "44 MB"."""
    number = _number(value)
    if number is None:
        return None
    if unit == "ratio":
        return _percent(number * 100)
    if unit == "percent":
        return _percent(number)
    if unit == "s":
        if abs(number) < 1:
            return format_value(number * 1000, "ms")
        if abs(number) < 120:
            return f"{_trim(f'{number:.1f}')} s"
        return f"{number / 60:,.0f} min"
    if unit == "ms":
        if abs(number) >= 1000:
            return format_value(number / 1000, "s")
        if abs(number) < 1:
            return f"{significant(number, 2)} ms"
        return f"{number:,.0f} ms"
    if unit == "bytes":
        size = abs(number)
        for suffix, scale in (("TB", 1e12), ("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
            if size >= scale:
                scaled = number / scale
                return f"{scaled:,.0f} {suffix}" if abs(scaled) >= 10 else f"{_trim(f'{scaled:.1f}')} {suffix}"
        return f"{number:,.0f} B"
    if unit == "per_second":
        return f"{significant(number, 3)}/s"
    if unit == "cores":
        return f"{significant(number, 2)} cores"
    if unit == "count":
        return f"{number:,.0f}" if abs(number) >= 1 else significant(number, 2)
    return significant(number, 3 if abs(number) >= 100 else 2)


def change_words(before: float | None, after: float | None, percent: float | None = None) -> str | None:
    """ "up 19%", "down 89%", or "about 4 times as high" for a big rise."""
    if percent is None and before not in (None, 0) and after is not None:
        percent = (after - before) / abs(before) * 100
    if percent is None:
        return None
    if before is not None and after is not None and before > 0 and after / before >= 3:
        return f"about {round(after / before)} times as high"
    rounded = round(abs(percent))
    if rounded == 0:
        return "about the same"
    return f"{'up' if percent > 0 else 'down'} {rounded}%"


def duration_words(minutes: float | None) -> str | None:
    if minutes is None:
        return None
    if minutes < 1:
        return "under a minute"
    if minutes < 90:
        count = round(minutes)
        return f"{count} minute{'s' if count != 1 else ''}"
    if minutes < 48 * 60:
        count = round(minutes / 60)
        return f"{count} hour{'s' if count != 1 else ''}"
    count = round(minutes / 1440)
    return f"{count} day{'s' if count != 1 else ''}"


def times_words(count: int) -> str:
    return {1: "once", 2: "twice"}.get(count, f"{count} times")


def _utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def time_marker(value: Any) -> str | None:
    moment = _utc(value)
    if moment is None:
        return None
    return f"[[time:{moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}]]"


def render_times(text: str, render: Any) -> str:
    """Replaces each time marker with render(datetime)."""
    return TIME_MARKER.sub(lambda match: render(_utc(match.group(1))) if _utc(match.group(1)) else match.group(0), text)


def utc_text(text: str) -> str:
    """Time markers as "Oct 19, 22:54 UTC", for readers that can't localize."""
    return render_times(text, lambda moment: f"{moment.strftime('%b')} {moment.day}, {moment.strftime('%H:%M')} UTC")


# ---------------------------------------------------------------------------------------------
# Facts the templates read


@dataclass(frozen=True)
class SignalFacts:
    signal_type: str
    analyzer_id: str | None
    evidence: dict[str, Any]
    start_time: datetime | None
    end_time: datetime | None


@dataclass(frozen=True)
class FindingFacts:
    metric_name: str
    service: str | None
    title: str
    category: str
    comparison: dict[str, Any] = field(default_factory=dict)
    event_start: datetime | None = None
    event_end: datetime | None = None
    # Whether the problem was still going on at the end of the analyzed data; None when unknown.
    ongoing: bool | None = None


@dataclass(frozen=True)
class MetricMeaning:
    plain_name: str
    unit: str | None
    concept: str | None
    bad_when: str | None


def metric_meaning(metric_name: str, wording: Wording) -> MetricMeaning:
    entry = dict(wording.metrics.get(metric_name) or {})
    for pattern, rule in wording.patterns:
        if pattern.fullmatch(metric_name):
            for key in ("concept", "unit", "plain_name"):
                if key in rule and key not in entry:
                    entry[key] = rule[key]
    concept = entry.get("concept")
    bad_when = (wording.concepts.get(concept) or {}).get("bad_when") if concept else None
    return MetricMeaning(entry.get("plain_name") or metric_name, entry.get("unit"), concept, bad_when)


@dataclass
class Plain:
    kind: str
    badge: str
    headline: str
    what: str
    why: str | None
    check: str | None
    change_time: str | None = None
    service: str | None = None
    metric_name: str | None = None
    # How another finding of the same event mentions this one ("Error rate also dropped at ...").
    related_sentence: str | None = None
    related: list[dict[str, Any]] = field(default_factory=list)
    # The values a target is checked against (before/after, halves, peak...), from the template.
    facts: dict[str, Any] = field(default_factory=dict)
    target: str | None = None
    service_about: str | None = None
    service_importance: str | None = None

    def to_json(self, wording: Wording) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "badge": self.badge,
            "badge_label": wording.badges.get(self.badge, self.badge),
            "headline": self.headline,
            "what": self.what,
            "why": self.why,
            "check": self.check,
            "change_time": self.change_time,
            "related": self.related,
            "target": self.target,
            "service_about": self.service_about,
            "service_importance": self.service_importance,
            "service_importance_label": wording.importance_labels.get(self.service_importance or ""),
        }


def _name_mid_sentence(name: str) -> str:
    """ "Error rate" as "error rate" inside a sentence; "CPU usage" keeps its capitals."""
    return name[0].lower() + name[1:] if len(name) > 1 and name[0].isupper() and name[1].islower() else name


def _fill(text: str | None, values: dict[str, Any]) -> str | None:
    """The line with its placeholders filled, or None when one of them has no value here."""
    if not text:
        return None
    needed = _fields(text)
    if any(values.get(name) is None for name in needed):
        return None
    filled_values = {name: values[name] for name in needed}
    if "plain_name" in filled_values and not text.startswith("{plain_name}"):
        filled_values["plain_name"] = _name_mid_sentence(str(filled_values["plain_name"]))
    filled = text.format(**filled_values)
    return filled[0].upper() + filled[1:] if filled.startswith("this service") else filled


def _join(*parts: str | None) -> str | None:
    kept = [part for part in parts if part]
    return " ".join(kept) if kept else None


def _direction_badge(direction: int, meaning: MetricMeaning) -> str:
    if meaning.bad_when == "either":
        return "worse"
    if meaning.bad_when == "up":
        return "worse" if direction > 0 else "better"
    if meaning.bad_when == "down":
        return "worse" if direction < 0 else "better"
    return "changed"


def _why(badge: str, meaning: MetricMeaning, wording: Wording, values: dict[str, Any]) -> str | None:
    concept = wording.concepts.get(meaning.concept or "") or {}
    if badge in {"worse", "blip"}:
        return _fill(concept.get("worse"), values)
    if badge == "better":
        return _fill(concept.get("better"), values)
    return _fill(wording.unknown_meaning, values)


def _matched(signals: Iterable[SignalFacts]) -> list[SignalFacts]:
    """Signals whose own finding rule matched; older findings also saved the near-misses."""
    signal_list = list(signals)
    kept = [signal for signal in signal_list if signal.evidence.get("finding_rule_matched") is not False]
    return kept or signal_list


def _minutes(start: datetime | None, end: datetime | None) -> float | None:
    return (end - start).total_seconds() / 60 if start and end else None


# ---------------------------------------------------------------------------------------------
# Templates


def _level_change(finding: FindingFacts, signal: SignalFacts, meaning: MetricMeaning, wording: Wording, base: dict[str, Any]) -> Plain | None:
    evidence = signal.evidence
    before = _number(evidence.get("left_mean", evidence.get("first_half_mean")))
    after = _number(evidence.get("right_mean", evidence.get("second_half_mean")))
    percent = _number(evidence.get("percent_change"))
    if before is None or after is None or before == after:
        return None
    direction = 1 if after > before else -1
    if percent is None and before:
        percent = (after - before) / abs(before) * 100
    change_at = _utc(evidence.get("change_point_time"))
    template = wording.templates["level_change"]
    values = {
        **base,
        "rose_or_dropped": "rose" if direction > 0 else "dropped",
        "sharply": " sharply" if percent is not None and abs(percent) >= SHARP_PERCENT else "",
        "higher_or_lower": "higher" if direction > 0 else "lower",
        "before": format_value(before, meaning.unit),
        "after": format_value(after, meaning.unit),
        "change": change_words(before, after, percent),
        "change_time": time_marker(change_at),
        "window_start": time_marker(change_at - CHECK_WINDOW) if change_at else None,
        "window_end": time_marker(change_at + CHECK_WINDOW) if change_at else None,
    }
    badge = _direction_badge(direction, meaning)
    headline, what = _fill(template.get("headline"), values), _fill(template.get("what"), values)
    if not headline or not what:
        return None
    concept = wording.concepts.get(meaning.concept or "") or {}
    return Plain(
        kind="level_change",
        badge=badge,
        headline=headline,
        what=what,
        why=_why(badge, meaning, wording, values),
        check=_fill(template.get("check"), values) or _fill(concept.get("check"), values),
        change_time=time_marker(change_at),
        related_sentence=_fill(template.get("related"), values),
        facts={"before": before, "after": after, "change_at": change_at},
    )


def _trend(finding: FindingFacts, signal: SignalFacts, meaning: MetricMeaning, wording: Wording, base: dict[str, Any]) -> Plain | None:
    evidence, comparison = signal.evidence, finding.comparison
    slope = _number(evidence.get("slope_percent"))
    if slope is None or slope == 0:
        return None
    direction = 1 if slope > 0 else -1
    r_squared = _number(evidence.get("r_squared"))
    first_half, second_half = _number(comparison.get("previous_mean")), _number(comparison.get("current_mean"))
    peaks = [value for value in (_number(comparison.get("previous_max")), _number(comparison.get("current_max"))) if value is not None]
    window = _minutes(_utc(signal.start_time), _utc(signal.end_time)) or _minutes(_utc(finding.event_start), _utc(finding.event_end))
    late_trend = _number(comparison.get("current_trend_percent"))
    template = wording.templates["trend"]
    values = {
        **base,
        "climbing_or_falling": "climbing" if direction > 0 else "falling",
        "steadily_or_unevenly": "steadily" if r_squared is not None and r_squared >= STEADY_R_SQUARED else "unevenly",
        "first_half": format_value(first_half, meaning.unit),
        "second_half": format_value(second_half, meaning.unit),
        "half": duration_words(window / 2) if window else None,
        "change": change_words(first_half, second_half, _number(comparison.get("change_percent"))),
        "peak": format_value(max(peaks), meaning.unit) if peaks else None,
        "down_or_up": "down" if direction > 0 else "up",
    }
    turned = late_trend is not None and late_trend * direction < 0
    headline, what = _fill(template.get("headline"), values), _fill(template.get("what"), values)
    if not headline or not what:
        return None
    badge = _direction_badge(direction, meaning)
    uneven = badge == "worse" and r_squared is not None and r_squared < UNEVEN_R_SQUARED
    concept = wording.concepts.get(meaning.concept or "") or {}
    return Plain(
        kind="trend",
        badge=badge,
        headline=headline,
        what=_join(what, _fill(template.get("turned"), values) if turned else None) or what,
        why=_join(_why(badge, meaning, wording, values), _fill(template.get("not_urgent"), values) if uneven else None),
        check=_fill(concept.get("check"), values),
        facts={"first": first_half, "second": second_half, "half": values["half"]},
    )


def _spike_peak(signal: SignalFacts, comparison: dict[str, Any]) -> tuple[float | None, int]:
    """The burst's furthest value and its side of normal (1 above, -1 below). Newer signals save
    the peak; for older ones it is worked out from how far past the normal range it went."""
    evidence = signal.evidence
    peak = _number(evidence.get("peak_value"))
    normal = evidence.get("normal_range") or {}
    low, high = _number(normal.get("low")), _number(normal.get("high"))
    window_max = max((value for value in (_number(comparison.get("previous_max")), _number(comparison.get("current_max"))) if value is not None), default=None)
    if peak is not None:
        reference = high if high is not None else _number(evidence.get("mean"))
        return peak, (1 if reference is None or peak >= reference else -1)
    if low is not None and high is not None:
        excess = _number(evidence.get("range_excess")) or 0.0
        width = high - low
        above = window_max is None or window_max > high
        return (high + excess * width, 1) if above else (low - excess * width, -1)
    mean, stddev, zscore = _number(evidence.get("mean")), _number(evidence.get("stddev")), _number(evidence.get("max_abs_zscore"))
    if mean is not None and stddev is not None and zscore is not None:
        upper = mean + zscore * stddev
        if window_max is None or window_max >= mean + 0.9 * zscore * stddev:
            return upper, 1
        return mean - zscore * stddev, -1
    return None, 1


def _spikes(finding: FindingFacts, anomalies: list[SignalFacts], meaning: MetricMeaning, wording: Wording, base: dict[str, Any]) -> Plain | None:
    template = wording.templates["spikes"]
    starts = [moment for moment in (_utc(signal.start_time) for signal in anomalies) if moment]
    ends = [moment for moment in (_utc(signal.end_time) for signal in anomalies) if moment]
    first, last = (min(starts) if starts else None), (max(ends) if ends else None)
    ranged = [signal for signal in anomalies if signal.evidence.get("normal_range")]
    lows = [_number((signal.evidence.get("normal_range") or {}).get("low")) for signal in ranged]
    highs = [_number((signal.evidence.get("normal_range") or {}).get("high")) for signal in ranged]
    values = {
        **base,
        "first_time": time_marker(first),
        "last_time": time_marker(last),
        "normal_low": format_value(min((v for v in lows if v is not None), default=None), meaning.unit) if lows else None,
        "normal_high": format_value(max((v for v in highs if v is not None), default=None), meaning.unit) if highs else None,
        "count": sum(int(_number(signal.evidence.get("point_count")) or 1) for signal in anomalies),
    }
    inside = ranged and len(ranged) == len(anomalies) and all((_number(signal.evidence.get("range_excess")) or 0.0) == 0 for signal in anomalies)
    if inside:
        headline, what = _fill(template.get("noise_headline"), values), _fill(template.get("noise_what"), values)
        if not headline or not what:
            return None
        return Plain(kind="spikes", badge="noise", headline=headline, what=what, why=_fill(template.get("noise_why"), values), check=None)

    peaks = [(_spike_peak(signal, finding.comparison), signal) for signal in anomalies]
    peaks = [item for item in peaks if item[0][0] is not None]
    if not peaks:
        return None
    (peak, side), strongest = max(peaks, key=lambda item: abs(_number(item[1].evidence.get("range_excess")) or _number(item[1].evidence.get("max_abs_zscore")) or 0.0))
    single = len(anomalies) == 1
    span = _minutes(first, last)
    values.update(
        {
            "above_or_below": "above" if side > 0 else "below",
            "up_or_down": "up" if side > 0 else "down",
            "times": times_words(len(anomalies)),
            "peak": format_value(peak, meaning.unit),
            "duration": "one reading" if span == 0 else duration_words(span),
            "typical": format_value(strongest.evidence.get("mean"), meaning.unit),
        }
    )
    if single:
        line = template.get("what_once")
    elif values["normal_low"] is not None:
        line = template.get("what")
    else:
        line = template.get("what_typical")
    headline, what = _fill(template.get("headline"), values), _fill(line, values) or _fill(template.get("what_typical"), values)
    if not headline or not what:
        return None
    badge = _direction_badge(side, meaning)
    if single and span is not None and span <= BLIP_MAX.total_seconds() / 60 and badge == "worse":
        badge = "blip"
    concept = wording.concepts.get(meaning.concept or "") or {}
    return Plain(
        kind="spikes",
        badge=badge,
        headline=headline,
        what=what,
        why=_why(badge, meaning, wording, values),
        check=_fill(concept.get("check"), values),
        facts={"peak": peak},
    )


def _odd_stretch(signals: list[SignalFacts], meaning: MetricMeaning, wording: Wording, base: dict[str, Any]) -> Plain | None:
    template = wording.templates["odd_stretch"]
    starts = [moment for moment in (_utc(signal.start_time) for signal in signals) if moment]
    ends = [moment for moment in (_utc(signal.end_time) for signal in signals) if moment]
    values = {**base, "first_time": time_marker(min(starts)) if starts else None, "last_time": time_marker(max(ends)) if ends else None}
    headline, what = _fill(template.get("headline"), values), _fill(template.get("what"), values)
    if not headline or not what:
        return None
    # Which way a stretch went isn't known, so a described metric gets the template's neutral
    # sentence rather than its worse or better one; an undescribed metric says it isn't described.
    concept = wording.concepts.get(meaning.concept or "") or {}
    why = _fill(template.get("why"), values) if meaning.concept else _fill(wording.unknown_meaning, values)
    return Plain(kind="odd_stretch", badge="changed", headline=headline, what=what, why=why, check=_fill(concept.get("check"), values))


def _data_gap(gaps: list[SignalFacts], wording: Wording, base: dict[str, Any]) -> Plain | None:
    template = wording.templates["data_gap"]
    longest = max(gaps, key=lambda signal: _number(signal.evidence.get("gap_minutes")) or _minutes(_utc(signal.start_time), _utc(signal.end_time)) or 0.0)
    evidence = longest.evidence
    minutes = _number(evidence.get("gap_minutes")) or _minutes(_utc(longest.start_time), _utc(longest.end_time))
    missing = _number(evidence.get("missing_points"))
    values = {
        **base,
        "duration": duration_words(minutes),
        "first_time": time_marker(evidence.get("last_seen") or longest.start_time),
        "last_time": time_marker(evidence.get("resumed_at") or longest.end_time),
        "missing_points": f"{missing:,.0f}" if missing is not None else None,
        "gap_count": len(gaps),
    }
    headline, what = _fill(template.get("headline"), values), _fill(template.get("what"), values)
    if not headline or not what:
        return None
    return Plain(
        kind="data_gap",
        badge="gap",
        headline=headline,
        what=_join(what, _fill(template.get("more"), values) if len(gaps) > 1 else None) or what,
        why=_fill(template.get("why"), values),
        check=_fill(template.get("check"), values),
    )


def _flatline(signal: SignalFacts, meaning: MetricMeaning, wording: Wording, base: dict[str, Any]) -> Plain | None:
    template = wording.templates["flatline"]
    evidence = signal.evidence
    ratio = _number(evidence.get("normal_change_ratio"))
    values = {
        **base,
        "stuck_value": format_value(evidence.get("stuck_value"), meaning.unit),
        "duration": duration_words(_number(evidence.get("flatline_minutes")) or _minutes(_utc(signal.start_time), _utc(signal.end_time))),
        "first_time": time_marker(signal.start_time),
        "last_time": time_marker(signal.end_time),
        "normal_change": f"{round(ratio * 100)}%" if ratio is not None else None,
    }
    headline, what = _fill(template.get("headline"), values), _fill(template.get("what"), values)
    if not headline or not what:
        return None
    return Plain(kind="flatline", badge="gap", headline=headline, what=what, why=_fill(template.get("why"), values), check=_fill(template.get("check"), values))


def _forecast(signal: SignalFacts, meaning: MetricMeaning, wording: Wording, base: dict[str, Any]) -> Plain | None:
    template = wording.templates["forecast"]
    evidence = signal.evidence
    actual, expected = _number(evidence.get("actual_value")), _number(evidence.get("forecast_value"))
    error = _number(evidence.get("relative_error"))
    if actual is None or expected is None or actual == expected:
        return None
    direction = 1 if actual > expected else -1
    values = {
        **base,
        "higher_or_lower": "higher" if direction > 0 else "lower",
        "actual": format_value(actual, meaning.unit),
        "expected": format_value(expected, meaning.unit),
        "off": f"{round(abs(error) * 100)}%" if error is not None else None,
    }
    headline, what = _fill(template.get("headline"), values), _fill(template.get("what"), values)
    if not headline or not what:
        return None
    badge = _direction_badge(direction, meaning)
    concept = wording.concepts.get(meaning.concept or "") or {}
    return Plain(
        kind="forecast",
        badge=badge,
        headline=headline,
        what=what,
        why=_why(badge, meaning, wording, values),
        check=_fill(concept.get("check"), values),
        facts={"value": actual},
    )


def build_plain(finding: FindingFacts, signals: Iterable[SignalFacts], wording: Wording | None) -> Plain | None:
    """The plain wording for one finding, picked the way FindingAggregator picks its title, or None."""
    if wording is None:
        return None
    signal_list = _matched(signals)
    if not signal_list:
        return None
    meaning = metric_meaning(finding.metric_name, wording)
    service = finding.service if finding.service and finding.service.lower() != "unknown" else None
    base = {"plain_name": meaning.plain_name, "service": service or "this service", "metric": finding.metric_name}
    types = {signal.signal_type for signal in signal_list}
    try:
        plain = _pick(finding, signal_list, types, meaning, wording, base)
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        # Bad wording or odd evidence must never break a findings page: the card falls back.
        logger.warning("finding_plain: no plain wording for %s (%s)", finding.metric_name, exc)
        return None
    if plain is not None:
        plain.service, plain.metric_name = service, finding.metric_name
        context = wording.services.get((service or "").lower())
        if context is not None:
            plain.service_about, plain.service_importance = context.about, context.importance
            target = context.targets.get(finding.metric_name)
            if target is not None and "targets" in wording.templates:
                plain.target = _target_line(plain, finding, target, meaning, wording)
    return plain


def _target_line(plain: Plain, finding: FindingFacts, target: Target, meaning: MetricMeaning, wording: Wording) -> str | None:
    """How the finding stands against the service's own target, from the same values the card
    shows: averages before and after a change, the two halves of a trend, a spike's peak."""
    lines = wording.templates["targets"]
    facts = plain.facts

    def misses(value: Any) -> bool | None:
        number = _number(value)
        if number is None:
            return None
        return number > target.limit if target.keep == "below" else number < target.limit

    values = {
        "plain_name": meaning.plain_name,
        "service": plain.service or "this service",
        "metric": finding.metric_name,
        "target": format_value(target.limit, meaning.unit),
        "breach_side": "Above" if target.keep == "below" else "Below",
        "half": facts.get("half"),
        "peak": format_value(facts.get("peak"), meaning.unit),
        "value": format_value(facts.get("value"), meaning.unit),
    }
    if plain.kind == "level_change":
        before, after = misses(facts.get("before")), misses(facts.get("after"))
        change_at, end = facts.get("change_at"), _utc(finding.event_end)
        values.update({"since": time_marker(change_at), "until": time_marker(end), "duration": duration_words(_minutes(change_at, end))})
        if before is None or after is None:
            return None
        if after and before:
            return _fill(lines.get("breach_throughout"), values)
        if after:
            if finding.ongoing is True:
                return _fill(lines.get("breach_ongoing"), values) or _fill(lines.get("breach_since"), values)
            if finding.ongoing is False:
                return _fill(lines.get("breach_ended"), values) or _fill(lines.get("breach_since"), values)
            return _fill(lines.get("breach_since"), values)
        return _fill(lines.get("recovered" if before else "within"), values)
    if plain.kind == "trend":
        first, second = misses(facts.get("first")), misses(facts.get("second"))
        if first is None or second is None:
            return None
        if first and second:
            return _fill(lines.get("window_breach"), values)
        if second:
            return _fill(lines.get("trend_breach"), values)
        return _fill(lines.get("trend_recovered" if first else "within"), values)
    if plain.kind == "spikes":
        peak = misses(facts.get("peak"))
        if peak is None:
            return None
        return _fill(lines.get("peak_breach" if peak else "within"), values)
    if plain.kind == "forecast":
        value = misses(facts.get("value"))
        if value is None:
            return None
        return _fill(lines.get("value_breach" if value else "within"), values)
    return None


def _pick(finding: FindingFacts, signal_list: list[SignalFacts], types: set[str], meaning: MetricMeaning, wording: Wording, base: dict[str, Any]) -> Plain | None:
    templates = wording.templates

    def first(signal_type: str) -> SignalFacts | None:
        return next((signal for signal in signal_list if signal.signal_type == signal_type), None)

    if types <= DATA_HEALTH_TYPES:
        gaps = [signal for signal in signal_list if signal.signal_type == "data_gap"]
        if gaps and "data_gap" in templates:
            return _data_gap(gaps, wording, base)
        flat = first("flatline")
        return _flatline(flat, meaning, wording, base) if flat and "flatline" in templates else None
    # The aggregator titles a ruptures change a "persistent baseline shift" only when the series
    # profile backs it; otherwise the finding is about whatever else it saw.
    ruptures = first("ruptures")
    if ruptures and "baseline shift" in finding.title and "level_change" in templates:
        return _level_change(finding, ruptures, meaning, wording, base)
    baseline = first("baseline_shift")
    if baseline and "level_change" in templates:
        return _level_change(finding, baseline, meaning, wording, base)
    anomalies = [signal for signal in signal_list if signal.signal_type in ANOMALY_TYPES]
    if anomalies:
        measured = [signal for signal in anomalies if signal.analyzer_id != "stumpy"]
        if measured and "spikes" in templates:
            return _spikes(finding, measured, meaning, wording, base)
        if not measured and "odd_stretch" in templates:
            return _odd_stretch(anomalies, meaning, wording, base)
        return None
    trend = first("trend")
    if trend and "trend" in templates:
        return _trend(finding, trend, meaning, wording, base)
    forecast = next((signal for signal in signal_list if signal.signal_type in {"forecast", "seasonality", "seasonal"}), None)
    if forecast and "forecast" in templates:
        return _forecast(forecast, meaning, wording, base)
    return None


def _change_moment(plain: Plain) -> datetime | None:
    match = TIME_MARKER.fullmatch(plain.change_time or "")
    return _utc(match.group(1)) if match else None


def link_related(items: list[tuple[int | None, Plain]], candidates: list[tuple[int | None, Plain]] = ()) -> None:
    """A level change mentions the other metrics of the same service that changed within
    RELATED_WINDOW of it: one event, seen by several metrics. `candidates` are findings that may be
    mentioned but aren't being shown. The closest finding per metric is kept."""
    timed = [(finding_id, plain, moment) for finding_id, plain in [*items, *candidates] if plain.kind == "level_change" and (moment := _change_moment(plain))]
    for finding_id, plain in items:
        moment = _change_moment(plain)
        if plain.kind != "level_change" or moment is None or not plain.service:
            continue
        closest: dict[str, tuple[timedelta, int | None, Plain]] = {}
        for other_id, other, other_moment in timed:
            if other is plain or other.service != plain.service or other.metric_name == plain.metric_name or not other.related_sentence:
                continue
            gap = abs(other_moment - moment)
            if gap <= RELATED_WINDOW and (other.metric_name not in closest or gap < closest[other.metric_name][0]):
                closest[str(other.metric_name)] = (gap, other_id, other)
        plain.related = [{"finding_id": other_id, "text": other.related_sentence} for _, other_id, other in sorted(closest.values(), key=lambda item: item[0])]


# ---------------------------------------------------------------------------------------------
# Reading findings from the database


def _signal_facts(db: Session, signal_ids: set[str]) -> dict[str, SignalFacts]:
    facts: dict[str, SignalFacts] = {}
    ordered = sorted(signal_ids)
    for start in range(0, len(ordered), _CHUNK):
        chunk = ordered[start : start + _CHUNK]
        for signal_id, signal_type, analyzer_id, evidence, start_time, end_time in db.execute(
            select(
                SignalEntity.signal_id,
                SignalEntity.signal_type,
                SignalEntity.analyzer_id,
                SignalEntity.evidence_json,
                SignalEntity.start_time,
                SignalEntity.end_time,
            ).where(SignalEntity.signal_id.in_(chunk))
        ).all():
            facts[signal_id] = SignalFacts(signal_type, analyzer_id, evidence or {}, start_time, end_time)
    return facts


def _finding_facts(row: FindingEntity) -> FindingFacts:
    return FindingFacts(row.metric_name, row.service, row.title or "", row.category or "", row.comparison_json or {}, row.event_start, row.event_end, row.ongoing)


def _build_rows(db: Session, rows: Iterable[FindingEntity], wording: Wording) -> list[tuple[FindingEntity, Plain]]:
    row_list = list(rows)
    facts = _signal_facts(db, {signal_id for row in row_list for signal_id in (row.signal_ids or [])})
    built = []
    for row in row_list:
        plain = build_plain(_finding_facts(row), [facts[signal_id] for signal_id in (row.signal_ids or []) if signal_id in facts], wording)
        if plain is not None:
            built.append((row, plain))
    return built


def finding_plain(db: Session, rows: list[FindingEntity], path: Path | None = None) -> dict[int, dict[str, Any]]:
    """Plain wording for each finding that has one, keyed by finding id."""
    wording = load_wording(path)
    if wording is None or not rows:
        return {}
    built = [(row, plain) for row, plain in _build_rows(db, [row for row in rows if row.id is not None], wording)]

    # Level changes of the same services found around the same time, for "Happened with".
    changes = [(row, plain) for row, plain in built if plain.kind == "level_change" and plain.service and row.created_at]
    candidates: list[tuple[int | None, Plain]] = []
    if changes:
        created = [row.created_at for row, _ in changes]
        others = db.execute(
            select(FindingEntity)
            .where(
                FindingEntity.service.in_({plain.service for _, plain in changes}),
                FindingEntity.category == "behavior_change",
                FindingEntity.created_at >= min(created) - RELATED_SEARCH,
                FindingEntity.created_at <= max(created) + RELATED_SEARCH,
                FindingEntity.id.not_in([row.id for row, _ in built]),
            )
            .order_by(FindingEntity.created_at.desc())
            .limit(RELATED_SEARCH_LIMIT)
        ).scalars().all()
        candidates = [(row.id, plain) for row, plain in _build_rows(db, others, wording)]
    link_related([(row.id, plain) for row, plain in built], candidates)
    return {row.id: plain.to_json(wording) for row, plain in built}


def plain_for_result(findings: Iterable[Any], signals: Iterable[Any], path: Path | None = None) -> list[dict[str, Any] | None]:
    """Plain wording for findings that haven't been saved (CSV and Prometheus validation): the
    pipeline's OperationalFinding and OperationalSignal objects, in the same order as `findings`."""
    wording = load_wording(path)
    finding_list = list(findings)
    if wording is None:
        return [None] * len(finding_list)
    by_id = {
        signal.signal_id: SignalFacts(signal.signal_type, signal.analyzer_id, dict(signal.evidence or {}), signal.start_time, signal.end_time)
        for signal in signals
    }
    built: list[Plain | None] = []
    for finding in finding_list:
        facts = FindingFacts(
            finding.metric_name,
            finding.service,
            finding.title or "",
            finding.category or "",
            dict(finding.comparison_json or {}),
            getattr(finding, "event_start", None),
            getattr(finding, "event_end", None),
            getattr(finding, "ongoing", None),
        )
        built.append(build_plain(facts, [by_id[signal_id] for signal_id in finding.signal_ids if signal_id in by_id], wording))
    link_related([(None, plain) for plain in built if plain is not None])
    return [plain.to_json(wording) if plain else None for plain in built]
