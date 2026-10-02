from __future__ import annotations

import hashlib
import hmac
import httpx
import pytest

from backend.app.config import JiraConfig
from backend.app.integrations.ticketing.jira.adapter import JiraTicketProvider
from backend.app.integrations.ticketing.jira.adf import adf_to_plain_text, build_case_adf_description
from backend.app.integrations.ticketing.models import TicketDraft
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

    def mock_get(self, url, params=None, **kwargs):
        if "/rest/api/3/search" in url:
            assert 'labels = "ops-signals-op-op_test"' in params["jql"]
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

    monkeypatch.setattr(httpx.Client, "get", mock_get)

    draft = _make_sample_draft()
    result = provider.reconcile_or_create(draft, "op_test")
    assert result.remote_id == "10050"
    assert result.display_key == "OPS-50"
    assert result.initial_status == "In Progress"
    assert "OPS-50" in result.ticket_url


def test_jira_create_issue_success(monkeypatch):
    config = JiraConfig(
        base_url="https://example.atlassian.net",
        email="eng@example.com",
        api_token="secret",
        project_key="OPS",
        issue_type="Task",
    )
    provider = JiraTicketProvider(config)

    def mock_get(self, url, params=None, **kwargs):
        # Pre-reconciliation search finds nothing
        return httpx.Response(200, json={"total": 0, "issues": []})

    def mock_post(self, url, json=None, **kwargs):
        assert "/rest/api/3/issue" in url
        labels = json["fields"]["labels"]
        assert "ops-signals" in labels
        assert "ops-signals-case-42" in labels
        assert "ops-signals-op-op_create" in labels
        return httpx.Response(201, json={"id": "10099", "key": "OPS-99"})

    monkeypatch.setattr(httpx.Client, "get", mock_get)
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

    monkeypatch.setattr(
        httpx.Client, "get", lambda *a, **kw: httpx.Response(200, json={"total": 0, "issues": []})
    )
    monkeypatch.setattr(
        httpx.Client, "post", lambda *a, **kw: httpx.Response(status_code, text="Gateway error")
    )

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
