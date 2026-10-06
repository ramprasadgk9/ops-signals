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
    build_case_resolution_adf_comment,
)
from backend.app.integrations.ticketing.models import (
    RemoteEventDraft,
    RemoteTicketSnapshot,
    TicketCreationResult,
    TicketDraft,
    TicketResolutionDraft,
    TicketResolutionResult,
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

    def reconcile_only(self, operation_id: str, case_id: int | None = None) -> TicketCreationResult | None:
        """Searches Jira Cloud for an existing issue matching the operation correlation label without creating a new one."""
        self._ensure_configured()
        op_label = f"ops-signals-op-{operation_id}"
        jql = f'labels = "{op_label}"'
        search_url = f"{self.base_url}/rest/api/3/search/jql"
        try:
            with self._get_client() as client:
                # 1. Primary standard Jira Cloud endpoint: POST /rest/api/3/search/jql (CHANGE-2046)
                search_res = client.post(
                    search_url,
                    json={
                        "jql": jql,
                        "maxResults": 1,
                        "fields": ["summary", "status"],
                    },
                )
                # Fallback to legacy GET /rest/api/3/search if search/jql returns 404/405 (e.g. older on-prem Jira Server/DC)
                if search_res.status_code in (404, 405):
                    search_res = client.get(
                        f"{self.base_url}/rest/api/3/search",
                        params={"jql": jql, "maxResults": 1, "fields": "summary,status"},
                    )

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
                    return None
                raise TicketingError(f"Jira search returned HTTP {search_res.status_code}: {search_res.text}")
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            raise AmbiguousOutcomeError(f"Network error searching Jira during pre-reconciliation: {e}") from e

    def reconcile_or_create(self, draft: TicketDraft, operation_id: str) -> TicketCreationResult:
        """Attempts safe pre-retry reconciliation via JQL label search before creating an issue."""
        self._ensure_configured()
        existing = self.reconcile_only(operation_id, draft.case_id)
        if existing:
            return existing

        case_label = f"ops-signals-case-{draft.case_id}"
        global_label = "ops-signals"
        op_label = f"ops-signals-op-{operation_id}"

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

    def resolve_ticket(
        self,
        remote_id: str,
        display_key: str,
        resolution: TicketResolutionDraft,
    ) -> TicketResolutionResult:
        """Posts a formatted ADF resolution comment to the Jira ticket and optionally transitions it to Done."""
        self._ensure_configured()
        comment_url = f"{self.base_url}/rest/api/3/issue/{remote_id}/comment"
        adf_body = build_case_resolution_adf_comment(resolution)
        comment_payload = {"body": adf_body}
        comment_id = None
        transitioned_to = None

        try:
            with self._get_client() as client:
                # 1. Post resolution comment
                res = client.post(comment_url, json=comment_payload)
                if res.status_code in (500, 502, 503, 504):
                    raise AmbiguousOutcomeError(
                        f"Jira returned HTTP {res.status_code} posting resolution comment for {display_key}"
                    )
                if not res.is_success:
                    raise TicketingError(
                        f"Failed to post resolution comment to Jira {display_key}: HTTP {res.status_code} - {res.text}"
                    )
                comment_data = res.json()
                comment_id = str(comment_data.get("id"))
                logger.info("Successfully posted resolution comment %s to Jira issue %s", comment_id, display_key)

                # 2. Attempt to transition to Done / Resolved / Closed (fail-safe)
                try:
                    trans_url = f"{self.base_url}/rest/api/3/issue/{remote_id}/transitions"
                    trans_res = client.get(trans_url)
                    if trans_res.is_success:
                        transitions = trans_res.json().get("transitions", [])
                        target_trans = None
                        target_names = {"done", "resolved", "closed", "complete"}
                        for t in transitions:
                            to_name = str(t.get("to", {}).get("name", "")).lower().strip()
                            t_name = str(t.get("name", "")).lower().strip()
                            if to_name in target_names or t_name in target_names:
                                target_trans = t
                                break
                        if target_trans:
                            trans_id = target_trans["id"]
                            trans_target_name = target_trans.get("to", {}).get("name") or target_trans.get("name")
                            do_trans_res = client.post(trans_url, json={"transition": {"id": trans_id}})
                            if do_trans_res.is_success or do_trans_res.status_code == 204:
                                transitioned_to = trans_target_name
                                logger.info("Successfully transitioned Jira issue %s to %s", display_key, transitioned_to)
                            else:
                                logger.warning(
                                    "Could not transition Jira issue %s to %s (HTTP %s): %s",
                                    display_key,
                                    trans_target_name,
                                    do_trans_res.status_code,
                                    do_trans_res.text,
                                )
                except Exception as trans_err:
                    logger.warning("Optional transition to Done failed for Jira issue %s: %s", display_key, trans_err)

                return TicketResolutionResult(
                    remote_id=remote_id,
                    display_key=display_key,
                    comment_id=comment_id,
                    transitioned_to=transitioned_to,
                    success=True,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            raise AmbiguousOutcomeError(f"Network error resolving Jira ticket {display_key}: {e}") from e

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

        delivery_id = self.extract_delivery_id(headers)

        # 2. Status / changelog events
        changelog = data.get("changelog", {})
        changelog_id = str(changelog.get("id") or "")
        for item in changelog.get("items", []):
            if item.get("field") == "status":
                new_status = item.get("toString") or ""
                event_key = changelog_id or (f"{new_status}_{delivery_id}" if delivery_id else f"{new_status}_{data.get('timestamp') or 'latest'}")
                return RemoteEventDraft(
                    remote_id=remote_id,
                    display_key=display_key,
                    remote_event_id=f"jira_status_{event_key}",
                    event_type="status_changed",
                    author=data.get("user", {}).get("displayName"),
                    summary=f"Remote Jira status changed to {new_status}",
                    observed_remote_status=new_status,
                    payload={"from": item.get("fromString"), "to": new_status},
                    occurred_at=occurred_at,
                )

        # 3. Generic issue update fallback
        if observed_remote_status:
            update_key = data.get("timestamp") or delivery_id or "latest"
            return RemoteEventDraft(
                remote_id=remote_id,
                display_key=display_key,
                remote_event_id=f"jira_update_{update_key}",
                event_type="issue_updated",
                author=data.get("user", {}).get("displayName"),
                summary=f"Jira issue updated (Status: {observed_remote_status})",
                observed_remote_status=observed_remote_status,
                payload={},
                occurred_at=occurred_at,
            )

        return None
