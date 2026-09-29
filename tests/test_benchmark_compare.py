from __future__ import annotations

import json
from pathlib import Path

from benchmark.report_compare import write_compare


def _snapshot(root: Path, run_id: str, commit: str, default_status: str) -> Path:
    def scenario(scenario_id: str) -> dict:
        return {
            "scenario": {"id": scenario_id, "name": scenario_id, "path": "x"},
            "evaluation": {"status": "PASS", "analyzers_by_metric": {"cpu": ["a", "b", "c"]}},
            "default_mode_evaluation": {"status": default_status, "analyzers_by_metric": {"cpu": ["a"]}},
        }

    path = root / run_id
    path.mkdir()
    results = {
        "run_id": run_id,
        "fingerprint": "f",
        "manifest": {"started_at": "2026-09-27T00:00:00+00:00", "git": {"commit": commit, "branch": "b", "dirty": False}},
        "suites": {"behavior": {"scenarios": [scenario("one"), scenario("two")], "counts": {"PASS": 2}, "default_mode_counts": {default_status: 2}}},
    }
    (path / "results.json").write_text(json.dumps(results), encoding="utf-8")
    return path


def test_compare_page_shows_router_picks_before_and_after_in_one_file(tmp_path: Path) -> None:
    before = _snapshot(tmp_path, "run-before", "a" * 40, "FAIL")
    after = _snapshot(tmp_path, "run-after", "b" * 40, "PASS")

    output = write_compare(before, after)
    page = output.read_text(encoding="utf-8")

    assert output == after / "compare-run-before.html"
    assert "Router fix: before and after, on the same data" in page
    assert "<b>0 of 2</b> behaviors recognized" in page and "<b>2 of 2</b> behaviors recognized" in page
    assert "Choosing a few detectors per metric now matches or beats running all of them on 1 of 1 datasets, up from 0." in page
    assert "Nothing else moved." in page
    assert "../run-before/report-routing.html" in page
    assert "New here? The story in plain words" in page
    assert "No description of this change was provided" in page


def test_compare_page_tells_the_change_story_from_change_yaml(tmp_path: Path) -> None:
    before = _snapshot(tmp_path, "run-before", "a" * 40, "FAIL")
    after = _snapshot(tmp_path, "run-after", "b" * 40, "PASS")
    (after / "change.yaml").write_text(
        "problem:\n  - 'The router **ignored** spikes.'\nchange:\n  - 'Spikes get a detector.'\nexpected:\n  - 'More spikes found.'\n",
        encoding="utf-8",
    )

    page = write_compare(before, after).read_text(encoding="utf-8")

    assert "The router <b>ignored</b> spikes." in page
    assert "Spikes get a detector." in page and "More spikes found." in page
    assert "is now recognized" in page


def test_compare_page_takes_its_title_and_expected_changes_from_change_yaml(tmp_path: Path) -> None:
    before = _snapshot(tmp_path, "run-before", "a" * 40, "FAIL")
    after = _snapshot(tmp_path, "run-after", "b" * 40, "PASS")
    (after / "change.yaml").write_text(
        "headline: 'Spike fix: before and after'\nchanged: 'the spike rule'\naffected_methods: [router_picks, all_analyzers]\n",
        encoding="utf-8",
    )

    page = write_compare(before, after).read_text(encoding="utf-8")

    assert "<h1>Spike fix: before and after</h1>" in page
    assert "the spike rule" in page
