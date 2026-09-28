from __future__ import annotations

from benchmark import harness
from benchmark.methods import ALL_ANALYZERS, LABELS, ROUTER_PICKS
from benchmark.report_html import _routing_row_verdict, routing_comparison
from intelligence.pipeline import SignalPipeline


def _cell(value: float, analyzer_runs: int) -> dict:
    return {"text": "", "value": value, "analyzer_runs": analyzer_runs, "seconds": 1.0}


def test_harness_builds_the_product_pipeline_by_default_and_runs_everything_on_request() -> None:
    router = harness.build_pipeline(5, "m")
    everything = harness.build_pipeline(5, "m", ALL_ANALYZERS)
    only = harness.build_pipeline(5, "m", ("anomaly_zscore",))

    assert router.config.analysis.selection_mode == "recommended_threshold"
    assert everything.config.analysis.selection_mode == "all"
    assert type(everything) is SignalPipeline
    assert [a.analyzer_id for a in only._build_analyzers([])] == ["anomaly_zscore"]


def test_router_matching_everything_with_fewer_runs_is_good() -> None:
    kind, text = _routing_row_verdict({"router_picks": _cell(0.99, 30), "all_analyzers": _cell(1.0, 100)})

    assert kind == "good"
    assert text == "Matches running everything, with 70.0% fewer analyzer runs."


def test_router_behind_everything_is_critical() -> None:
    kind, text = _routing_row_verdict({"router_picks": _cell(0.5, 30), "all_analyzers": _cell(1.0, 100)})

    assert kind == "critical"
    assert text.startswith("Behind running everything")


def test_a_simple_baseline_beating_the_router_is_called_out() -> None:
    kind, text = _routing_row_verdict(
        {"router_picks": _cell(1.0, 30), "all_analyzers": _cell(1.0, 100), "zscore_only": _cell(2.0, 10), "static_threshold": _cell(0.1, 0)}
    )

    assert kind == "warning"
    assert text.endswith("Z-score only scores higher than router picks.")


def test_behavior_suite_compares_router_picks_with_all_analyzers() -> None:
    def scenario(all_status: str, default_status: str) -> dict:
        return {
            "evaluation": {"status": all_status, "analyzers_by_metric": {"cpu": ["a", "b", "c"]}},
            "default_mode_evaluation": {"status": default_status, "analyzers_by_metric": {"cpu": ["a"]}},
        }

    rows = routing_comparison({"behavior": {"scenarios": [scenario("PASS", "FAIL"), scenario("PASS", "PASS")], "default_mode_counts": {}}})

    assert len(rows) == 1
    cells = rows[0]["cells"]
    assert set(cells) == {ROUTER_PICKS, ALL_ANALYZERS}
    assert (cells[ROUTER_PICKS]["value"], cells[ALL_ANALYZERS]["value"]) == (1.0, 2.0)
    assert rows[0]["verdict"][0] == "critical"
    assert LABELS[ROUTER_PICKS] == "Ops Signals, router picks"
