"""Monitoring coverage: which imported incidents Ops Signals detected, flagged something else for,
missed, or wasn't watching - with the real embedder and in-memory Qdrant (test_memory_recall
fixtures). Each incident below is built to land in one status. Skipped without the model."""

from __future__ import annotations

from datetime import datetime, timedelta

from backend.app.case_import.parsers import ImportSettings, parse_files
from backend.app.case_import.service import CaseImportService
from backend.app.memory.coverage import build_coverage_report
from backend.app.models.entities import AnalysisRunEntity, FindingEntity, OperationalCaseEntity, SignalEntity
from tests.api_backend.test_memory_recall import _add_case, embedder, memory  # noqa: F401

NOW = datetime(2026, 10, 6, 12, 0)
POSTMORTEMS = """id,title,service,started_at,resolved_at,symptom,root_cause,fix,outcome
CPU-1,Checkout CPU pinned after release,checkout-api,2026-09-01T10:00:00Z,2026-09-01T12:00:00Z,CPU on checkout went from 40% to a sustained 95% after the v3.1 release,Hot loop in the new pricing code,Rolled back v3.1,CPU back to normal
LAT-1,Checkout slow after release,checkout-api,2026-09-05T10:00:00Z,2026-09-05T11:00:00Z,p95 latency on checkout rose from 200ms to 900ms,Slow query after an index was dropped,Recreated the index,Latency recovered
ERR-1,Login failures after certificate expiry,auth-svc,2026-09-10T08:00:00Z,2026-09-10T09:00:00Z,5xx errors on login,TLS certificate expired,Renewed the certificate,Errors stopped
DSK-1,Inventory disk full,inventory-svc,2026-09-12T06:00:00Z,2026-09-12T07:00:00Z,Disk on inventory nodes filled up and writes failed,Log rotation disabled,Re-enabled logrotate,Disk freed
CPU-2,Checkout CPU high again,checkout-api,2026-09-20T10:00:00Z,2026-09-20T11:00:00Z,CPU on checkout climbed to 90% during the sale,Pricing cache disabled,Re-enabled the cache,CPU normal
"""


def _import(db, memory) -> dict[str, int]:
    upload = parse_files([("postmortems.csv", POSTMORTEMS.encode())], ImportSettings())
    service = CaseImportService(db, memory.indexer, memory.indexer.config)
    result = service.apply(service.plan(upload), source_files=["postmortems.csv"])
    return {item.record.source_id: item.case_id for item in result.plan.items}


def _run(db, run_id, service, metric, start, hours=4):
    db.add(AnalysisRunEntity(
        id=run_id, source_type="prometheus", provider="prometheus", service=service, metric_name=metric,
        start_time=start, end_time=start + timedelta(hours=hours), sample_count=100, status="completed",
    ))
    db.commit()


def _finding(db, run_id, service, metric, title, summary, signal_at=None):
    signal_ids = []
    if signal_at is not None:
        signal_id = f"sig-{run_id}-{len(title)}"
        db.add(SignalEntity(
            signal_id=signal_id, signal_type="baseline_shift", metric_name=metric, service=service,
            start_time=signal_at, end_time=signal_at + timedelta(minutes=30),
        ))
        signal_ids = [signal_id]
    finding = FindingEntity(
        analysis_run_id=run_id, service=service, metric_name=metric, title=title, summary=summary,
        category="baseline_shift", health_status="significant", importance_score=0.8, signal_ids=signal_ids, comparison_json={},
        created_at=NOW,
    )
    db.add(finding)
    db.commit()
    return finding


def _scenario(db, memory):
    ids = _import(db, memory)
    # CPU-1: watched, and a CPU finding while it happened -> detected.
    _run(db, "run-cpu1", "checkout-api", "cpu_usage", datetime(2026, 9, 1, 9))
    detected = _finding(db, "run-cpu1", "checkout-api", "cpu_usage", "cpu_usage experienced a persistent baseline shift",
                        "Sustained increase in cpu_usage on checkout-api.", signal_at=datetime(2026, 9, 1, 10, 20))
    # LAT-1: watched, but only an unrelated memory finding was raised -> flagged something else.
    _run(db, "run-lat1", "checkout-api", "container_memory_working_set_bytes", datetime(2026, 9, 5, 9))
    other = _finding(db, "run-lat1", "checkout-api", "container_memory_working_set_bytes", "container_memory_working_set_bytes has unusual activity",
                     "Short spike in memory working set on checkout-api.", signal_at=datetime(2026, 9, 5, 10, 10))
    # ERR-1: auth-svc was analysed, nothing flagged -> missed.
    _run(db, "run-err1", "auth-svc", "http_requests_errors_total", datetime(2026, 9, 10, 7))
    # DSK-1: inventory-svc never analysed -> not watched.
    # CPU-2: watched, but the only CPU finding's anomaly was days earlier -> missed.
    _run(db, "run-cpu2", "checkout-api", "cpu_usage", datetime(2026, 9, 17), hours=24 * 4)
    _finding(db, "run-cpu2", "checkout-api", "cpu_usage", "cpu_usage is trending in one direction",
             "cpu_usage on checkout-api has been rising steadily.", signal_at=datetime(2026, 9, 17, 6))
    return ids, detected, other


def _by_case(report) -> dict[int, object]:
    return {incident.case_id: incident for incident in report.incidents}


def test_each_past_incident_gets_what_monitoring_did_about_it(db_session, memory):
    ids, detected, other = _scenario(db_session, memory)

    report = build_coverage_report(db_session, memory.embedder, memory.similarity.vector_store, now=NOW)

    assert report.available and report.incidents_considered == 5
    incidents = _by_case(report)
    assert incidents[ids["CPU-1"]].status == "detected"
    assert incidents[ids["CPU-1"]].evidence[0].id == detected.id
    assert incidents[ids["LAT-1"]].status == "flagged_other"
    assert incidents[ids["LAT-1"]].evidence[0].title == other.title
    assert incidents[ids["ERR-1"]].status == "missed"
    assert incidents[ids["DSK-1"]].status == "not_watched"
    # An anomaly days before the incident doesn't count as catching it.
    assert incidents[ids["CPU-2"]].status == "missed"
    assert report.counts == {"missed": 2, "not_watched": 1, "flagged_other": 1, "unknown": 0, "detected": 1}
    # Gaps come first, most recent first.
    assert [incident.status for incident in report.incidents] == ["missed", "missed", "not_watched", "flagged_other", "detected"]
    assert report.incidents[0].case_id == ids["CPU-2"]
    checkout = next(row for row in report.services if row.service == "checkout-api")
    assert checkout.counts["detected"] == 1 and checkout.counts["missed"] == 1 and checkout.counts["flagged_other"] == 1


def test_a_miss_says_when_the_same_problem_has_been_detected_since(db_session, memory, monkeypatch):
    ids, _, _ = _scenario(db_session, memory)
    from tests.api_backend.test_memory_recall import CATALOG

    monkeypatch.setitem(CATALOG, "auth_5xx", dict(
        service="auth-svc", metric="http_requests_errors_total", title="auth-svc login 5xx errors",
        summary="5xx errors on login on auth-svc.", root_cause="Certificate expired.", fix="Renewed it.", outcome="Errors stopped.",
    ))
    later = _add_case(db_session, "auth_5xx")
    memory.indexer.index_case(later, db_session)

    incident = _by_case(build_coverage_report(db_session, memory.embedder, memory.similarity.vector_store, now=NOW))[ids["ERR-1"]]

    assert incident.status == "missed"
    assert incident.seen_elsewhere == 1 and incident.seen_elsewhere_case_id == later.id
    assert "analyzers can catch it now" in incident.explanation


def test_a_postmortem_without_a_start_time_cant_be_checked(db_session, memory):
    _import(db_session, memory)
    case = db_session.query(OperationalCaseEntity).first()
    case.finding_snapshot = {**case.finding_snapshot, "started_at": None}
    db_session.commit()

    incident = _by_case(build_coverage_report(db_session, memory.embedder, now=NOW))[case.id]

    assert incident.status == "unknown" and "start time" in incident.explanation


def test_nothing_imported_says_how_to_get_a_report(db_session, memory):
    report = build_coverage_report(db_session, memory.embedder, now=NOW)

    assert report.available and report.incidents == [] and "Import postmortems" in report.reason


def test_the_endpoint_says_when_memory_is_off(client):
    body = client.get("/api/memory/coverage?days=90").json()

    assert body["available"] is False and body["window_days"] == 90
