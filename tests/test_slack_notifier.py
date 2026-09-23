"""Unit tests for SlackNotifier's enable/disable, importance filtering, and best-effort
error handling. The private _post method is swapped for a fake, the same duck-typed
injection idiom used for PrometheusQueryService._get_json elsewhere in this test suite -
no real HTTP call is ever made here."""

from __future__ import annotations

import pytest

from backend.app.config import SlackConfig
from backend.app.notifications.slack_client import SlackNotifier
from intelligence.findings.schema import OperationalFinding


def _finding(**overrides) -> OperationalFinding:
    payload = {
        "service": "payments-api",
        "metric_name": "cpu_usage",
        "title": "CPU spike on payments-api",
        "summary": "Sustained elevated utilization.",
        "category": "anomaly",
        "health_status": "critical",
        "importance_score": 0.93,
    }
    payload.update(overrides)
    return OperationalFinding(**payload)


def _notifier(**config_overrides) -> tuple[SlackNotifier, list[dict]]:
    config = SlackConfig(enabled=True, webhook_url="http://fake.example/webhook", **config_overrides)
    notifier = SlackNotifier(config)
    sent: list[dict] = []
    notifier._post = sent.append
    return notifier, sent


def test_disabled_config_sends_nothing() -> None:
    notifier = SlackNotifier(SlackConfig(enabled=False, webhook_url="http://fake.example/webhook"))
    sent: list[dict] = []
    notifier._post = sent.append

    notifier.notify_findings([_finding()])

    assert sent == []


def test_enabled_without_webhook_url_sends_nothing() -> None:
    notifier = SlackNotifier(SlackConfig(enabled=True, webhook_url=None))
    sent: list[dict] = []
    notifier._post = sent.append

    notifier.notify_findings([_finding()])

    assert sent == []


def test_enabled_finding_above_threshold_is_posted() -> None:
    notifier, sent = _notifier(minimum_importance=0.7)

    notifier.notify_findings([_finding(importance_score=0.93)])

    assert len(sent) == 1
    assert sent[0]["blocks"][0]["text"]["text"] == "🔴 CPU spike on payments-api"


def test_finding_below_threshold_is_skipped() -> None:
    notifier, sent = _notifier(minimum_importance=0.7)

    notifier.notify_findings([_finding(importance_score=0.3)])

    assert sent == []


def test_only_findings_above_threshold_are_posted_from_a_mixed_batch() -> None:
    notifier, sent = _notifier(minimum_importance=0.7)

    notifier.notify_findings(
        [
            _finding(title="low", importance_score=0.2),
            _finding(title="high", importance_score=0.9),
        ]
    )

    assert len(sent) == 1
    assert sent[0]["blocks"][0]["text"]["text"] == "🔴 high"


def test_a_failed_post_is_swallowed_and_does_not_stop_remaining_findings() -> None:
    config = SlackConfig(enabled=True, webhook_url="http://fake.example/webhook", minimum_importance=0.0)
    notifier = SlackNotifier(config)
    sent: list[dict] = []
    calls = {"count": 0}

    def _flaky_post(payload: dict) -> None:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("Slack webhook unreachable")
        sent.append(payload)

    notifier._post = _flaky_post

    notifier.notify_findings([_finding(title="fails"), _finding(title="succeeds")])

    assert len(sent) == 1
    assert sent[0]["blocks"][0]["text"]["text"] == "🔴 succeeds"
