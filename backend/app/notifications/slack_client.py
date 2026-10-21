from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import SlackConfig
from backend.app.models.entities import FindingEntity, SlackNotificationEntity
from backend.app.notifications.message_builder import build_finding_blocks
from backend.app.services.finding_plain import finding_plain
from intelligence.findings.schema import OperationalFinding

logger = logging.getLogger(__name__)

# Waits before each retry of a message Slack didn't take. The first try is immediate; after the
# last retry (about 18 minutes in) the message is marked failed.
RETRY_DELAYS = (timedelta(seconds=30), timedelta(minutes=1), timedelta(minutes=2), timedelta(minutes=5), timedelta(minutes=10))
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1
RETRY_BATCH_SIZE = 10

PENDING = "pending"
DELIVERED = "delivered"
FAILED = "failed"


class SlackNotifier:
    """Posts findings to a Slack incoming webhook.

    Best-effort for the pipeline: a failure notifying Slack is never raised, so a broken or
    unconfigured webhook can never fail the analysis it's attached to. With a session factory,
    every message is written to ops_slack_notifications first and sent at once; one Slack didn't
    take stays pending and deliver_due() retries it (RETRY_DELAYS) until it arrives or is marked
    failed. Only a delivered message counts as reported: a problem whose message failed is
    notified again when a later run sees it (notify_seen_again). Without a session factory it
    sends once, as before.

    With background=True (the app) the first try runs on a worker thread, so the request that
    produced the findings doesn't wait for Slack: a hung webhook held a CSV upload for the whole
    Slack timeout (QA-35). The message is in the outbox before the caller returns either way.
    """

    def __init__(self, config: SlackConfig, session_factory: Callable[[], Session] | None = None, *, background: bool = False):
        self.config = config
        self.session_factory = session_factory
        self.background = background
        self._executor: ThreadPoolExecutor | None = None
        self._executor_lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.config.enabled and self.config.webhook_url)

    def _eligible(self, findings: list[OperationalFinding]) -> list[OperationalFinding]:
        if not self.enabled:
            return []
        return [finding for finding in findings if finding.importance_score >= self.config.minimum_importance]

    def notify_findings(self, findings: list[OperationalFinding]) -> None:
        """New problems and problems that got worse."""
        eligible = self._eligible(findings)
        if not eligible:
            return
        if self.session_factory is None:
            for finding in eligible:
                self._run(self._send_once, finding)
            return
        try:
            self._enqueue_and_send(eligible)
        except Exception:
            # The outbox itself failed (e.g. the database is down): still try Slack once.
            logger.warning("Slack outbox unavailable; sending without retry", exc_info=True)
            for finding in eligible:
                self._run(self._send_once, finding)

    def notify_seen_again(self, findings: list[OperationalFinding]) -> None:
        """Findings of a problem already reported. Sent only when every earlier message for the
        problem failed: a delivered or still-retrying one means the team has it or will."""
        eligible = [finding for finding in self._eligible(findings) if finding.problem_id is not None]
        if not eligible or self.session_factory is None:
            return
        try:
            with self.session_factory() as db:
                statuses: dict[int, set[str]] = {}
                keys = {finding.problem_id for finding in eligible}
                for key, status in db.execute(
                    select(SlackNotificationEntity.problem_key, SlackNotificationEntity.status).where(SlackNotificationEntity.problem_key.in_(keys))
                ):
                    statuses.setdefault(key, set()).add(status)
            undelivered = [finding for finding in eligible if statuses.get(finding.problem_id) == {FAILED}]
            if undelivered:
                self._enqueue_and_send(undelivered)
        except Exception:
            logger.warning("Slack outbox check failed for repeated findings", exc_info=True)

    def deliver_due(self, now: datetime | None = None) -> int:
        """Retries pending messages whose next attempt is due; returns how many were tried.
        Rows are claimed with SKIP LOCKED on Postgres, so several backends never send one twice."""
        if not self.enabled or self.session_factory is None:
            return 0
        now = now or datetime.utcnow()
        with self.session_factory() as db:
            query = (
                select(SlackNotificationEntity)
                .where(SlackNotificationEntity.status == PENDING, SlackNotificationEntity.next_attempt_at <= now)
                .order_by(SlackNotificationEntity.next_attempt_at)
                .limit(RETRY_BATCH_SIZE)
            )
            if db.get_bind().dialect.name == "postgresql":
                query = query.with_for_update(skip_locked=True)
            rows = db.scalars(query).all()
            for row in rows:
                self._attempt(row, now)
            db.commit()
        return len(rows)

    @staticmethod
    def _plain(db, findings: list[OperationalFinding]) -> dict[int, dict]:
        """Plain wording for saved findings, from their stored signals. Wording never blocks a
        message: without it the message uses the stored title and summary."""
        ids = [finding.id for finding in findings if finding.id is not None]
        if not ids:
            return {}
        try:
            return finding_plain(db, db.scalars(select(FindingEntity).where(FindingEntity.id.in_(ids))).all())
        except Exception:
            logger.warning("Slack message: plain wording failed, using the stored summary", exc_info=True)
            return {}

    def _enqueue_and_send(self, findings: list[OperationalFinding]) -> None:
        now = datetime.utcnow()
        with self.session_factory() as db:
            plain = self._plain(db, findings)
            rows = [
                SlackNotificationEntity(
                    problem_key=finding.problem_id if finding.problem_id is not None else finding.id,
                    finding_id=finding.id,
                    title=finding.title,
                    service=finding.service,
                    metric_name=finding.metric_name,
                    payload=build_finding_blocks(finding, plain.get(finding.id)),
                    status=PENDING,
                    # Not due for the retry loop until the first try below has had its chance.
                    next_attempt_at=now + RETRY_DELAYS[0],
                    created_at=now,
                )
                for finding in findings
            ]
            db.add_all(rows)
            db.commit()
            if self.background:
                self._run(self._first_attempt, [row.id for row in rows], now)
                return
            for row in rows:
                self._attempt(row, now)
            db.commit()

    def _first_attempt(self, row_ids: list[int], now: datetime) -> None:
        """The immediate try of newly queued messages, on the worker thread with its own session.
        The retry loop leaves them alone until RETRY_DELAYS[0] has passed."""
        with self.session_factory() as db:
            rows = db.scalars(
                select(SlackNotificationEntity).where(SlackNotificationEntity.id.in_(row_ids), SlackNotificationEntity.status == PENDING)
            ).all()
            for row in rows:
                self._attempt(row, now)
            db.commit()

    def _run(self, function: Callable[..., None], *args) -> None:
        if not self.background:
            function(*args)
            return
        with self._executor_lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="slack-send")
            self._executor.submit(self._logged, function, *args)

    @staticmethod
    def _logged(function: Callable[..., None], *args) -> None:
        try:
            function(*args)
        except Exception:
            logger.exception("Slack notification send failed")

    def close(self) -> None:
        """Waits for sends already started (each is bounded by the Slack timeout)."""
        with self._executor_lock:
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=True)

    def _attempt(self, row: SlackNotificationEntity, now: datetime) -> None:
        row.attempts += 1
        try:
            self._post(row.payload)
        except Exception as exc:
            row.last_error = str(exc)[:1000]
            if row.attempts >= MAX_ATTEMPTS:
                row.status = FAILED
                logger.error(
                    "Slack notification gave up after %d attempts for %r on %s/%s: %s",
                    row.attempts, row.title, row.service, row.metric_name, exc,
                )
            else:
                row.next_attempt_at = now + RETRY_DELAYS[row.attempts - 1]
                logger.warning(
                    "Slack notification failed for %r on %s/%s (attempt %d of %d, retrying): %s",
                    row.title, row.service, row.metric_name, row.attempts, MAX_ATTEMPTS, exc,
                )
            return
        row.status = DELIVERED
        row.delivered_at = now
        row.last_error = None

    def _send_once(self, finding: OperationalFinding) -> None:
        try:
            self._post(build_finding_blocks(finding))
        except Exception as exc:
            logger.warning(
                "Slack notification failed for finding %r on %s/%s: %s",
                finding.title,
                finding.service,
                finding.metric_name,
                exc,
            )

    def _post(self, payload: dict) -> None:
        post_to_slack_webhook(self.config.webhook_url, payload, self.config.timeout_seconds)


def post_to_slack_webhook(webhook_url: str, payload: dict, timeout_seconds: float) -> None:
    """POST one Block Kit payload to a Slack incoming webhook. Raises RuntimeError on failure;
    callers decide whether that's fatal (it never is for notifications)."""
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            if response.status >= 300:
                raise RuntimeError(f"Slack webhook returned HTTP {response.status}")
    except HTTPError as exc:
        raise RuntimeError(f"Slack webhook returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"Slack webhook unreachable: {exc.reason}") from exc
