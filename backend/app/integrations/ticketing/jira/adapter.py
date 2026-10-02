from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timezone
from typing import Any, Mapping

import httpx

from backend.app.config import JiraConfig
from backend.app.integrations.ticketing.jira.adf import (
    adf_to_plain_text,
    build_case_adf_description,
)
from backend.app.integrations.ticketing.models import (
    RemoteEventDraft,
    RemoteTicketSnapshot,
    TicketCreationResult,
    TicketDraft,
)
from backend.app.integrations.ticketing.protocols import (
    AmbiguousOutcomeError,
    ProviderNotConfiguredError,
    TicketingError,
)

logger = logging.getLogger(__name__)


class JiraTicketProvider:
    """Jira Cloud REST API v3 reference adapter."""

    def __init__(self, config: JiraConfig) -> None:
        self.config = config
        self.is_configured, self.missing_config = config.validate_configuration()
        if not self.is_configured:
            logger.warning(
                "Jira provider disabled: missing required configuration: %s",
                ", ".join(self.missing_config),
            )
        self.base_url = (config.base_url or "").rstrip("/")

    def _ensure_configured(self) -> None:
        if not self.is_configured:
            raise ProviderNotConfiguredError(
                f"Jira provider is not configured: missing {', '.join(self.missing_config)}"
            )

    def _get_auth(self) -> tuple[str, str]:
        self._ensure_configured()
        return (self.config.email or "", self.config.api_token or "")

    def _get_client(self) -> httpx.Client:
        return httpx.Client(
            auth=self._get_auth(),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=httpx.Timeout(self.config.request_timeout_seconds),
        )

    def reconcile_or_create(self, draft: TicketDraft, operation_id: str) -> TicketCreationResult:
        """Attempts safe pre-retry reconciliation via JQL label search before creating an issue."""
        self._ensure_configured()
        op_label = f"ops-signals-op-{operation_id}"
        case_label = f"ops-signals-case-{draft.case_id}"
        global_label = "ops-signals"

        # 1. Pre-reconciliation search by unique operation label
        jql = f'labels = "{op_label}"'
        search_url = f"{self.base_url}/rest/api/3/search"
        try:
            with self._get_client() as client:
                search_res = client.get(search_url, params={"jql": jql, "maxResults": 1})
                if search_res.status_code in (500, 502, 503, 504):
                    raise AmbiguousOutcomeError(
                        f"Jira search returned HTTP {search_res.status_code} during pre-reconciliation"
                    )
                if search_res.is_success:
                    data = search_res.json()
                    issues = data.get("issues", [])
                    if issues:
                        issue = issues[0]
                        remote_id = str(issue["id"])
                        key = issue["key"]
                        ticket_url = f"{self.base_url}/browse/{key}"
                        status = issue.get("fields", {}).get("status", {}).get("name", "open")
                        logger.info("Pre-reconciliation adopted existing Jira issue %s for op %s", key, operation_id)
                        return TicketCreationResult(
                            remote_id=remote_id,
                            display_key=key,
                            ticket_url=ticket_url,
                            initial_status=status,
                        )
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            raise AmbiguousOutcomeError(f"Network error searching Jira during pre-reconciliation: {e}") from e

        # 2. Outbound creation via POST /rest/api/3/issue
        create_url = f"{self.base_url}/rest/api/3/issue"
        body = {
            "fields": {
                "project": {"key": self.config.project_key},
                "summary": f"[Ops Signals] Case #{draft.case_id}: {draft.case_title}",
                "description": build_case_adf_description(draft),
                "issuetype": {"name": self.config.issue_type},
                "labels": [global_label, case_label, op_label],
            }
        }

        try:
            with self._get_client() as client:
                res = client.post(create_url, json=body)
                if res.status_code in (500, 502, 503, 504):
                    raise AmbiguousOutcomeError(
                        f"Jira issue creation returned uncertain status HTTP {res.status_code}"
                    )
                if not res.is_success:
                    raise TicketingError(f"Jira issue creation rejected: HTTP {res.status_code} - {res.text}")
                created = res.json()
                remote_id = str(created["id"])
                key = created["key"]
                ticket_url = f"{self.base_url}/browse/{key}"
                logger.info("Successfully created Jira issue %s for case %s (op %s)", key, draft.case_id, operation_id)
                return TicketCreationResult(
                    remote_id=remote_id,
                    display_key=key,
                    ticket_url=ticket_url,
                    initial_status="open",
                )
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            raise AmbiguousOutcomeError(f"Network error or timeout during Jira issue creation: {e}") from e

    def pull_remote_ticket(self, remote_id: str, display_key: str, cursor: str | None) -> RemoteTicketSnapshot:
        """Polls Jira Cloud for current ticket status, comments, and changelogs."""
        self._ensure_configured()
        url = f"{self.base_url}/rest/api/3/issue/{remote_id}"
        params = {"fields": "status,comment,updated", "expand": "changelog"}
        try:
            with self._get_client() as client:
                res = client.get(url, params=params)
                if res.status_code in (500, 502, 503, 504):
                    raise AmbiguousOutcomeError(f"Jira returned HTTP {res.status_code} during ticket pull")
                if not res.is_success:
                    raise TicketingError(f"Failed to fetch Jira ticket {display_key}: HTTP {res.status_code}")
                data = res.json()
                fields = data.get("fields", {})
                status_name = fields.get("status", {}).get("name", "unknown")
                raw_comments = fields.get("comment", {}).get("comments", [])
                comments = []
                for c in raw_comments:
                    comments.append(
                        {
                            "id": str(c.get("id")),
                            "author": c.get("author", {}).get("displayName") or c.get("author", {}).get("name"),
                            "body": adf_to_plain_text(c.get("body", "")).strip(),
                            "created": c.get("created"),
                        }
                    )
                changelog_items = []
                histories = data.get("changelog", {}).get("histories", [])
                for h in histories:
                    for item in h.get("items", []):
                        changelog_items.append(
                            {
                                "id": str(h.get("id")),
                                "field": item.get("field"),
                                "from_string": item.get("fromString"),
                                "to_string": item.get("toString"),
                                "author": h.get("author", {}).get("displayName"),
                                "created": h.get("created"),
                            }
                        )
                return RemoteTicketSnapshot(
                    remote_id=remote_id,
                    display_key=display_key,
                    remote_status=status_name,
                    comments=comments,
                    changelog_items=changelog_items,
                    cursor=data.get("fields", {}).get("updated"),
                )
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            raise AmbiguousOutcomeError(f"Network error pulling Jira ticket {display_key}: {e}") from e

    def verify_signature(self, raw_body: bytes, headers: Mapping[str, str], secret: str) -> bool:
        """Verifies cryptographic HMAC-SHA256 signature across headers."""
        if not secret:
            return False
        header_sig = (
            headers.get("x-hub-signature")
            or headers.get("X-Hub-Signature")
            or headers.get("x-hub-signature-256")
            or headers.get("X-Hub-Signature-256")
            or headers.get("x-atlassian-webhook-signature")
            or ""
        ).strip()
        if not header_sig:
            return False

        expected_hex = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        expected_sig = f"sha256={expected_hex}"

        # Match either prefixed 'sha256=...' or raw hex
        if header_sig.startswith("sha256="):
            return hmac.compare_digest(header_sig, expected_sig)
        return hmac.compare_digest(header_sig, expected_hex)

    def extract_delivery_id(self, headers: Mapping[str, str]) -> str | None:
        """Extracts canonical delivery identifier from Atlassian webhook headers."""
        return (
            headers.get("x-atlassian-webhook-identifier")
            or headers.get("X-Atlassian-Webhook-Identifier")
            or headers.get("x-delivery-id")
            or headers.get("X-Delivery-Id")
        )

    def parse_webhook_event(self, raw_body: bytes, headers: Mapping[str, str]) -> RemoteEventDraft | None:
        """Parses webhook JSON payload into a normalized RemoteEventDraft."""
        import json

        try:
            data = json.loads(raw_body.decode("utf-8"))
        except Exception:
            return None

        issue = data.get("issue", {})
        remote_id = str(issue.get("id") or "")
        display_key = issue.get("key") or ""
        if not remote_id:
            return None

        webhook_event = data.get("webhookEvent", "")
        occurred_at = datetime.now(timezone.utc)
        observed_remote_status = issue.get("fields", {}).get("status", {}).get("name")

        # 1. Comment events
        if "comment" in webhook_event or "comment" in data:
            comment = data.get("comment", {})
            comment_id = str(comment.get("id") or "")
            if comment_id:
                author = comment.get("author", {}).get("displayName") or comment.get("author", {}).get("name")
                body_text = adf_to_plain_text(comment.get("body", "")).strip()
                return RemoteEventDraft(
                    remote_id=remote_id,
                    display_key=display_key,
                    remote_event_id=f"jira_comment_{comment_id}",
                    event_type="comment_added",
                    author=author,
                    summary=body_text or "Comment added in Jira",
                    observed_remote_status=observed_remote_status,
                    payload={"comment_id": comment_id, "text": body_text},
                    occurred_at=occurred_at,
                )

        # 2. Status / changelog events
        changelog = data.get("changelog", {})
        changelog_id = str(changelog.get("id") or "")
        for item in changelog.get("items", []):
            if item.get("field") == "status":
                new_status = item.get("toString") or ""
                return RemoteEventDraft(
                    remote_id=remote_id,
                    display_key=display_key,
                    remote_event_id=f"jira_status_{changelog_id or occurred_at.timestamp()}",
                    event_type="status_changed",
                    author=data.get("user", {}).get("displayName"),
                    summary=f"Remote Jira status changed to {new_status}",
                    observed_remote_status=new_status,
                    payload={"from": item.get("fromString"), "to": new_status},
                    occurred_at=occurred_at,
                )

        # 3. Generic issue update fallback
        if observed_remote_status:
            return RemoteEventDraft(
                remote_id=remote_id,
                display_key=display_key,
                remote_event_id=f"jira_update_{data.get('timestamp') or occurred_at.timestamp()}",
                event_type="issue_updated",
                author=data.get("user", {}).get("displayName"),
                summary=f"Jira issue updated (Status: {observed_remote_status})",
                observed_remote_status=observed_remote_status,
                payload={},
                occurred_at=occurred_at,
            )

        return None
