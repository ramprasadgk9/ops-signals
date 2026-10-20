"""Unit tests for Slack Block Kit payload construction - no HTTP or DB involved, see
tests/test_slack_notifier.py for delivery/filtering behavior."""

from __future__ import annotations

from intelligence.findings.schema import OperationalFinding
from backend.app.notifications.message_builder import build_finding_blocks


def _finding(**overrides) -> OperationalFinding:
    payload = {
        "service": "payments-api",
        "metric_name": "cpu_usage",
        "title": "CPU spike on payments-api",
        "summary": "The current window is materially above the previous baseline.",
        "category": "anomaly",
        "health_status": "critical",
        "importance_score": 0.93,
    }
    payload.update(overrides)
    return OperationalFinding(**payload)


def test_header_includes_severity_icon_and_title() -> None:
    blocks = build_finding_blocks(_finding())["blocks"]

    header = blocks[0]
    assert header["type"] == "header"
    assert header["text"]["text"] == "🔴 CPU spike on payments-api"


def test_summary_section_carries_the_finding_summary() -> None:
    blocks = build_finding_blocks(_finding())["blocks"]

    summary = blocks[1]
    assert summary["text"]["text"] == "The current window is materially above the previous baseline."


def test_fields_section_includes_service_metric_category_importance() -> None:
    blocks = build_finding_blocks(_finding())["blocks"]

    fields = {f["text"] for f in blocks[2]["fields"]}
    assert "*Service:*\npayments-api" in fields
    assert "*Metric:*\ncpu_usage" in fields
    assert "*Category:*\nanomaly" in fields
    assert "*Importance:*\n0.93" in fields


def test_unknown_health_status_falls_back_to_a_neutral_icon() -> None:
    blocks = build_finding_blocks(_finding(health_status="something_new"))["blocks"]

    assert blocks[0]["text"]["text"].startswith("⚪")


def test_missing_service_falls_back_to_unknown() -> None:
    blocks = build_finding_blocks(_finding(service=None))["blocks"]

    fields = {f["text"] for f in blocks[2]["fields"]}
    assert "*Service:*\nunknown" in fields


def test_missing_summary_falls_back_to_placeholder_text() -> None:
    blocks = build_finding_blocks(_finding(summary=""))["blocks"]

    assert blocks[1]["text"]["text"] == "No summary available."


def test_long_title_is_truncated_to_slack_header_limit() -> None:
    blocks = build_finding_blocks(_finding(title="x" * 200))["blocks"]

    assert len(blocks[0]["text"]["text"]) == 150


def test_seen_before_names_an_imported_incident_with_its_cause_and_fix() -> None:
    from backend.app.notifications.message_builder import _seen_before

    context = {
        "recommendation": "insufficient_history",
        "history": {"total_prior_occurrences": 0},
        "similar_cases": [
            {
                "case_id": 25, "title": "Checkout CPU pinned at 95% after release 4.2", "similarity_score": 0.58,
                "origin": "imported", "source": "jira", "source_id": "OPS-101",
                "root_cause_summary": "Schema validation re-parsed the cart on every call",
                "corrective_action": "Cached the compiled schema", "outcome_summary": None,
            }
        ],
    }

    text = _seen_before(context, "http://ui")

    assert "Verdict: *seen before, no verdict yet*" in text
    assert "(58% match, imported from jira OPS-101)" in text
    assert "↳ Cause: Schema validation re-parsed the cart on every call" in text
    assert "↳ Fix: Cached the compiled schema" in text


def test_seen_before_keeps_not_enough_history_when_nothing_matched() -> None:
    from backend.app.notifications.message_builder import _seen_before

    text = _seen_before({"recommendation": "insufficient_history", "history": {}, "similar_cases": []}, "http://ui")

    assert "Verdict: *not enough history*" in text
    assert "First time Ops Signals has seen this alert." in text


PLAIN = {
    "kind": "level_change",
    "badge": "better",
    "badge_label": "Better",
    "headline": "Error rate dropped sharply and stayed lower",
    "what": "About 11.3% until [[time:2026-10-19T22:54:17Z]]. Since then about 1.2% (down 89%).",
    "why": "Fewer requests fail, so fewer users see errors.",
    "check": "Deploys or config changes in spike-lab between [[time:2026-10-19T22:24:17Z]] and [[time:2026-10-19T23:24:17Z]].",
    "related": [{"finding_id": 8299, "text": "Slow-request time (p95) also dropped at [[time:2026-10-19T22:54:17Z]] (571 ms to 357 ms)."}],
}


def test_plain_wording_leads_the_message_with_the_stored_summary_as_small_print() -> None:
    finding = _finding(title="error_rate experienced a persistent baseline shift during the selected time window.", summary="A structural change was detected around sample 30.")
    blocks = build_finding_blocks(finding, PLAIN)["blocks"]

    assert blocks[0]["text"]["text"] == "🟢 Better: Error rate dropped sharply and stayed lower"
    body = blocks[1]["text"]["text"]
    # Slack shows these in each reader's time zone; the fallback is for clients that can't.
    assert body.startswith("About 11.3% until <!date^1792450457^{date_short_pretty} {time}|Oct 19, 22:54 UTC>. Since then about 1.2% (down 89%).")
    assert "*Why it matters:* Fewer requests fail, so fewer users see errors." in body
    assert "*Happened with:* Slow-request time (p95) also dropped at <!date^1792450457^" in body
    assert "*What to check:* Deploys or config changes in spike-lab between <!date^1792448657^" in body
    assert "[[time:" not in body
    technical = blocks[3]
    assert technical["type"] == "context"
    assert technical["elements"][0]["text"] == f"Technical: {finding.title} {finding.summary}"
    assert blocks[-1]["elements"][0]["text"] == "Posted by Ops Signals"


def test_without_plain_wording_the_message_is_unchanged() -> None:
    assert build_finding_blocks(_finding(), None) == build_finding_blocks(_finding())
