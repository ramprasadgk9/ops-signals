from __future__ import annotations

from benchmark.report_html import _brief_smd, _brief_ucr

# run_all --skip-methods leaves comparison methods out of a snapshot; its report must still render
# the product's own result instead of crashing on the missing ones.


def test_ucr_brief_without_the_reference_methods_reports_the_product_uncompared() -> None:
    brief = _brief_ucr({"summary": {"overall": {"series": 250, "default_rate": 0.03, "product": {"correct": 116}}}})

    assert brief["result"].startswith("116 of 250 located")
    assert brief["verdict"][0] == "warning"
    assert "skipped" in brief["verdict"][1]


def test_smd_brief_without_comparison_methods_reports_the_product_uncompared() -> None:
    ours = {"caught": 30, "incidents": 52, "false_alerts": 2490, "f1": 0.075, "hit_rate": {"100": 0.58}}
    smd = {
        "settings": {"headline_threshold": 0.5},
        "comparison": {"router_picks": {"overall": {"0.5": ours}}},
        "smd": {"machines": 5, "metrics_per_machine": 38},
    }

    brief = _brief_smd(smd)

    assert brief["result"].startswith("Caught 30 of 52 incidents")
    assert brief["verdict"][0] == "warning"
    assert "skipped" in brief["verdict"][1]
