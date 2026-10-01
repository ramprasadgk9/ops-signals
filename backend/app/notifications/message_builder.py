from __future__ import annotations

from intelligence.findings.schema import OperationalFinding

_SEVERITY_ICON = {
    "critical": "🔴",
    "significant": "🟡",
    "normal": "🟢",
}

# Slack's header block rejects text over 150 characters.
_HEADER_MAX_LEN = 150


def build_finding_blocks(finding: OperationalFinding) -> dict:
    icon = _SEVERITY_ICON.get(finding.health_status, "⚪")
    header_text = f"{icon} {finding.title}"[:_HEADER_MAX_LEN]

    return {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": header_text, "emoji": True},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": finding.summary or "No summary available."},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Service:*\n{finding.service or 'unknown'}"},
                    {"type": "mrkdwn", "text": f"*Metric:*\n{finding.metric_name}"},
                    {"type": "mrkdwn", "text": f"*Category:*\n{finding.category}"},
                    {"type": "mrkdwn", "text": f"*Importance:*\n{finding.importance_score:.2f}"},
                ],
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "Posted by Ops Signals"}],
            },
        ],
    }


# --- Alert enrichment (docs/design/alert-enrichment-plan.md §H) -------------------------------------
# Built from the stored enrichment dict (ops_alert_enrichments.enrichment_json), so what's posted
# and what's stored can never disagree, and a stored enrichment can be re-rendered later.

_SOURCE_LABEL = {
    "alertmanager": "Alertmanager alert",
    "generic": "External alert",
}
_VERDICT_TEXT = {
    "likely_real": "likely real",
    "likely_noise": "likely noise",
    "insufficient_history": "not enough history",
}
_SECTION_MAX_LEN = 2900  # Slack section text limit is 3000


def _clip(text: str, limit: int = _SECTION_MAX_LEN) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _link(url: str | None, label: str) -> str:
    return f"<{url}|{label}>" if url else label


def _hhmm(iso_value: str | None) -> str:
    return iso_value[11:16] + " UTC" if iso_value and len(iso_value) >= 16 else "unknown time"


def _minutes(value: float) -> str:
    minutes = round(abs(value))
    if minutes < 1:
        return "<1 min"
    if minutes < 120:
        return f"{minutes} min"
    return f"{minutes / 60:.1f} h"


# --- Pod breakdown: the same wording as the UI (frontend/src/utils/findingBreakdown.ts) -------------


def _plural(label: str, count: int) -> str:
    return label if count == 1 else f"{label}s"


def _format_value(value: float | None) -> str:
    if value is None:
        return "–"
    magnitude = abs(value)
    if magnitude == 0:
        return "0"
    if magnitude >= 100:
        return f"{value:.0f}"
    if magnitude >= 1:
        return f"{value:.2f}"
    return f"{value:.2g}"


def _breakdown_sentence(breakdown: dict) -> str:
    label = breakdown.get("label") or "pod"
    total = breakdown.get("parts_total") or 0
    moved = [part for part in breakdown.get("top") or [] if part.get("moved")]
    changed = breakdown.get("parts_changed") or len(moved)
    verb = "fell" if breakdown.get("direction") == "down" else "rose"
    change_word = "decrease" if breakdown.get("direction") == "down" else "increase"
    names = ", ".join(str(part.get("value")) for part in moved)

    if breakdown.get("spread") == "widespread":
        who = f"All {total} {_plural(label, total)}" if changed == total else f"{changed} of {total} {_plural(label, total)}"
        return f"{who} {verb} by a similar amount."
    if breakdown.get("mode") == "share":
        share = f"{round(sum(part.get('share') or 0.0 for part in moved) * 100)}%"
        if breakdown.get("spread") == "concentrated" and moved:
            is_new = f" (a new {label})" if moved[0].get("new") else ""
            return f"{share} of the {change_word} comes from {label} {moved[0].get('value')}{is_new}, 1 of {total} {_plural(label, total)}."
        return f"{share} of the {change_word} comes from {changed} of {total} {_plural(label, total)}: {names}."
    if breakdown.get("spread") == "concentrated" and moved:
        part = moved[0]
        before = f"other {_plural(label, 2)}’ normal level" if part.get("new") else _format_value(part.get("before"))
        others = total - 1
        return (
            f"Only {label} {part.get('value')} {verb} ({before} → {_format_value(part.get('after'))}). "
            f"The other {others} {_plural(label, others)} are unchanged."
        )
    return f"{changed} of {total} {_plural(label, total)} {verb}: {names}."


def _breakdown_next_step(breakdown: dict) -> str:
    label = breakdown.get("label") or "pod"
    moved = [part for part in breakdown.get("top") or [] if part.get("moved")]
    if breakdown.get("spread") == "widespread":
        return f"Not a single bad {label}. Look at recent code or config changes, or a shared dependency (database, downstream API)."
    if moved and all(part.get("new") for part in moved):
        return (
            f"These {_plural(label, len(moved))} first appeared after the change started, which looks like a rollout "
            "in progress. Compare the new version with the old one before it finishes."
        )
    if breakdown.get("spread") == "concentrated" and moved:
        return f"Check {label} {moved[0].get('value')} and the node it runs on. The other {_plural(label, 2)} look normal, so a rollback is probably not needed."
    return f"Check what these {_plural(label, len(moved))} have in common, such as node, zone or version."


def _where(breakdown: dict | None) -> str | None:
    if not breakdown or breakdown.get("status") != "ok" or not breakdown.get("parts_total"):
        return None
    return f"📍 *Where:* {_breakdown_sentence(breakdown)}\n_{_breakdown_next_step(breakdown)}_"


def _what_happened(analysis: dict) -> str:
    status = analysis.get("status")
    finding = analysis.get("finding") or {}
    lookback_hours = round((analysis.get("lookback_seconds") or 0) / 3600, 1)
    if status in {"analyzed", "reused"} and finding:
        lines = [f"*{finding.get('title', 'Finding')}*", finding.get("summary") or ""]
        if analysis.get("change_point_time"):
            lines.append(f"Change started around *{_hhmm(analysis['change_point_time'])}*.")
        where = _where(finding.get("breakdown"))
        if where:
            lines.append(where)
        if status == "reused" and analysis.get("detected_before_alert_minutes"):
            lines.append(
                f"🔎 Ops Signals detected this *{_minutes(analysis['detected_before_alert_minutes'])} before* the alert fired."
            )
        if analysis.get("early"):
            lines.append(
                f"_Early analysis: only {analysis.get('post_change_points', 0)} data points since the alert started._"
            )
        return "\n".join(line for line in lines if line)
    if status == "no_significant_change":
        return f"No significant change detected in the last {lookback_hours:g}h of this series."
    if status in {"skipped", "failed"}:
        return f"Not analyzed: {analysis.get('reason_text') or analysis.get('reason') or 'unknown reason'}."
    return "Not analyzed."


_ANALYZER_LABEL = {
    "baseline_shift": "baseline shift",
    "ruptures": "change-point detection",
    "anomaly_zscore": "z-score",
    "pyod_outlier": "outlier detection",
    "stumpy": "pattern matching",
}


def _change_label(match: dict) -> str:
    label = f"{match.get('event_type', 'change')} `{match.get('version') or match.get('description') or 'unversioned'}`"
    who = f" by {match['author']}" if match.get("author") else ""
    return f"{_link(match.get('url'), label)}{who}"


def _what_changed(changes: dict | None, service: str | None, timing: dict | None = None) -> str:
    """Wording follows where the start time came from (backend/app/alerts/timing.py): only a step
    change or a spike gives a real start, so only those get "started N min after"."""
    if not service:
        return "No service label on this alert, so change events can't be matched."
    if changes is None:
        return "Change-event lookup unavailable."
    if not changes.get("service_has_any_events"):
        return f"No change events have ever been recorded for `{service}` - send deploys to `POST /api/events` to see them here."
    timing = timing or {}
    basis = timing.get("basis") or "alert_time"
    matches = changes.get("matches") or []
    window = changes.get("window_before_minutes", 30)
    trend = timing.get("trend_direction")

    if basis in {"step_change", "spike"}:
        kind = "step change" if basis == "step_change" else "spike"
        source = _ANALYZER_LABEL.get(timing.get("analyzer_id"), timing.get("analyzer_id") or "analysis")
        note = f"_Start time {_hhmm(timing.get('time'))}, from a {kind} ({source})."
        # Only a spike sits "on" a trend. A step change makes the trend analyzer fire too (a line
        # fitted across a jump has a slope), so for a step the trend is the same change, not context.
        if trend and basis == "spike":
            note += f" It sits on a gradual {trend} trend, which these changes may not explain."
        note += "_"
        if not matches:
            return f"No changes recorded for `{service}` in the {window} min before the {kind} at {_hhmm(timing.get('time'))}.\n{note}"
        verb = "Started" if basis == "step_change" else "Spike started"
        lines = []
        for match in matches:
            # minutes_before_anchor > 0: the change event came first, so the problem started *after* it.
            when = match.get("minutes_before_anchor", 0.0)
            relation = f"{_minutes(when)} after" if when >= 0 else f"{_minutes(when)} before"
            lines.append(f"• {verb} *{relation}* {_change_label(match)}")
        return "\n".join([*lines, note])

    # No real start time: list changes relative to when the alert fired, and claim nothing.
    if basis == "trend":
        intro = f"Gradual {trend} trend with no clear start time."
    else:
        intro = "No start time found in the metric."
    if not matches:
        return f"{intro} No changes recorded for `{service}` in the {window} min before the alert fired."
    lines = [f"{intro} Changes near when the alert fired, for reference:"]
    for match in matches:
        when = match.get("minutes_before_anchor", 0.0)
        relation = f"{_minutes(when)} before" if when >= 0 else f"{_minutes(when)} after"
        lines.append(f"• {_change_label(match)}, {relation} the alert fired")
    if basis == "trend":
        lines.append("_A slow trend is rarely explained by a single change._")
    return "\n".join(lines)


def _seen_before(context: dict | None, ui_base_url: str) -> str:
    if not context:
        return "History lookup unavailable."
    history = context.get("history") or {}
    total = history.get("total_prior_occurrences") or 0
    verdict = _VERDICT_TEXT.get(context.get("recommendation"), context.get("recommendation") or "unknown")
    lines = [f"Verdict: *{verdict}*"]
    if total:
        lines.append(
            f"{total} prior occurrence(s): {history.get('confirmed', 0)} confirmed, {history.get('rejected', 0)} rejected."
        )
        if history.get("most_common_root_cause"):
            lines.append(f"Most common cause: _{history['most_common_root_cause']}_")
    similar = context.get("similar_cases") or []
    if similar:
        top = similar[0]
        title = _link(f"{ui_base_url}/cases/{top['case_id']}", f"#{top['case_id']} {top.get('title', '')}".strip())
        lines.append(f"Most similar case: {title} ({round(top.get('similarity_score', 0) * 100)}% match)")
        if top.get("outcome_summary"):
            lines.append(f"↳ Fix: {top['outcome_summary']}")
    raw = context.get("raw_activity") or {}
    if not total and not similar:
        if raw.get("total_occurrences"):
            lines.append(f"Seen {raw['total_occurrences']} time(s) in past findings, but no case was ever filed.")
        else:
            lines.append("First time Ops Signals has seen this alert.")
    return "\n".join(lines)


def build_alert_enrichment_blocks(enrichment: dict, ui_base_url: str) -> dict:
    alert = enrichment.get("alert") or {}
    source_label = _SOURCE_LABEL.get(enrichment.get("source"), "External alert")
    analysis = enrichment.get("analysis") or {}
    finding = analysis.get("finding") or {}
    icon = _SEVERITY_ICON.get(finding.get("health_status"), "🔔")
    service = alert.get("service")
    header_text = f"{icon} [FIRING] {alert.get('name', 'alert')}" + (f" · {service}" if service else "")

    origin_parts = [f"🔔 *{source_label}*", f"rule `{alert.get('name', 'alert')}`"]
    if alert.get("severity"):
        origin_parts.append(f"severity: {alert['severity']}")
    origin_parts.append(f"fired {_hhmm(alert.get('starts_at'))}")
    source_links = [
        _link(alert.get("generator_url"), "view rule source") if alert.get("generator_url") else None,
        _link(alert.get("external_url"), "Alertmanager") if alert.get("external_url") else None,
    ]
    origin = " · ".join(origin_parts + [link for link in source_links if link])

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": header_text[:_HEADER_MAX_LEN], "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": _clip(origin, 2900)}]},
        {"type": "section", "text": {"type": "mrkdwn", "text": _clip(f"*Alert:* {alert.get('summary') or alert.get('name')}")}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": _clip("*📈 What happened*\n" + _what_happened(analysis))}},
        {"type": "section", "text": {"type": "mrkdwn", "text": _clip("*🚀 What changed*\n" + _what_changed(enrichment.get("changes"), service, analysis.get("timing")))}},
        {"type": "section", "text": {"type": "mrkdwn", "text": _clip("*🧠 Seen before*\n" + _seen_before(enrichment.get("context"), ui_base_url))}},
    ]
    links = [_link(f"{ui_base_url}/findings", "Open findings"), _link(f"{ui_base_url}/cases", "Create a case")]
    fingerprint = alert.get("fingerprint")
    footer = (
        f"Enriched by Ops Signals from an {source_label.lower()}"
        + (f" · fingerprint `{fingerprint}`" if fingerprint else "")
        + (f" · metric `{alert['metric_key']}`" if alert.get("metric_key") else "")
        + " · " + " · ".join(links)
    )
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": _clip(footer, 2900)}]})
    return {"text": header_text[:_HEADER_MAX_LEN], "blocks": blocks}


def build_alert_resolved_blocks(enrichment: dict, ui_base_url: str, open_minutes: float | None) -> dict:
    alert = enrichment.get("alert") or {}
    source_label = _SOURCE_LABEL.get(enrichment.get("source"), "External alert")
    service = alert.get("service")
    header_text = f"✅ [RESOLVED] {alert.get('name', 'alert')}" + (f" · {service}" if service else "")
    duration = f" after {_minutes(open_minutes)}" if open_minutes is not None else ""
    body = (
        f"🔔 *{source_label}* `{alert.get('name', 'alert')}` resolved{duration}.\n"
        f"Was it real? Record the outcome on a {_link(f'{ui_base_url}/cases', 'case')} so the next alert knows."
    )
    fingerprint = alert.get("fingerprint")
    footer = f"Enriched by Ops Signals from an {source_label.lower()}" + (f" · fingerprint `{fingerprint}`" if fingerprint else "")
    return {
        "text": header_text[:_HEADER_MAX_LEN],
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": header_text[:_HEADER_MAX_LEN], "emoji": True}},
            {"type": "section", "text": {"type": "mrkdwn", "text": body}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": footer}]},
        ],
    }
