"""Tests for CommentTriageService."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from backend.app.ai.exceptions import LLMRequestError
from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.interfaces import LLMClient, LLMResponse
from backend.app.ai.models import StructuredLLMService
from backend.app.ai.services.comment_triage_service import (
    CommentTriageEvaluation,
    CommentTriageService,
)


def _build_mock_ai_services(return_json: dict | None = None, raise_error: Exception | None = None) -> OptionalAIServices:
    client = MagicMock(spec=LLMClient)
    if raise_error:
        client.generate.side_effect = raise_error
    else:
        payload = return_json or {
            "is_relevant_clue": True,
            "confidence": 0.95,
            "reason": "Comment details root cause and remediation action",
        }
        client.generate.return_value = LLMResponse(content=json.dumps(payload))
    structured = StructuredLLMService(client=client, retry_on_invalid_output=False)
    return OptionalAIServices(client=client, structured=structured)


def test_triage_service_evaluates_relevant_clue():
    mock_ai = _build_mock_ai_services({
        "is_relevant_clue": True,
        "confidence": 0.92,
        "reason": "Explains PostgreSQL connection deadlock resolved by restarting pool",
    })
    service = CommentTriageService(confidence_threshold=0.75)
    case_context = {
        "case_title": "Database connection spike on checkout-service",
        "service": "checkout-service",
        "metric_name": "db_pool_utilization",
        "summary": "Database pool reached 100% saturation",
    }
    evaluation = service.evaluate(
        mock_ai,
        case_context=case_context,
        author="DevOps Engineer",
        comment_body="Found deadlocked connection on pg-primary. Restarted connection pool; latency normalized.",
    )
    assert evaluation is not None
    assert evaluation.is_relevant_clue is True
    assert evaluation.confidence == 0.92
    assert "deadlock" in evaluation.reason.lower()
    assert service.is_promotable(evaluation) is True


def test_triage_service_evaluates_irrelevant_administrative_noise():
    mock_ai = _build_mock_ai_services({
        "is_relevant_clue": False,
        "confidence": 0.15,
        "reason": "Administrative assignment, no diagnostic or remediation content",
    })
    service = CommentTriageService(confidence_threshold=0.75)
    case_context = {
        "case_title": "Database connection spike",
        "service": "checkout-service",
        "metric_name": "db_pool_utilization",
        "summary": "Database pool saturation",
    }
    evaluation = service.evaluate(
        mock_ai,
        case_context=case_context,
        author="Scrum Master",
        comment_body="Moving ticket to next sprint and assigning to @backend-lead.",
    )
    assert evaluation is not None
    assert evaluation.is_relevant_clue is False
    assert evaluation.confidence == 0.15
    assert service.is_promotable(evaluation) is False


def test_triage_service_low_confidence_clue_not_promotable():
    mock_ai = _build_mock_ai_services({
        "is_relevant_clue": True,
        "confidence": 0.60,  # Below 0.75 threshold
        "reason": "Vague conjecture about network, no concrete evidence",
    })
    service = CommentTriageService(confidence_threshold=0.75)
    case_context = {"case_title": "Incident", "service": "api", "metric_name": "latency", "summary": "slow"}
    evaluation = service.evaluate(
        mock_ai,
        case_context=case_context,
        author="Analyst",
        comment_body="Could this maybe be related to the network?",
    )
    assert evaluation is not None
    assert evaluation.is_relevant_clue is True
    assert evaluation.confidence == 0.60
    assert service.is_promotable(evaluation) is False


def test_triage_service_none_when_ai_disabled():
    service = CommentTriageService()
    case_context = {"case_title": "Incident"}
    evaluation = service.evaluate(
        None,
        case_context=case_context,
        author="Tester",
        comment_body="Restarted pod",
    )
    assert evaluation is None
    assert service.is_promotable(evaluation) is False


def test_triage_service_empty_comment_returns_none():
    mock_ai = _build_mock_ai_services()
    service = CommentTriageService()
    case_context = {"case_title": "Incident"}
    evaluation = service.evaluate(
        mock_ai,
        case_context=case_context,
        author="Tester",
        comment_body="   \n  ",
    )
    assert evaluation is None
    assert service.is_promotable(evaluation) is False


def test_triage_service_ai_failure_fails_closed():
    mock_ai = _build_mock_ai_services(raise_error=LLMRequestError("Ollama host unreachable"))
    service = CommentTriageService()
    case_context = {"case_title": "Incident"}
    evaluation = service.evaluate(
        mock_ai,
        case_context=case_context,
        author="Tester",
        comment_body="Critical DB clue",
    )
    assert evaluation is None
    assert service.is_promotable(evaluation) is False
