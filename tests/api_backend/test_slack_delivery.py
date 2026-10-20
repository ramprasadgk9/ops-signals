"""QA-12: a finding message Slack didn't take was logged and dropped - no retry, no record - and a
later run of the same problem counted it as reported, so the alert never arrived."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import Integer, select

from backend.app.config import SlackConfig
from backend.app.models.db import get_session_local
from backend.app.models.entities import SlackNotificationEntity
from backend.app.notifications.slack_client import MAX_ATTEMPTS, RETRY_DELAYS, SlackNotifier
from intelligence.findings.schema import OperationalFinding
from intelligence.storage.postgres_store import PostgresStore, register_findings_hook

START = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


class FlakySlack:
    """Stands in for the webhook: fails while `down`, records what arrived."""

    def __init__(self) -> None:
        self.down = False
        self.received: list[dict] = []

    def __call__(self, payload: dict) -> None:
        if self.down:
            raise RuntimeError("Slack webhook returned HTTP 500")
        self.received.append(payload)


@pytest.fixture()
def slack(db_session) -> Iterator[tuple[SlackNotifier, FlakySlack]]:
    notifier = SlackNotifier(SlackConfig(enabled=True, webhook_url="http://slack.invalid/hook", minimum_importance=0.5), get_session_local())
    webhook = FlakySlack()
    notifier._post = webhook
    yield notifier, webhook


@pytest.fixture()
def store(slack) -> Iterator[PostgresStore]:
    notifier, _ = slack
    config = SimpleNamespace(storage=SimpleNamespace(postgres=SimpleNamespace(table_prefix="ops_")))
    with (
        patch.object(PostgresStore, "_connection_string", return_value="sqlite:///:memory:"),
        patch("intelligence.storage.postgres_store.BIGINT", Integer),
    ):
        instance = PostgresStore(config)
    instance.init_db()
    register_findings_hook(notifier.notify_findings, on_seen_again=notifier.notify_seen_again)
    yield instance
    register_findings_hook(None)
    instance.engine.dispose()


def _finding(**overrides) -> OperationalFinding:
    payload = {
        "service": "checkout",
        "metric_name": "cpu_usage",
        "title": "cpu_usage moved to a new baseline.",
        "summary": "CPU stepped up.",
        "category": "behavior_change",
        "health_status": "significant",
        "importance_score": 0.8,
        "event_start": START,
        "event_end": START + timedelta(minutes=30),
    }
    payload.update(overrides)
    return OperationalFinding(**payload)


def _rows() -> list[SlackNotificationEntity]:
    with get_session_local()() as db:
        rows = db.scalars(select(SlackNotificationEntity).order_by(SlackNotificationEntity.id)).all()
        for row in rows:
            db.expunge(row)
        return rows


def _retry_until_done(notifier: SlackNotifier) -> None:
    moment = datetime.utcnow()
    for delay in RETRY_DELAYS:
        moment += delay + timedelta(seconds=1)
        notifier.deliver_due(now=moment)


def test_a_message_slack_refused_is_kept_and_retried_until_it_arrives(slack) -> None:
    notifier, webhook = slack
    webhook.down = True

    notifier.notify_findings([_finding(id=1)])

    [row] = _rows()
    assert (row.status, row.attempts) == ("pending", 1)
    assert "HTTP 500" in row.last_error
    assert webhook.received == []

    assert notifier.deliver_due(now=datetime.utcnow()) == 0  # not due yet
    webhook.down = False
    assert notifier.deliver_due(now=datetime.utcnow() + RETRY_DELAYS[0] + timedelta(seconds=1)) == 1

    [row] = _rows()
    assert (row.status, row.attempts, row.last_error) == ("delivered", 2, None)
    assert len(webhook.received) == 1


def test_it_gives_up_after_the_last_retry_and_says_so(slack) -> None:
    notifier, webhook = slack
    webhook.down = True

    notifier.notify_findings([_finding(id=1)])
    _retry_until_done(notifier)

    [row] = _rows()
    assert (row.status, row.attempts) == ("failed", MAX_ATTEMPTS)
    assert notifier.deliver_due(now=datetime.utcnow() + timedelta(days=1)) == 0


def test_a_problem_whose_message_failed_is_sent_when_it_is_seen_again(store, slack) -> None:
    notifier, webhook = slack
    webhook.down = True
    store.save_findings([_finding()])
    _retry_until_done(notifier)
    assert [row.status for row in _rows()] == ["failed"]

    webhook.down = False
    store.save_findings([_finding(event_start=START + timedelta(minutes=20), event_end=START + timedelta(minutes=50))])

    assert len(webhook.received) == 1
    assert [row.status for row in _rows()] == ["failed", "delivered"]


def test_a_delivered_problem_is_not_sent_again(store, slack) -> None:
    _, webhook = slack
    store.save_findings([_finding()])
    store.save_findings([_finding(event_start=START + timedelta(minutes=20), event_end=START + timedelta(minutes=50))])

    assert len(webhook.received) == 1


def test_a_problem_still_retrying_is_not_sent_twice(store, slack) -> None:
    _, webhook = slack
    webhook.down = True
    store.save_findings([_finding()])
    webhook.down = False
    store.save_findings([_finding(event_start=START + timedelta(minutes=20), event_end=START + timedelta(minutes=50))])

    assert webhook.received == []
    assert [row.status for row in _rows()] == ["pending"]


def test_a_repeat_of_a_problem_never_sent_stays_quiet(slack) -> None:
    # Below the importance threshold the first time, so never sent: unchanged behavior.
    notifier, webhook = slack
    notifier.notify_seen_again([_finding(id=2, problem_id=1)])

    assert webhook.received == []
    assert _rows() == []


def test_status_endpoint_reports_delivery(client, slack) -> None:
    notifier, webhook = slack
    with patch("backend.app.api.notifications.get_slack_config", return_value=notifier.config):
        notifier.notify_findings([_finding(id=1, title="delivered one")])
        webhook.down = True
        notifier.notify_findings([_finding(id=2, title="checkout CPU")])
        status = client.get("/api/notifications/slack").json()

    assert status["enabled"] is True
    assert (status["delivered_last_24h"], status["retrying"], status["failed_last_24h"]) == (1, 1, 0)
    assert status["last_failure"]["title"] == "checkout CPU"
    assert "HTTP 500" in status["last_failure"]["error"]
    assert status["last_failure"]["next_retry_at"] is not None


# QA-35: a CSV upload waited for the Slack timeout (10 s with a hung webhook) before answering.


class HungSlack:
    """Stands in for a webhook that doesn't answer until released."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.received: list[dict] = []

    def __call__(self, payload: dict) -> None:
        self.release.wait(5)
        self.received.append(payload)


@pytest.fixture()
def background_slack(db_session) -> Iterator[tuple[SlackNotifier, HungSlack]]:
    notifier = SlackNotifier(
        SlackConfig(enabled=True, webhook_url="http://slack.invalid/hook", minimum_importance=0.5), get_session_local(), background=True
    )
    webhook = HungSlack()
    notifier._post = webhook
    yield notifier, webhook
    webhook.release.set()
    notifier.close()


def test_a_hung_webhook_does_not_hold_up_the_caller(background_slack) -> None:
    notifier, webhook = background_slack

    started = time.monotonic()
    notifier.notify_findings([_finding(id=1)])

    assert time.monotonic() - started < 1
    [row] = _rows()
    assert row.status == "pending"  # kept in the outbox before the caller returns

    webhook.release.set()
    notifier.close()

    [row] = _rows()
    assert (row.status, row.attempts) == ("delivered", 1)
    assert len(webhook.received) == 1


def test_a_background_send_slack_refused_is_retried_like_any_other(background_slack) -> None:
    notifier, webhook = background_slack
    webhook.release.set()
    notifier._post = FlakySlack()
    notifier._post.down = True

    notifier.notify_findings([_finding(id=1)])
    notifier.close()

    [row] = _rows()
    assert (row.status, row.attempts) == ("pending", 1)
    assert "HTTP 500" in row.last_error


def test_without_the_outbox_a_background_send_still_happens_once(background_slack, monkeypatch) -> None:
    notifier, webhook = background_slack

    def outbox_down(_findings):
        raise RuntimeError("database is down")

    monkeypatch.setattr(notifier, "_enqueue_and_send", outbox_down)
    started = time.monotonic()
    notifier.notify_findings([_finding(id=1)])

    assert time.monotonic() - started < 1
    webhook.release.set()
    notifier.close()
    assert len(webhook.received) == 1


def test_a_saved_finding_is_posted_in_plain_words(slack) -> None:
    import json
    from pathlib import Path

    from backend.app.models.entities import FindingEntity, SignalEntity

    notifier, webhook = slack
    item = next(entry for entry in json.loads((Path(__file__).parents[1] / "fixtures" / "plain_findings_real.json").read_text(encoding="utf-8")) if entry["id"] == 8300)
    with get_session_local()() as db:
        for signal in item["signals"]:
            db.add(SignalEntity(signal_id=signal["signal_id"], signal_type=signal["signal_type"], analyzer_id=signal["analyzer_id"], metric_name=item["metric_name"],
                                service=item["service"], start_time=datetime.fromisoformat(signal["start_time"]), end_time=datetime.fromisoformat(signal["end_time"]),
                                evidence_json=signal["evidence"], importance_score=0.7))
        db.add(FindingEntity(id=8300, service=item["service"], metric_name=item["metric_name"], title=item["title"], summary=item["summary"], category=item["category"],
                             health_status="significant", importance_score=0.8, investigation_priority=2, signal_ids=[s["signal_id"] for s in item["signals"]],
                             comparison_json=item["comparison_json"]))
        db.commit()

    notifier.notify_findings([_finding(id=8300, service=item["service"], metric_name=item["metric_name"], title=item["title"], summary=item["summary"])])

    [payload] = webhook.received
    assert payload["blocks"][0]["text"]["text"] == "🟢 Better: Error rate dropped sharply and stayed lower"
    assert "Since then about 1.2% (down 89%)." in payload["blocks"][1]["text"]["text"]
    [row] = _rows()
    assert row.title == item["title"]
