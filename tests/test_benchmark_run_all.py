from __future__ import annotations

import json
from pathlib import Path

from benchmark import run_all
from benchmark.report_html import render


def test_fingerprint_ignores_wall_clock_timings_but_not_results() -> None:
    suites = {
        "router": {"counts": {"PASS": 1}, "scenarios": [{"evaluation": {"status": "PASS"}}]},
        "performance": {
            "datasets": [
                {
                    "dataset_label": "24h",
                    "normalization_seconds": 0.01,
                    "total_seconds": 0.02,
                    "analyzers": [{"analyzer_id": "trend", "elapsed_seconds": 0.001, "signal_count": 1}],
                }
            ]
        },
    }
    slower = json.loads(json.dumps(suites))
    slower["performance"]["datasets"][0]["total_seconds"] = 9.0
    slower["performance"]["datasets"][0]["analyzers"][0]["elapsed_seconds"] = 5.0
    changed = json.loads(json.dumps(suites))
    changed["router"]["scenarios"][0]["evaluation"]["status"] = "FAIL"

    assert run_all.accuracy_fingerprint(suites) == run_all.accuracy_fingerprint(slower)
    assert run_all.accuracy_fingerprint(suites) != run_all.accuracy_fingerprint(changed)


def test_run_writes_results_and_report_for_selected_suite(tmp_path: Path) -> None:
    out_dir = run_all.run(["behavior"], tmp_path / "snapshot")

    results = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
    assert results["schema_version"] == run_all.SCHEMA_VERSION
    assert set(results["suites"]) == {"behavior"}
    assert results["suites"]["behavior"]["counts"] == {"PASS": 2}
    assert results["manifest"]["git"]["commit"]
    assert results["manifest"]["dataset_sha256"]
    assert run_all.exit_code(out_dir / "results.json") == 0

    html = (out_dir / "report.html").read_text(encoding="utf-8")
    assert "Cross-metric behavior suite" in html
    assert results["fingerprint"] in html
    # Suites not run in this snapshot are listed as missing rather than silently omitted.
    assert "Not included in this run" in html


def test_report_marks_router_only_analyzers_and_counts_passes_that_depend_on_them() -> None:
    scenario = {
        "scenario": {"id": "s1", "name": "Spikes", "description": "", "notes": [], "path": "benchmark/scenarios/s1"},
        "expected_router": {"required_recommended": ["pyod"]},
        "expected_event": None,
        "expects_no_actionable_findings": False,
        "evaluation": {
            "status": "PASS",
            "checks": {"required_recommended_present": True},
            "actual": {"recommended": ["pyod", "pyod_outlier"], "optional": [], "not_recommended": []},
            "actual_details": {},
            "profile": {},
        },
        "series": {},
    }
    results = {
        "run_id": "r1",
        "fingerprint": "abc",
        "manifest": {"git": {}},
        "suites": {"router": {"counts": {"PASS": 1}, "scenarios": [scenario], "executable_analyzers": ["pyod_outlier"]}},
    }

    html = render(results)

    assert "pyod†" in html
    assert "1 of the passes need a router-only analyzer" in html
