from __future__ import annotations

import hashlib
import hmac
import httpx
import pytest

from backend.app.config import JiraConfig
from backend.app.integrations.ticketing.jira.adapter import JiraTicketProvider
from backend.app.integrations.ticketing.jira.adf import (
    adf_to_plain_text,
    build_case_adf_description,
    build_case_resolution_adf_comment,
)
from backend.app.integrations.ticketing.models import TicketDraft, TicketResolutionDraft
from backend.app.integrations.ticketing.protocols import (
    AmbiguousOutcomeError,
    ProviderNotConfiguredError,
    TicketingError,
)


def _make_sample_draft() -> TicketDraft:
    return TicketDraft(
        case_id=42,
        case_title="CPU saturation on checkout",
        summary="Sustained high load observed across multiple pods",
        service="checkout",
        metric_name="container_cpu_usage_seconds_total",
        health_status="critical",
        importance_score=0.92,
        analysis_run_id="run_123",
        rca_summary="Memory leak in serialization layer",
        deep_link_url="http://localhost:3000/cases/42",
    )


def test_build_case_adf_description():
    draft = _make_sample_draft()
    adf = build_case_adf_description(draft)
    assert adf["type"] == "doc"
    assert adf["version"] == 1
    content = adf["content"]
    assert len(content) >= 3

    # Check title heading
    heading = content[0]
    assert heading["type"] == "heading"
    assert "Case #42" in heading["content"][0]["text"]

    # Check link mark
    deep_link_node = content[-1]
    link_mark = deep_link_node["content"][0]["marks"][0]
    assert link_mark["type"] == "link"
    assert link_mark["attrs"]["href"] == "http://localhost:3000/cases/42"


def test_adf_to_plain_text():
    sample_adf = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Investigating this issue now."},
                ],
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Found root cause in DB pool."},
                ],
            },
        ],
    }
    text = adf_to_plain_text(sample_adf)
    assert "Investigating this issue now." in text
    assert "Found root cause in DB pool." in text


def test_fail_closed_jira_configuration():
    # Incomplete configuration (missing api_token and project_key)
    incomplete_config = JiraConfig(
        base_url="https://example.atlassian.net",
        email="eng@example.com",
    )
    provider = JiraTicketProvider(incomplete_config)
    assert not provider.is_configured
    assert "api_token" in provider.missing_config
    assert "project_key" in provider.missing_config

    draft = _make_sample_draft()
    with pytest.raises(ProviderNotConfiguredError):
        provider.reconcile_or_create(draft, "op_123")


def test_jira_pre_reconciliation_adopts_existing_issue(monkeypatch):
    config = JiraConfig(
        base_url="https://example.atlassian.net",
        email="eng@example.com",
        api_token="secret",
        project_key="OPS",
        issue_type="Task",
    )
    provider = JiraTicketProvider(config)
    assert provider.is_configured

    def mock_post(self, url, json=None, **kwargs):
        if "/rest/api/3/search/jql" in url:
            assert 'labels = "ops-signals-op-op_test"' in json["jql"]
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "issues": [
                        {
                            "id": "10050",
                            "key": "OPS-50",
                            "fields": {"status": {"name": "In Progress"}},
                        }
                    ],
                },
            )
        return httpx.Response(404)

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    draft = _make_sample_draft()
    result = provider.reconcile_or_create(draft, "op_test")
    assert result.remote_id == "10050"
    assert result.display_key == "OPS-50"
    assert result.initial_status == "In Progress"
    assert "OPS-50" in result.ticket_url


def test_jira_pre_reconciliation_fallback_to_legacy_search(monkeypatch):
    config = JiraConfig(
        base_url="https://example.atlassian.net",
        email="eng@example.com",
        api_token="secret",
        project_key="OPS",
        issue_type="Task",
    )
    provider = JiraTicketProvider(config)

    def mock_post(self, url, json=None, **kwargs):
        if "/rest/api/3/search/jql" in url:
            return httpx.Response(404, text="Not Found")
        return httpx.Response(404)

    def mock_get(self, url, params=None, **kwargs):
        if "/rest/api/3/search" in url:
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "issues": [
                        {
                            "id": "10050",
                            "key": "OPS-50",
                            "fields": {"status": {"name": "In Progress"}},
                        }
                    ],
                },
            )
        return httpx.Response(404)

    monkeypatch.setattr(httpx.Client, "post", mock_post)
    monkeypatch.setattr(httpx.Client, "get", mock_get)

    draft = _make_sample_draft()
    result = provider.reconcile_or_create(draft, "op_test")
    assert result.remote_id == "10050"
    assert result.display_key == "OPS-50"


def test_jira_create_issue_success(monkeypatch):
    config = JiraConfig(
        base_url="https://example.atlassian.net",
        email="eng@example.com",
        api_token="secret",
        project_key="OPS",
        issue_type="Task",
    )
    provider = JiraTicketProvider(config)

    def mock_post(self, url, json=None, **kwargs):
        if "/rest/api/3/search/jql" in url:
            # Pre-reconciliation search finds nothing
            return httpx.Response(200, json={"total": 0, "issues": []})
        assert "/rest/api/3/issue" in url
        labels = json["fields"]["labels"]
        assert "ops-signals" in labels
        assert "ops-signals-case-42" in labels
        assert "ops-signals-op-op_create" in labels
        return httpx.Response(201, json={"id": "10099", "key": "OPS-99"})

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    draft = _make_sample_draft()
    result = provider.reconcile_or_create(draft, "op_create")
    assert result.remote_id == "10099"
    assert result.display_key == "OPS-99"
    assert result.initial_status == "open"


@pytest.mark.parametrize("status_code", [500, 502, 503, 504])
def test_jira_create_issue_uncertain_status_raises_ambiguous_outcome(monkeypatch, status_code):
    config = JiraConfig(
        base_url="https://example.atlassian.net",
        email="eng@example.com",
        api_token="secret",
        project_key="OPS",
    )
    provider = JiraTicketProvider(config)

    def mock_post(self, url, json=None, **kwargs):
        if "/rest/api/3/search/jql" in url:
            return httpx.Response(200, json={"total": 0, "issues": []})
        return httpx.Response(status_code, text="Gateway error")

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    draft = _make_sample_draft()
    with pytest.raises(AmbiguousOutcomeError) as exc_info:
        provider.reconcile_or_create(draft, "op_ambiguous")
    assert f"HTTP {status_code}" in str(exc_info.value)


def test_jira_webhook_verification():
    secret = "my-webhook-secret"
    config = JiraConfig(webhook_secret=secret)
    provider = JiraTicketProvider(config)

    body = b'{"webhookEvent": "comment_created", "issue": {"id": "101", "key": "OPS-101"}}'
    sig = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    assert provider.verify_signature(body, {"X-Hub-Signature": sig}, secret)
    assert not provider.verify_signature(b'tampered body', {"X-Hub-Signature": sig}, secret)
    assert not provider.verify_signature(body, {"X-Hub-Signature": "sha256=invalid"}, secret)


def test_jira_webhook_parsing():
    config = JiraConfig()
    provider = JiraTicketProvider(config)

    # 1. Delivery identifier
    headers = {"X-Atlassian-Webhook-Identifier": "deliv-xyz-123"}
    assert provider.extract_delivery_id(headers) == "deliv-xyz-123"

    # 2. Comment event parsing with ADF conversion
    raw_body = b'''{
        "webhookEvent": "comment_created",
        "issue": {"id": "2001", "key": "OPS-2001", "fields": {"status": {"name": "In Progress"}}},
        "comment": {
            "id": "505",
            "author": {"displayName": "Alice Engineer"},
            "body": {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Deploying hotfix."}]}]
            }
        }
    }'''

    event = provider.parse_webhook_event(raw_body, headers)
    assert event is not None
    assert event.remote_id == "2001"
    assert event.display_key == "OPS-2001"
    assert event.remote_event_id == "jira_comment_505"
    assert event.event_type == "comment_added"
    assert event.author == "Alice Engineer"
    assert "Deploying hotfix." in event.summary


def test_build_case_resolution_adf_comment():
    draft = TicketResolutionDraft(
        case_id=99,
        display_key="OPS-99",
        root_cause_summary="Keep-alive timeout mismatch",
        root_cause_verified=True,
        corrective_action="Adjusted pool size to 50",
        outcome_status="resolved",
        outcome_summary="All worker pools stabilized",
        deep_link_url="http://localhost:3000/cases/99",
    )
    adf = build_case_resolution_adf_comment(draft)
    assert adf["type"] == "doc"
    assert adf["version"] == 1
    content = adf["content"]
    assert len(content) == 6

    # Check title heading
    heading = content[0]
    assert heading["type"] == "heading"
    assert "Case #99" in heading["content"][0]["text"]

    # Check link
    link_node = content[-1]
    link_mark = link_node["content"][0]["marks"][0]
    assert link_mark["type"] == "link"
    assert link_mark["attrs"]["href"] == "http://localhost:3000/cases/99"


def test_resolve_ticket_with_done_transition(monkeypatch):
    config = JiraConfig(
        base_url="https://example.atlassian.net",
        email="eng@example.com",
        api_token="secret",
        project_key="OPS",
    )
    provider = JiraTicketProvider(config)

    posted_urls: list[str] = []
    posted_payloads: list[dict] = []

    def mock_post(self, url, json=None, **kwargs):
        posted_urls.append(url)
        posted_payloads.append(json or {})
        if "/comment" in url:
            return httpx.Response(201, json={"id": "comm_123"})
        if "/transitions" in url:
            return httpx.Response(204)
        return httpx.Response(400)

    def mock_get(self, url, **kwargs):
        if "/transitions" in url:
            return httpx.Response(200, json={
                "transitions": [
                    {"id": "11", "name": "In Progress", "to": {"name": "In Progress"}},
                    {"id": "41", "name": "Done", "to": {"name": "Done"}},
                ]
            })
        return httpx.Response(404)

    monkeypatch.setattr(httpx.Client, "post", mock_post)
    monkeypatch.setattr(httpx.Client, "get", mock_get)

    draft = TicketResolutionDraft(
        case_id=8,
        display_key="OPS-8",
        root_cause_summary="Keep-alive timeout misconfigured",
        root_cause_verified=True,
        corrective_action="Rolled back keep-alive config",
        outcome_status="resolved",
        outcome_summary="Issue mitigated",
        deep_link_url="/cases/8",
    )

    result = provider.resolve_ticket("1008", "OPS-8", draft)
    assert result.success is True
    assert result.remote_id == "1008"
    assert result.display_key == "OPS-8"
    assert result.comment_id == "comm_123"
    assert result.transitioned_to == "Done"

    # Verify comment was posted and transition was invoked
    assert any("/comment" in u for u in posted_urls)
    assert any("/transitions" in u and p.get("transition", {}).get("id") == "41" for u, p in zip(posted_urls, posted_payloads))


def test_resolve_ticket_graceful_degradation_when_no_done_transition(monkeypatch):
    config = JiraConfig(
        base_url="https://example.atlassian.net",
        email="eng@example.com",
        api_token="secret",
        project_key="OPS",
    )
    provider = JiraTicketProvider(config)

    def mock_post(self, url, json=None, **kwargs):
        if "/comment" in url:
            return httpx.Response(201, json={"id": "comm_456"})
        return httpx.Response(400)

    def mock_get(self, url, **kwargs):
        if "/transitions" in url:
            return httpx.Response(200, json={
                "transitions": [
                    {"id": "21", "name": "Under Review", "to": {"name": "Under Review"}},
                ]
            })
        return httpx.Response(404)

    monkeypatch.setattr(httpx.Client, "post", mock_post)
    monkeypatch.setattr(httpx.Client, "get", mock_get)

    draft = TicketResolutionDraft(
        case_id=8,
        display_key="OPS-8",
        root_cause_summary="Unverified bug",
        root_cause_verified=False,
        outcome_status="resolved",
    )

    result = provider.resolve_ticket("1008", "OPS-8", draft)
    assert result.success is True
    assert result.comment_id == "comm_456"
    assert result.transitioned_to is None


def test_resolve_ticket_network_error_raises_ambiguous(monkeypatch):
    config = JiraConfig(
        base_url="https://example.atlassian.net",
        email="eng@example.com",
        api_token="secret",
        project_key="OPS",
    )
    provider = JiraTicketProvider(config)

    def mock_post(self, url, json=None, **kwargs):
        raise httpx.ConnectTimeout("Connection timed out")

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    draft = TicketResolutionDraft(
        case_id=8,
        display_key="OPS-8",
        outcome_status="resolved",
    )

    with pytest.raises(AmbiguousOutcomeError) as exc_info:
        provider.resolve_ticket("1008", "OPS-8", draft)
    assert "Network error resolving Jira ticket OPS-8" in str(exc_info.value)

