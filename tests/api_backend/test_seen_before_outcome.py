"""Each past-case match carries what the one-line outcome on the Seen before panel needs: the
case's status, whether its cause was verified, when it was opened, and its latest guided
investigation. The end-to-end tests reuse the fixtures from test_memory_recall.py and are skipped
when the embedding model can't be loaded."""

from __future__ import annotations

from datetime import datetime

from backend.app.memory.match_investigations import latest_investigations
from backend.app.memory.seen_before import find_seen_before
from backend.app.models.entities import FindingEntity, InvestigationEntity
from tests.api_backend.test_memory_recall import CATALOG, _add_case, embedder, memory  # noqa: F401


def _investigation(db, *, finding_id: int, case_id: int | None = None, ending: str | None = "found", summary: str | None = None) -> InvestigationEntity:
    row = InvestigationEntity(finding_id=finding_id, case_id=case_id, status="done", ending=ending, summary=summary)
    db.add(row)
    db.commit()
    return row


def _new_finding_like(db, key: str) -> FindingEntity:
    spec = CATALOG[key]
    finding = FindingEntity(
        analysis_run_id=f"run-new-{key}", service=spec["service"], metric_name=spec["metric"],
        title=spec["title"], summary=spec["summary"], category="baseline_shift", health_status="significant",
        importance_score=0.8, investigation_priority=2, signal_ids=[], comparison_json={}, created_at=datetime.utcnow(),
    )
    db.add(finding)
    db.commit()
    return finding


def test_latest_investigation_is_found_by_case_or_by_the_cases_finding(db_session) -> None:
    linked = _add_case(db_session, "db_pool", resolved=False)
    before_case = _add_case(db_session, "auth_cert", resolved=False)
    none = _add_case(db_session, "inventory_disk", resolved=False)
    _investigation(db_session, finding_id=linked.finding_id, case_id=linked.id, summary="older")
    _investigation(db_session, finding_id=linked.finding_id, case_id=linked.id, summary="newer")
    # Run from the finding before the case existed: no case_id yet.
    _investigation(db_session, finding_id=before_case.finding_id, ending="nothing_found")

    latest = latest_investigations(db_session, [linked, before_case, none])

    assert latest[linked.id].summary == "newer"
    assert latest[before_case.id].ending == "nothing_found"
    assert none.id not in latest


def test_latest_investigations_with_no_cases_is_empty(db_session) -> None:
    assert latest_investigations(db_session, []) == {}


def test_seen_before_match_says_status_verification_date_and_investigation(db_session, memory) -> None:
    fixed = _add_case(db_session, "db_pool")
    memory.indexer.index_case(fixed, db_session)
    open_case = _add_case(db_session, "db_pool", resolved=False)
    memory.indexer.index_case(open_case, db_session)
    _investigation(db_session, finding_id=open_case.finding_id, case_id=open_case.id, summary="Pointed at deploy v1.4.2.")

    response = find_seen_before(db_session, _new_finding_like(db_session, "db_pool"), memory.similarity, memory.embedder)

    by_id = {match.case_id: match for match in response.matches}
    for copy in [copy for match in response.matches for copy in match.more_like_this]:
        by_id.setdefault(copy.case_id, copy)
    assert by_id[fixed.id].case_status == "resolved"
    assert by_id[fixed.id].rca_verified is True
    assert by_id[fixed.id].opened_at is not None
    assert by_id[fixed.id].investigation_ending is None
    assert by_id[open_case.id].case_status == "open"
    assert by_id[open_case.id].rca_verified is False
    assert by_id[open_case.id].investigation_ending == "found"
    assert by_id[open_case.id].investigation_summary == "Pointed at deploy v1.4.2."


def test_similar_cases_match_carries_the_investigation(db_session, memory) -> None:
    source = _add_case(db_session, "db_pool")
    memory.indexer.index_case(source, db_session)
    other = _add_case(db_session, "db_pool", resolved=False)
    memory.indexer.index_case(other, db_session)
    _investigation(db_session, finding_id=other.finding_id, ending="nothing_found")

    response = memory.similarity.find_similar_cases(source.id, db_session, minimum_score=0.3)

    matches = {match.case_id: match for match in response.matches}
    for copy in [copy for match in response.matches for copy in match.more_like_this]:
        matches.setdefault(copy.case_id, copy)
    assert matches[other.id].investigation_ending == "nothing_found"
    assert matches[other.id].opened_at is not None
