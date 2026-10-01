"""Operational memory recall, end to end with the real pieces: CaseDocumentBuilder, the MiniLM
embedder, Qdrant (in-memory mode) and build_alert_context. test_memory.py and test_alert_context.py
cover the plumbing with fakes; these prove that a stored case actually comes back for a realistic
alert, and that look-alikes and unrelated cases don't.

Skipped when the embedding model can't be loaded (first run downloads ~90 MB)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from qdrant_client import QdrantClient

from backend.app.api import memory as memory_module
from backend.app.config import MemoryConfig, VectorStoreConfig
from backend.app.memory.alert_context import build_alert_context
from backend.app.memory.embedder import CaseEmbedder
from backend.app.memory.indexer import CaseMemoryIndexer
from backend.app.memory.qdrant_initializer import QdrantInitializer
from backend.app.memory.similarity_service import SimilarityService
from backend.app.memory.vector_store import QdrantVectorStore
from backend.app.models.db import get_session_local
from backend.app.models.entities import FindingEntity, OperationalCaseEntity
from tests.api_backend.test_alert_receiver_api import METRIC_KEY, _message_text, _payload, harness  # noqa: F401

SERVICE = "checkout-api"
LATENCY = METRIC_KEY
ERRORS = "http_requests_errors_total"

# Past incidents. Only the first two share the alert's service and metric; the others are look-alikes
# (same cause elsewhere) and unrelated noise, so each one tests a different way recall could go wrong.
CATALOG = {
    "db_pool": dict(
        service=SERVICE, metric=LATENCY, title="checkout-api latency up after v2.3 deploy",
        summary="Sustained latency baseline shift on checkout-api: p95 moved from 180ms to 450ms.",
        root_cause="Database connection pool exhausted after the v2.3 deploy lowered the max pool size.",
        fix="Raised the pool size from 20 to 50.", outcome="Latency back to baseline within 10 minutes.",
    ),
    "payment_api": dict(
        service=SERVICE, metric=LATENCY, title="checkout-api latency up during payment provider incident",
        summary="Latency increase on checkout-api: p95 rose to 400ms.",
        root_cause="Third-party payment provider API was slow responding.",
        fix="Enabled the payment provider fallback.", outcome="Recovered when the provider fixed their incident.",
    ),
    "db_pool_errors": dict(
        service=SERVICE, metric=ERRORS, title="checkout-api 5xx errors from DB pool",
        summary="Error spike on checkout-api 5xx responses.",
        root_cause="Database connection pool exhausted; requests failed waiting for a connection.",
        fix="Raised the pool size.", outcome="Errors stopped.",
    ),
    "db_pool_payments": dict(
        service="payments-api", metric=LATENCY, title="payments-api latency from DB pool",
        summary="Sustained latency baseline shift on payments-api: p95 moved from 120ms to 380ms.",
        root_cause="Database connection pool exhausted under peak load.",
        fix="Raised the pool size.", outcome="Latency back to baseline.",
    ),
    "inventory_disk": dict(
        service="inventory-svc", metric="node_filesystem_avail_bytes", title="inventory-svc disk filling up",
        summary="Disk space on inventory-svc declining steadily.",
        root_cause="Log rotation was disabled.", fix="Re-enabled logrotate.", outcome="Disk freed.",
    ),
    "auth_cert": dict(
        service="auth-svc", metric=ERRORS, title="auth-svc 5xx after cert expiry",
        summary="Error spike on auth-svc 5xx responses.",
        root_cause="TLS certificate expired.", fix="Renewed the certificate.", outcome="Errors stopped.",
    ),
}

SYMPTOM_ALERT = "checkout-api p95 latency above 300ms"


@pytest.fixture(scope="module")
def embedder() -> CaseEmbedder:
    try:
        return CaseEmbedder()
    except RuntimeError as exc:
        pytest.skip(f"embedding model unavailable: {exc}")


@pytest.fixture()
def memory(embedder: CaseEmbedder) -> SimpleNamespace:
    client = QdrantClient(":memory:")
    assert QdrantInitializer.initialize(client)["status"] == "ready"
    store = QdrantVectorStore(client, QdrantInitializer.COLLECTION_NAME)
    config = MemoryConfig(enabled=True, vector_store=VectorStoreConfig(collection_name=QdrantInitializer.COLLECTION_NAME))
    return SimpleNamespace(
        client=client,
        embedder=embedder,
        indexer=CaseMemoryIndexer(store, embedder, config),
        similarity=SimilarityService(store, embedder, config),
    )


def _add_case(db, key: str, *, resolved: bool = True) -> OperationalCaseEntity:
    spec = CATALOG[key]
    now = datetime.utcnow()
    finding = FindingEntity(
        analysis_run_id=f"run-{key}", service=spec["service"], metric_name=spec["metric"],
        title=spec["title"], summary=spec["summary"], category="baseline_shift", health_status="significant",
        importance_score=0.8, investigation_priority=2, signal_ids=["sig-1"], comparison_json={}, created_at=now,
    )
    db.add(finding)
    db.commit()
    case = OperationalCaseEntity(
        finding_id=finding.id, analysis_run_id=finding.analysis_run_id, case_title=spec["title"],
        case_status="resolved" if resolved else "investigating",
        finding_snapshot={
            "id": finding.id, "service": spec["service"], "metric_name": spec["metric"], "title": spec["title"],
            "summary": spec["summary"], "category": "baseline_shift", "health_status": "significant",
            "importance_score": 0.8, "signal_ids": ["sig-1"],
        },
        investigation_status="completed" if resolved else "in_progress", investigation_notes=[],
        root_cause_status="confirmed" if resolved else "unknown",
        root_cause_summary=spec["root_cause"] if resolved else None,
        root_cause_verified=resolved, root_cause_confidence=0.9 if resolved else None,
        corrective_action=spec["fix"] if resolved else None,
        outcome_status="resolved" if resolved else "pending",
        outcome_summary=spec["outcome"] if resolved else None,
        memory_status="not_indexed", created_at=now, updated_at=now,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def _remember(db, memory: SimpleNamespace, keys=CATALOG) -> dict[str, int]:
    ids = {}
    for key in keys:
        case = _add_case(db, key)
        memory.indexer.index_case(case, db)
        ids[key] = case.id
    return ids


def _recall(db, memory: SimpleNamespace, message: str, metric: str = LATENCY, service: str | None = SERVICE):
    return build_alert_context(
        db, metric_name=metric, service=service, message=message,
        similarity=memory.similarity, embedder=memory.embedder,
    )


def test_symptom_only_alert_recalls_past_cases_on_the_same_service_and_metric(db_session, memory) -> None:
    ids = _remember(db_session, memory)

    context = _recall(db_session, memory, SYMPTOM_ALERT)

    assert {case.case_id for case in context.similar_cases} == {ids["db_pool"], ids["payment_api"]}
    # Measured ~0.6 against a 0.3 cutoff: a one-line alert clears it comfortably, not by luck.
    assert min(case.similarity_score for case in context.similar_cases) > 0.45
    recalled = {case.case_id: case for case in context.similar_cases}[ids["db_pool"]]
    assert recalled.root_cause_summary == CATALOG["db_pool"]["root_cause"]
    assert recalled.outcome_summary == CATALOG["db_pool"]["outcome"]
    assert recalled.reference == f"/cases/{ids['db_pool']}"


@pytest.mark.parametrize(
    ("message", "expected_first", "expected_second"),
    [
        ("checkout latency is up, db connections maxed out", "db_pool", "payment_api"),
        ("checkout slow, payment provider timing out", "payment_api", "db_pool"),
    ],
)
def test_cause_in_the_message_ranks_the_matching_case_first(
    db_session, memory, message: str, expected_first: str, expected_second: str
) -> None:
    ids = _remember(db_session, memory)

    context = _recall(db_session, memory, message)

    first, second = context.similar_cases
    assert (first.case_id, second.case_id) == (ids[expected_first], ids[expected_second])
    assert first.similarity_score - second.similarity_score > 0.05


def test_same_cause_on_another_metric_or_service_is_not_recalled(db_session, memory) -> None:
    ids = _remember(db_session, memory)

    context = _recall(db_session, memory, "checkout latency is up, db connections maxed out")

    recalled = {case.case_id for case in context.similar_cases}
    # Current design: recall is scoped to the alert's metric and service, so the same root cause
    # elsewhere is never offered - even though an engineer might find it useful.
    assert ids["db_pool_errors"] not in recalled
    assert ids["db_pool_payments"] not in recalled


def test_alert_on_a_metric_with_no_past_cases_recalls_nothing(db_session, memory) -> None:
    _remember(db_session, memory)

    context = _recall(db_session, memory, "orders consumer lag above 10k messages", metric="kafka_consumergroup_lag", service="orders-worker")

    assert context.similar_cases == []
    assert context.recommendation == "insufficient_history"
    assert context.recommendation_basis.startswith("No prior")


def test_root_cause_added_later_is_recalled_after_reindex(db_session, memory) -> None:
    ids = _remember(db_session, memory, ["payment_api"])
    open_case = _add_case(db_session, "db_pool", resolved=False)
    memory.indexer.index_case(open_case, db_session)
    message = "checkout latency is up, db connections maxed out"

    before = {case.case_id: case for case in _recall(db_session, memory, message).similar_cases}
    spec = CATALOG["db_pool"]
    open_case.root_cause_status, open_case.root_cause_summary = "confirmed", spec["root_cause"]
    open_case.corrective_action, open_case.outcome_summary = spec["fix"], spec["outcome"]
    open_case.case_status, open_case.outcome_status = "resolved", "resolved"
    db_session.commit()
    memory.indexer.index_case(open_case, db_session)
    after = _recall(db_session, memory, message).similar_cases

    assert before[open_case.id].root_cause_summary is None
    assert after[0].case_id == open_case.id
    assert after[0].root_cause_summary == spec["root_cause"]
    assert after[0].similarity_score > before[open_case.id].similarity_score
    assert ids["payment_api"] in {case.case_id for case in after}


def test_vector_store_outage_falls_back_to_exact_history(db_session, memory) -> None:
    _remember(db_session, memory)
    memory.client.delete_collection(QdrantInitializer.COLLECTION_NAME)

    context = _recall(db_session, memory, SYMPTOM_ALERT)

    assert context.similar_cases == []
    assert context.raw_activity.total_occurrences > 0  # the findings behind the cases still count


def test_alertmanager_alert_shows_the_recalled_case_in_the_message(harness, memory, monkeypatch) -> None:  # noqa: F811
    h = harness()
    with get_session_local()() as db:
        ids = _remember(db, memory, ["db_pool", "db_pool_errors", "inventory_disk"])
    monkeypatch.setitem(memory_module._services, "similarity_service", memory.similarity)
    monkeypatch.setitem(memory_module._services, "embedder", memory.embedder)

    response = h.client.post("/api/integrations/alertmanager", json=_payload())

    assert response.status_code == 202
    [message] = h.posted
    text = _message_text(message)
    assert f"/cases/{ids['db_pool']}" in text
    assert CATALOG["db_pool"]["title"] in text
    assert "% match" in text
    assert "First time Ops Signals has seen this alert." not in text
