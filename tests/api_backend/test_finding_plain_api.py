"""Findings carry plain wording (`plain`) next to their unchanged title and summary."""

from __future__ import annotations

import io
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import FindingEntity, SignalEntity
from backend.app.services.finding_plain import utc_text

REAL = {item["id"]: item for item in json.loads((Path(__file__).parents[1] / "fixtures" / "plain_findings_real.json").read_text(encoding="utf-8"))}


def _time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _seed(db, finding_id: int, created_at: datetime) -> None:
    item = REAL[finding_id]
    for signal in item["signals"]:
        db.add(
            SignalEntity(
                signal_id=signal["signal_id"],
                signal_type=signal["signal_type"],
                analyzer_id=signal["analyzer_id"],
                metric_name=item["metric_name"],
                service=item["service"],
                severity="high",
                start_time=_time(signal["start_time"]),
                end_time=_time(signal["end_time"]),
                evidence_json=signal["evidence"],
                importance_score=0.7,
                analysis_run_id=item["analysis_run_id"],
            )
        )
    db.add(
        FindingEntity(
            id=finding_id,
            analysis_run_id=item["analysis_run_id"],
            service=item["service"],
            metric_name=item["metric_name"],
            title=item["title"],
            summary=item["summary"],
            category=item["category"],
            health_status="significant",
            importance_score=0.7,
            investigation_priority=2,
            signal_ids=[signal["signal_id"] for signal in item["signals"]],
            comparison_json=item["comparison_json"],
            event_start=_time(item["event_start"]),
            event_end=_time(item["event_end"]),
            created_at=created_at,
        )
    )


@pytest.fixture()
def seeded(client: TestClient) -> TestClient:
    now = datetime.now(timezone.utc)
    with get_session_local()() as db:
        # 8300 and 8299 changed at the same moment but were found by runs 35 s apart.
        _seed(db, 8300, now)
        _seed(db, 8299, now - timedelta(seconds=35))
        _seed(db, 8305, now)
        db.add(FindingEntity(id=1, service="cart", metric_name="cpu_usage", title="cpu_usage has unusual behaviour.", summary="as stored", category="operational_insight",
                             health_status="normal", importance_score=0.2, investigation_priority=3, signal_ids=[], comparison_json={}, created_at=now))
        db.commit()
    return client


def test_findings_list_carries_plain_wording_and_keeps_title_and_summary(seeded: TestClient) -> None:
    by_id = {item["id"]: item for item in seeded.get("/api/findings").json()}

    errors = by_id[8300]
    assert errors["title"] == REAL[8300]["title"]
    assert errors["summary"] == REAL[8300]["summary"]
    plain = errors["plain"]
    assert (plain["kind"], plain["badge"], plain["badge_label"]) == ("level_change", "better", "Better")
    assert plain["headline"] == "Error rate dropped sharply and stayed lower"
    assert utc_text(plain["what"]) == "About 11.3% until Oct 19, 22:54 UTC. Since then about 1.2% (down 89%)."
    assert plain["change_time"] == "[[time:2026-10-19T22:54:17Z]]"

    assert by_id[8305]["plain"]["badge"] == "gap"
    # Not enough evidence: no plain wording, the card shows the stored summary.
    assert by_id[1]["plain"] is None


def test_changes_found_by_different_runs_at_the_same_moment_are_linked(seeded: TestClient) -> None:
    by_id = {item["id"]: item for item in seeded.get("/api/findings").json()}
    assert [item["finding_id"] for item in by_id[8300]["plain"]["related"]] == [8299]
    assert [item["finding_id"] for item in by_id[8299]["plain"]["related"]] == [8300]


def test_a_single_finding_links_to_one_that_was_not_requested(seeded: TestClient) -> None:
    plain = seeded.get("/api/findings/8300").json()["plain"]
    assert [item["finding_id"] for item in plain["related"]] == [8299]
    assert utc_text(plain["related"][0]["text"]) == "Slow-request time (p95) also dropped at Oct 19, 22:54 UTC (571 ms to 357 ms)."


def test_search_results_carry_plain_wording(seeded: TestClient) -> None:
    results = seeded.get("/api/findings/search", params={"q": "error_rate", "window": "24h"}).json()
    assert [item["id"] for item in results] == [8300]
    assert results[0]["plain"]["headline"] == "Error rate dropped sharply and stayed lower"


def test_a_broken_wording_file_leaves_every_finding_on_its_summary(seeded: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    broken = tmp_path / "finding_templates.yaml"
    broken.write_text("templates: [unclosed", encoding="utf-8")
    monkeypatch.setattr("backend.app.services.finding_plain.TEMPLATES_PATH", broken)
    response = seeded.get("/api/findings")
    assert response.status_code == 200
    assert all(item["plain"] is None for item in response.json())
    assert {item["summary"] for item in response.json()} >= {REAL[8300]["summary"]}


def test_csv_validation_findings_carry_plain_wording() -> None:
    rng = random.Random(7)
    values = [0.11 + rng.gauss(0, 0.004) for _ in range(150)] + [0.012 + rng.gauss(0, 0.002) for _ in range(150)]
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    rows = ["timestamp,metric_name,value"] + [f"{(start + timedelta(minutes=5 * index)).strftime('%Y-%m-%dT%H:%M:%SZ')},error_rate,{value:.4f}" for index, value in enumerate(values)]
    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
        response = client.post(
            "/api/ingestion/csv-validate",
            data={"provider": "generic", "analyzer_id": "all", "service": "checkout", "metric_name": "error_rate"},
            files={"file": ("upload.csv", io.BytesIO("\n".join(rows).encode("utf-8")), "text/csv")},
        )
    assert response.status_code == 200, response.text
    plain = [finding["plain"] for finding in response.json()["findings"] if finding["plain"]]
    assert plain, response.json()["findings"]
    assert any(item["badge"] == "better" and "Error rate dropped" in item["headline"] for item in plain), plain


def test_service_context_from_the_wording_file_reaches_the_api(seeded: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import yaml

    from backend.app.services.finding_plain import TEMPLATES_PATH

    raw = yaml.safe_load(TEMPLATES_PATH.read_text(encoding="utf-8"))
    raw["services"] = {"spike-lab": {"about": "Lab traffic for demos.", "importance": "low", "targets": {"error_rate": {"below": 0.05}}}}
    path = tmp_path / "finding_templates.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    monkeypatch.setattr("backend.app.services.finding_plain.TEMPLATES_PATH", path)

    plain = seeded.get("/api/findings/8300").json()["plain"]

    assert utc_text(plain["target"]) == "Back within your 5% target since Oct 19, 22:54 UTC."
    assert (plain["service_about"], plain["service_importance"], plain["service_importance_label"]) == ("Lab traffic for demos.", "low", "Low-impact service")
    # The latency finding on the same service has no target set.
    assert seeded.get("/api/findings/8299").json()["plain"]["target"] is None
