"""Imported incidents are recalled like detected cases, end to end with the real embedder and
in-memory Qdrant: an alert or a newly detected case on the same service finds a matching imported
postmortem, even though postmortems carry no metric. Reuses the fixtures from test_memory_recall.py.

Skipped when the embedding model can't be loaded."""

from __future__ import annotations

from backend.app.case_import.parsers import ImportSettings, parse_files
from backend.app.case_import.service import CaseImportService
from tests.api_backend.test_memory_recall import SERVICE, SYMPTOM_ALERT, _add_case, _recall, embedder, memory  # noqa: F401

POSTMORTEMS = """id,title,service,started_at,symptom,root_cause,fix,outcome
PM-1,Checkout slow after release,checkout-api,2025-03-14T18:20:00Z,p95 latency on checkout rose from 200ms to 900ms,Database connection pool exhausted after the release lowered the max pool size,Raised the pool size back to 50,Latency recovered within minutes
PM-2,Payments slow at peak,payments-api,2025-04-02T12:00:00Z,p95 latency on payments rose to 700ms,Database connection pool exhausted under peak load,Raised the pool size,Latency recovered
PM-3,Login failures after certificate expiry,auth-svc,2025-05-10T08:00:00Z,5xx errors on login,TLS certificate expired,Renewed the certificate and added expiry alerts,Errors stopped
"""


def _import(db, memory) -> dict[str, int]:
    upload = parse_files([("postmortems.csv", POSTMORTEMS.encode())], ImportSettings())
    service = CaseImportService(db, memory.indexer, memory.indexer.config)
    result = service.apply(service.plan(upload), source_files=["postmortems.csv"])
    assert result.indexed == 3
    return {item.record.source_id: item.case_id for item in result.plan.items}


def test_alert_recalls_an_imported_postmortem_on_the_same_service(db_session, memory) -> None:
    ids = _import(db_session, memory)

    context = _recall(db_session, memory, SYMPTOM_ALERT)

    recalled = [case.case_id for case in context.similar_cases]
    assert ids["PM-1"] in recalled
    assert ids["PM-2"] not in recalled
    assert ids["PM-3"] not in recalled


def test_detected_case_finds_a_similar_imported_postmortem(db_session, memory) -> None:
    ids = _import(db_session, memory)
    detected = _add_case(db_session, "db_pool")
    memory.indexer.index_case(detected, db_session)

    response = memory.similarity.find_similar_cases(detected.id, db_session, minimum_score=0.3, same_service_only=True)

    matched = [match.case_id for match in response.matches]
    assert matched[:1] == [ids["PM-1"]]
    assert ids["PM-2"] not in matched


def test_unrelated_imported_incident_is_not_recalled_for_the_alert(db_session, memory) -> None:
    ids = _import(db_session, memory)

    context = _recall(db_session, memory, "auth-svc certificate expired, login 5xx", service=SERVICE)

    assert ids["PM-3"] not in [case.case_id for case in context.similar_cases]


def _detected_checkout_cpu_finding(db):
    from datetime import datetime

    from backend.app.models.entities import FindingEntity

    finding = FindingEntity(
        analysis_run_id="run-live", service=SERVICE, metric_name="cpu_usage",
        title="cpu_usage experienced a persistent baseline shift during the analysis window.",
        summary="CPU usage on checkout-api moved from about 40% to a sustained 90% after the change point.",
        category="baseline_shift", health_status="critical", importance_score=0.9, investigation_priority=1,
        signal_ids=[], comparison_json={}, created_at=datetime.utcnow(),
    )
    db.add(finding)
    db.commit()
    return finding


CPU_POSTMORTEMS = """id,title,service,started_at,symptom,root_cause,fix
PM-10,Checkout CPU pinned at 95% after release,checkout-api,2025-02-03T14:10:00Z,CPU usage on checkout jumped from 40% to 95% after the release,Release enabled JSON schema validation on every request,Cached the compiled schema
PM-11,Payments CPU climbing over three days,payments-api,2025-03-17T09:00:00Z,CPU usage on payments rose from 30% to 85%,A retry queue leaked references and the GC ran constantly,Fixed the leak
"""


def _import_cpu(db, memory) -> dict[str, int]:
    upload = parse_files([("cpu.csv", CPU_POSTMORTEMS.encode())], ImportSettings())
    service = CaseImportService(db, memory.indexer, memory.indexer.config)
    result = service.apply(service.plan(upload), source_files=["cpu.csv"])
    return {item.record.source_id: item.case_id for item in result.plan.items}


def test_a_new_finding_shows_the_imported_postmortem_before_any_case_exists(db_session, memory) -> None:
    from backend.app.memory.seen_before import find_seen_before

    ids = _import_cpu(db_session, memory)
    finding = _detected_checkout_cpu_finding(db_session)

    response = find_seen_before(db_session, finding, memory.similarity, memory.embedder)

    assert response.available
    first = response.matches[0]
    assert first.case_id == ids["PM-10"]
    assert first.same_service and first.origin == "imported" and first.source_id == "PM-10"
    others = [match for match in response.matches if match.case_id == ids["PM-11"]]
    assert all(not match.same_service for match in others)


def test_similar_cases_for_a_detected_case_include_possible_imported_matches(db_session, memory) -> None:
    ids = _import_cpu(db_session, memory)
    detected = _add_case(db_session, "db_pool")
    detected.finding_snapshot = {**detected.finding_snapshot, "metric_name": "cpu_usage",
                                 "summary": "CPU usage on checkout-api moved from 40% to a sustained 90%."}
    db_session.commit()
    memory.indexer.index_case(detected, db_session)

    response = memory.similarity.find_similar_cases(detected.id, db_session, minimum_score=0.4)

    by_id = {match.case_id: match for match in response.matches}
    assert ids["PM-10"] in by_id
    assert by_id[ids["PM-10"]].same_service
    assert by_id[ids["PM-10"]].strength in {"strong", "possible"}
    if ids["PM-11"] in by_id:
        assert not by_id[ids["PM-11"]].same_service
