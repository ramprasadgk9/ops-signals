from __future__ import annotations

import copy

import numpy as np

from benchmark.evidence import paper
from benchmark.evidence.facts import _bootstrap, _budget_facts, _nab_f1


def _budget(live_usual: tuple[int, int]) -> dict:
    curves = {
        "live": [{"setting": 0.9, "alerts": 10, "caught": 3}, {"setting": 0.5, "alerts": live_usual[0], "caught": live_usual[1]}],
        "static_threshold": [{"setting": 0.3, "alerts": 10, "caught": 4}, {"setting": 0.0, "alerts": 40, "caught": 7}],
    }
    budgets = [{"alerts": b, "caught": {m: max([p["caught"] for p in c if p["alerts"] <= b], default=None) for m, c in curves.items()}}
               for b in (10, 30, 40)]
    return _budget_facts({"windows": 10, "labels": {"live": "Ops Signals, live alerts", "static_threshold": "Static threshold"},
                          "curves": curves, "usual": {"live": curves["live"][1], "static_threshold": curves["static_threshold"][1]},
                          "budgets": budgets})


def _facts(*, live_caught: int = 8, budget=None) -> dict:
    method = lambda label, caught, alerts, real: {  # noqa: E731
        "label": label, "caught": caught, "windows": 10, "flags": alerts, "false_flags": alerts - real, "precision": real / alerts,
        "recall": caught / 10, "f1": 0.4, "f1_ci": (0.3, 0.5), "alerts": {"alerts": alerts, "real": real, "false": alerts - real}, "cost": None}
    return {
        "run": {"run_id": "run-1", "commit": "a" * 40, "commit_date": None, "dirty_files": [], "started_at": None, "finished_at": None,
                "hours": 1.0, "command": "python -m benchmark.run_all", "sample": None, "skipped_methods": [], "python": "3.14",
                "platform": "x", "cpu": "y", "packages": {}, "config_sha256": {}, "dataset_sha256": {}, "fingerprint": "f", "suites": ["nab"]},
        "nab": {"settings": {}, "series": 5, "windows": 10, "categories": ["realTweets"],
                "methods": {"static_threshold": method("Static threshold", 9, 40, 8), "live": method("Ops Signals, live alerts", live_caught, 20, 8)},
                "paired_f1_vs": {"static_threshold": (-0.1, 0.2)}, "official": None, "budget": budget,
                "category_gaps": [{"category": "realTweets", "threshold_only": 2, "ours_only": 1, "windows": 10}]},
        "ucr": {"settings": {}, "series": 50, "random": 1.5, "correct": {"product": 26, "static_threshold": 11, "anomaly_zscore": 4},
                "product_ci": (19, 33), "found_anywhere": 40, "timeouts": 0, "found_by": {"stumpy": 26},
                "only_ours": 18, "both": 8, "only_threshold": 3, "paired_vs_threshold": (7, 23)},
        "tcpd": None, "smd": None, "behavior": None, "router": None, "analyzers": [], "choices": [], "routing": [],
    }


def test_the_publication_report_renders_without_optional_suites() -> None:
    facts = copy.deepcopy(_facts())
    facts["ucr"] = None

    assert "1. Setup" in paper.render(facts) and "3. UCR" not in paper.render(facts)


def test_the_publication_summary_states_the_paired_interval_in_words() -> None:
    html = paper.render(_facts())

    assert "[-0.100, 0.200], within series-to-series variation" in html


def test_bootstrap_intervals_are_reproducible_and_paired_differences_center_on_the_gap() -> None:
    rows = np.array([[1, 1, 2, 4], [0, 1, 0, 3], [1, 2, 3, 5], [2, 2, 4, 6]], dtype=float)

    assert _bootstrap(rows, _nab_f1) == _bootstrap(rows, _nab_f1)
    low, high = _bootstrap(np.hstack([rows, rows]), lambda r: _nab_f1(r[:, :4]) - _nab_f1(r[:, 4:]))
    assert low == high == 0.0
