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
