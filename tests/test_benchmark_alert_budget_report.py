from __future__ import annotations

import json
from pathlib import Path

from benchmark.report_html import _nab_alert_budget


def _alert_budget(live_caught: tuple[int, int]) -> dict:
    """Two settings per method: a quiet one (10 alerts) and the usual one (30 alerts)."""
    def curve(quiet: int, usual: int) -> list[dict]:
        return [{"setting": 0.9, "alerts": 10, "caught": quiet}, {"setting": 0.5, "alerts": 30, "caught": usual}]

    curves = {
        "live": curve(*live_caught),
        "batch": curve(4, 6),
        "static_threshold": [{"setting": 0.3, "alerts": 10, "caught": 3}, {"setting": 0.0, "alerts": 40, "caught": 7}],
    }
    usual = {"live": curves["live"][1], "batch": curves["batch"][1], "static_threshold": curves["static_threshold"][1]}
    budgets = [{"alerts": b, "caught": {m: max([p["caught"] for p in c if p["alerts"] <= b], default=None) for m, c in curves.items()}}
               for b in (10, 30, 40)]
    labels = {"live": "Ops Signals, live alerts", "batch": "Ops Signals, batch review", "static_threshold": "Static threshold"}
    return {"windows": 10, "labels": labels, "curves": curves, "usual": usual, "budgets": budgets}


def test_the_nab_report_charts_the_alert_budget_and_counts_wins_against_the_threshold() -> None:
    html = _nab_alert_budget({"alert_budget": _alert_budget((5, 6)), "settings": {"headline_threshold": 0.5}})

    assert "The fair test: the same number of alerts" in html
    assert "<svg class=\"budget\"" in html
    # live: 10 alerts 5 vs 3, 30 alerts 6 vs 3 -> more; 40 alerts 6 vs 7 -> fewer
    assert "catches more incidents than the best threshold at 2 of 3 alert budgets, as many at 0, and fewer at 1." in html
    assert "Ops Signals uses its confidence cutoff" in html


def test_a_run_without_alert_budget_data_leaves_the_section_out() -> None:
    assert _nab_alert_budget({"settings": {"headline_threshold": 0.5}}) == ""


def _snapshot(root: Path, run_id: str, live_caught: tuple[int, int]) -> Path:
    path = root / run_id
    path.mkdir()
    results = {
        "run_id": run_id,
        "fingerprint": "f",
        "manifest": {"started_at": "2026-09-30T00:00:00+00:00", "git": {"commit": "a" * 40, "branch": "b", "dirty": False}},
        "suites": {"nab": {"alert_budget": _alert_budget(live_caught)}},
    }
    (path / "results.json").write_text(json.dumps(results), encoding="utf-8")
    return path


def test_the_comparison_page_shows_before_and_after_at_the_same_alert_budgets(tmp_path: Path) -> None:
    from benchmark.report_compare import _alert_budget_changes, load_snapshot

    before = load_snapshot(_snapshot(tmp_path, "before", (3, 6)))
    after = load_snapshot(_snapshot(tmp_path, "after", (5, 6)))

    html = _alert_budget_changes(before, after)

    assert "NAB at the same number of alerts, before and after" in html
    assert "<b>Ops Signals, live alerts</b>: more incidents caught at 1 budget, the same at 2, fewer at 0." in html
