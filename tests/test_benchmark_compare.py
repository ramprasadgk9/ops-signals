from __future__ import annotations

import json
from pathlib import Path

from benchmark.report_compare import _cost_table, _match_sentence, write_compare


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


def _row(suite: str, with_all_analyzers: bool) -> dict:
    def side() -> dict:
        cells = {"router_picks": {"value": 0.5, "analyzer_runs": 10, "seconds": 1.0}}
        if with_all_analyzers:
            cells["all_analyzers"] = {"value": 0.6, "analyzer_runs": 30, "seconds": 2.0}
        return {"cells": cells, "verdict": ("warning", "Behind running everything.")}

    return {"suite": suite, "before": side(), "after": side()}


def test_compare_page_counts_routing_matches_only_where_all_analyzers_ran() -> None:
    # run_all --skip-methods all_analyzers leaves NAB and UCR with nothing to compare routing against
    rows = [_row("nab", False), _row("ucr", False), _row("tcpd", True)]

    assert _match_sentence(rows) == (
        "Choosing a few detectors per metric now matches or beats running all of them on 0 of 1 datasets where running all of them "
        "was measured, up from 0."
    )
    assert _match_sentence(rows[:2]) == "Running every analyzer wasn't measured in these runs, so routing isn't compared with it here."


def test_compare_cost_table_renders_when_all_analyzers_was_skipped() -> None:
    table = _cost_table([_row("nab", False), _row("tcpd", True)])

    assert "<td>NAB</td><td class='num'>10</td><td class='num'>10</td><td class='num'>-</td>" in table
    assert "<td class='num'>30</td>" in table
