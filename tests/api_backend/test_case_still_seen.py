"""The Resolution tab warns before Resolved when the case's problem is still being found.

Still seen: a run after the case was opened found the problem again and it was still going at the
end of that run's data. A one-off analysis, a problem that ended, or a failed check says not seen.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from tests.api_backend.test_cases import _create_finding


def _case_with_later_finding(client, **later) -> tuple[int, int | None]:
    first = _create_finding(analysis_run_id="run-seen-0", ongoing=True)
    case_id = client.post(f"/api/cases/findings/{first}/create").json()["case_id"]
    if not later:
        return case_id, None
    found = _create_finding(analysis_run_id="run-seen-1", problem_id=first, created_at=datetime.utcnow() + timedelta(minutes=10), **later)
    return case_id, found


def test_a_problem_found_again_after_the_case_was_opened_is_still_seen(client) -> None:
    case_id, later = _case_with_later_finding(client, ongoing=True)

    seen = client.get(f"/api/cases/{case_id}/still-seen").json()

    assert seen["still_seen"] is True
    assert seen["finding_id"] == later
    assert seen["seen_at"] is not None


def test_a_one_off_analysis_is_not_still_seen(client) -> None:
    # No run found it after the case was opened: nothing says it's still going.
    case_id, _ = _case_with_later_finding(client)

    assert client.get(f"/api/cases/{case_id}/still-seen").json() == {"still_seen": False, "finding_id": None, "seen_at": None}


def test_a_problem_whose_newest_run_saw_it_end_is_not_still_seen(client) -> None:
    case_id, _ = _case_with_later_finding(client, ongoing=False, event_end=datetime.utcnow())

    assert client.get(f"/api/cases/{case_id}/still-seen").json()["still_seen"] is False


def test_a_finding_of_another_problem_does_not_count(client) -> None:
    case_id, _ = _case_with_later_finding(client)
    _create_finding(analysis_run_id="run-other", title="Memory went up", ongoing=True, created_at=datetime.utcnow() + timedelta(minutes=10))

    assert client.get(f"/api/cases/{case_id}/still-seen").json()["still_seen"] is False


def test_a_failed_check_says_not_seen_instead_of_failing(client, monkeypatch) -> None:
    case_id, _ = _case_with_later_finding(client, ongoing=True)

    def broken(*_args, **_kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr("backend.app.api.cases.problem_still_seen", broken)

    response = client.get(f"/api/cases/{case_id}/still-seen")
    assert response.status_code == 200
    assert response.json()["still_seen"] is False


def test_an_unknown_case_is_404(client) -> None:
    assert client.get("/api/cases/999999/still-seen").status_code == 404


def test_viewers_may_read_it(client) -> None:
    from backend.app.roles import required_role

    assert required_role("GET", "/api/cases/12/still-seen") in (None, "Viewer")
