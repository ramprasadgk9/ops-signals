from __future__ import annotations

import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.app.config import SlackConfig
from backend.app.notifications.message_builder import build_finding_blocks
from intelligence.findings.schema import OperationalFinding

logger = logging.getLogger(__name__)


class SlackNotifier:
    """Posts findings to a Slack incoming webhook.

    Best-effort only: a failure notifying Slack is logged and swallowed here, never
    raised, so a broken or unconfigured webhook can never fail the analysis pipeline
    it's attached to.
    """

    def __init__(self, config: SlackConfig):
        self.config = config

    def notify_findings(self, findings: list[OperationalFinding]) -> None:
        if not self.config.enabled or not self.config.webhook_url:
            return
        for finding in findings:
            if finding.importance_score < self.config.minimum_importance:
                continue
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
