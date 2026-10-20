from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

import intelligence.analyzer_selection as analyzer_selection
from intelligence.config import AnalyzerConfig, load_config
from intelligence.findings.schema import OperationalFinding
from intelligence.pipeline import SignalPipeline
from intelligence.signals.schema import OperationalSignal
from tests.test_csv_pipeline import InMemoryStore, StubEmbedder

# Why each analyzer ran or didn't is recorded on its execution snapshot (`run_reason`), so the web
# UI and the Grafana plugin can say "Router pick", "Covers spikes" or "Runs on every series"
# instead of showing "Not Recommended" next to an analyzer that ran.

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _pipeline(selection_mode: str = "recommended_threshold") -> SignalPipeline:
    config = load_config(PROJECT_ROOT / "config.yaml")
    config.analysis.selection_mode = selection_mode
    return SignalPipeline(config=config, store=InMemoryStore(), embedder=StubEmbedder())


def _decision(analyzer_id: str, recommendation: str, score: float, matched: list[str] | None = None, detected: list[str] | None = None) -> dict:
    return {
        "analyzer_id": analyzer_id,
        "display_name": analyzer_id,
        "recommendation": recommendation,
        "final_score": score,
        "matched_profiles": matched or [],
        "parameters_tested": {"detected_profiles": detected or []},
    }


# The router's view of the series in the screenshot that prompted this: a baseline shift with a
# trend and spikes, where ADTK/Kats/PyOD score high but have no pipeline analyzer behind them.
DETECTED = ["baseline_shift", "regime_change", "trend", "spike", "outlier", "anomaly"]
ROUTING = [
    _decision("ruptures", "RECOMMENDED", 1.0, ["baseline_shift", "regime_change", "trend"], DETECTED),
    _decision("pyod", "RECOMMENDED", 1.0, ["anomaly", "outlier"], DETECTED),
    _decision("adtk", "RECOMMENDED", 0.96, ["outlier", "spike"], DETECTED),
    _decision("trend_regression", "RECOMMENDED", 0.90, ["trend"], DETECTED),
    _decision("kats", "RECOMMENDED", 0.82, ["anomaly", "baseline_shift"], DETECTED),
    _decision("pyod_outlier", "OPTIONAL", 0.78, ["anomaly", "outlier", "spike"], DETECTED),
    _decision("river", "OPTIONAL", 0.61, [], DETECTED),
    _decision("stumpy", "NOT_RECOMMENDED", 0.42, [], DETECTED),
    _decision("data_health", "NOT_RECOMMENDED", 0.30, [], DETECTED),
    _decision("prophet", "REJECTED", 0.0, [], DETECTED),
]


def test_selection_records_why_each_analyzer_was_chosen() -> None:
    reasons = _pipeline()._selection_reasons(ROUTING)

    assert reasons == {
        "ruptures": "router_pick",
        "trend_regression": "router_pick",
        "pyod_outlier": "covers_shape",
        "stumpy": "always_run",
        "data_health": "always_run",
    }


def test_selection_reasons_match_the_selected_ids() -> None:
    pipeline = _pipeline()

    assert pipeline._selected_router_analyzers(ROUTING) == set(pipeline._selection_reasons(ROUTING) or {})


def test_selection_reasons_are_none_when_every_analyzer_runs() -> None:
    assert _pipeline("all")._selection_reasons(ROUTING) is None


def test_manual_override_marks_settings_choices() -> None:
    pipeline = _pipeline("manual_override")
    pipeline.config.analysis.selected_analyzers = ["anomaly_zscore"]

    reasons = pipeline._selection_reasons(ROUTING) or {}

    assert reasons["ruptures"] == "router_pick"
    assert reasons["anomaly_zscore"] == "chosen_in_settings"


def test_snapshots_say_why_analyzers_ran(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analyzer_selection, "library_installed", lambda name: False)
    pipeline = _pipeline()
    selected = pipeline._selected_router_analyzers(ROUTING)

    snapshots = pipeline._executed_analyzer_snapshots(
        ROUTING,
        ["ruptures", "trend", "pyod_outlier", "stumpy", "data_health"],
        selected_analyzers=selected,
    )

    by_id = {item["router_analyzer_id"]: item for item in snapshots}
    assert by_id["ruptures"]["run_reason"] == "router_pick"
    assert by_id["ruptures"]["execution_reason"] == "Picked by the router for this series."
    assert by_id["trend_regression"]["run_reason"] == "router_pick"
    assert by_id["pyod_outlier"]["run_reason"] == "covers_shape"
    assert by_id["pyod_outlier"]["shapes"] == ["spike"]
    assert by_id["pyod_outlier"]["execution_reason"] == "Ran to cover the spikes the router detected."
    assert by_id["stumpy"]["execution_status"] == "completed"
    assert by_id["stumpy"]["run_reason"] == "always_run"
    assert by_id["stumpy"]["execution_reason"] == "Runs on every series."
    assert by_id["data_health"]["run_reason"] == "always_run"


def test_snapshots_say_why_analyzers_did_not_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analyzer_selection, "library_installed", lambda name: False)
    pipeline = _pipeline()
    selected = pipeline._selected_router_analyzers(ROUTING)

    snapshots = pipeline._executed_analyzer_snapshots(ROUTING, ["ruptures", "trend", "pyod_outlier"], selected_analyzers=selected)

    by_id = {item["router_analyzer_id"]: item for item in snapshots}
    for analyzer_id in ["pyod", "adtk", "kats", "river"]:
        assert by_id[analyzer_id]["execution_status"] == "skipped"
        assert by_id[analyzer_id]["run_reason"] == "not_built_in", analyzer_id
    assert by_id["prophet"]["run_reason"] == "library_missing"
    assert by_id["prophet"]["missing_library"] == "prophet"
    # The skipped wording that QA and the tests already rely on is unchanged.
    assert "no pipeline analyzer implements it" in by_id["adtk"]["execution_reason"]


def test_a_turned_off_analyzer_is_not_called_not_built_in() -> None:
    pipeline = _pipeline()
    pipeline.config.analysis.analyzers["stumpy"] = AnalyzerConfig(enabled=False, params={})

    snapshots = pipeline._executed_analyzer_snapshots([_decision("stumpy", "OPTIONAL", 0.7)], [], selected_analyzers=set())

    assert snapshots[0]["run_reason"] == "turned_off"


def test_a_ruled_out_analyzer_and_an_unchosen_one_are_told_apart() -> None:
    pipeline = _pipeline()

    snapshots = pipeline._executed_analyzer_snapshots(
        [_decision("ruptures", "REJECTED", 0.0), _decision("pyod_outlier", "OPTIONAL", 0.6)],
        [],
        selected_analyzers=set(),
    )

    by_id = {item["router_analyzer_id"]: item for item in snapshots}
    assert by_id["ruptures"]["run_reason"] == "rejected"
    assert by_id["pyod_outlier"]["run_reason"] == "not_selected"


def test_every_analyzer_that_ran_in_all_mode_counts_as_selected() -> None:
    # In "all" mode every enabled analyzer runs; an OPTIONAL one that ran used to read "skipped".
    pipeline = _pipeline("all")

    snapshots = pipeline._executed_analyzer_snapshots([_decision("pyod_outlier", "OPTIONAL", 0.6)], ["pyod_outlier"])

    assert snapshots[0]["selected"] is True
    assert snapshots[0]["execution_status"] == "completed"
    assert snapshots[0]["run_reason"] == "runs_all"


def test_an_unrouted_analyzer_that_ran_gets_its_display_name_and_reason() -> None:
    pipeline = _pipeline("all")

    snapshots = pipeline._executed_analyzer_snapshots([], ["anomaly_zscore"])

    assert snapshots[0]["display_name"] == "Z-Score Anomaly"
    assert snapshots[0]["run_reason"] == "runs_all"


def _signal(analyzer_id: str) -> OperationalSignal:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return OperationalSignal(
        signal_type="spike",
        analyzer_id=analyzer_id,
        metric_name="cpu_usage",
        service="checkout",
        env="prod",
        severity="high",
        confidence=0.9,
        start_time=start,
        end_time=start + timedelta(minutes=5),
        summary="spike",
        evidence={},
    )


def test_analyzers_whose_signals_are_in_a_finding_are_marked() -> None:
    ruptures, trend = _signal("ruptures"), _signal("trend")
    snapshots = [
        {"router_analyzer_id": "ruptures", "executed_pipeline_analyzer_ids": ["ruptures"], "in_finding": None},
        {"router_analyzer_id": "trend_regression", "executed_pipeline_analyzer_ids": ["trend"], "in_finding": None},
        {"router_analyzer_id": "kats", "executed_pipeline_analyzer_ids": [], "in_finding": None},
    ]
    finding = OperationalFinding(metric_name="cpu_usage", signal_ids=[ruptures.signal_id])

    SignalPipeline._mark_finding_contributors(snapshots, [ruptures, trend], [finding])

    assert [item["in_finding"] for item in snapshots] == [True, False, None]


def test_a_pipeline_run_records_reasons_and_finding_contributors() -> None:
    pipeline = _pipeline()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    values = [50.0 + (index % 3) * 0.4 for index in range(120)] + [80.0 + (index % 3) * 0.4 for index in range(120)]
    dataframe = pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=5 * index) for index in range(len(values))],
            "metric_name": ["cpu_usage"] * len(values),
            "value": values,
            "service": ["checkout"] * len(values),
            "env": ["prod"] * len(values),
        }
    )

    result = pipeline.run_normalized(dataframe)

    ran = [item for item in result.analyzer_executions if item["execution_status"] == "completed"]
    assert ran
    assert all(item["run_reason"] in analyzer_selection.RUN_REASON_TEXT for item in ran)
    assert all(isinstance(item["in_finding"], bool) for item in ran)
    assert any(item["in_finding"] for item in ran) == bool(result.findings)
    stored = pipeline.store.learning_snapshots[-2][1]
    assert stored["executed_analyzers_json"] is result.analyzer_executions


def test_an_aliased_analyzer_is_not_listed_twice() -> None:
    # trend_regression runs as the pipeline's trend analyzer; it used to appear again as an
    # unrouted "trend" record, so the panel counted Trend twice.
    pipeline = _pipeline()

    snapshots = pipeline._executed_analyzer_snapshots(
        [_decision("trend_regression", "RECOMMENDED", 0.9, ["trend"])],
        ["trend"],
        selected_analyzers={"trend_regression"},
    )

    assert [item["router_analyzer_id"] for item in snapshots] == ["trend_regression"]
    assert snapshots[0]["executed_pipeline_analyzer_ids"] == ["trend"]
