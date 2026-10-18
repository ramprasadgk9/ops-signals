from __future__ import annotations

from pathlib import Path

from backend.app.behavior_intelligence.correlation import evaluate_correlation
from backend.app.behavior_intelligence.fact_extractor import extract_facts
from backend.app.behavior_intelligence.finding_builder import build_evaluation
from backend.app.behavior_intelligence.loader import load_definitions

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFINITIONS = {definition.id: definition for definition in load_definitions(PROJECT_ROOT / "config" / "behavior_definitions.d")}
DAY_START = "2026-09-01T00:00:00+00:00"
DAY_END = "2026-09-01T23:55:00+00:00"


def _signal(metric: str, analyzer: str, signal_type: str, start: str, end: str | None = None, **evidence) -> dict:
    return {
        "metric_name": metric,
        "analyzer_id": analyzer,
        "signal_type": signal_type,
        "start_time": start,
        "end_time": end or start,
        "importance_score": 0.8,
        "evidence": evidence,
    }


def _at(hhmm: str) -> str:
    return f"2026-09-01T{hhmm}:00+00:00"


def _cascade(latency_signals: list[dict], error_signals: list[dict]):
    facts = {
        "latency": extract_facts(latency_signals)["request_latency_p95"],
        "errors": extract_facts(error_signals)["error_rate"],
    }
    return build_evaluation(DEFINITIONS["latency_error_cascade"], facts, facts, "svc", "run")


def _latency_spike(start: str, end: str | None = None) -> dict:
    return _signal("request_latency_p95", "pyod_outlier", "anomaly", start, end)


def _error_spike(start: str, end: str | None = None) -> dict:
    return _signal("error_rate", "pyod_outlier", "anomaly", start, end)


def _trend(metric: str) -> dict:
    return _signal(metric, "trend", "trend", DAY_START, DAY_END, slope=0.1)


def test_anomalies_hours_apart_are_not_a_cascading_failure() -> None:
    # QA-32: latency spiked at 04:10 and errors at 20:00; the definition allows 10 minutes.
    evaluation = _cascade([_latency_spike(_at("04:10"), _at("04:35"))], [_error_spike(_at("20:00"), _at("20:25"))])

    assert not evaluation.matched
    assert evaluation.correlation["closest_gap_minutes"] == 925.0


def test_overlapping_anomalies_are_a_cascading_failure() -> None:
    evaluation = _cascade([_latency_spike(_at("16:40"), _at("17:05"))], [_error_spike(_at("16:45"), _at("17:10"))])

    assert evaluation.matched
    assert evaluation.correlation["overlap_minutes"] == 20.0


def test_single_point_anomalies_within_the_gap_match_and_beyond_it_do_not() -> None:
    assert _cascade([_latency_spike(_at("10:00"))], [_error_spike(_at("10:10"))]).matched
    assert not _cascade([_latency_spike(_at("10:00"))], [_error_spike(_at("10:15"))]).matched


def test_any_pair_of_windows_close_in_time_is_enough() -> None:
    evaluation = _cascade(
        [_latency_spike(_at("02:00")), _latency_spike(_at("18:00"))],
        [_error_spike(_at("09:00")), _error_spike(_at("18:05"))],
    )

    assert evaluation.matched


def test_a_whole_window_trend_does_not_pull_a_distant_anomaly_into_the_match() -> None:
    # The trend signal spans the whole day; the conditions are about anomalies, so only the
    # anomaly windows are compared (the old check used every signal's window and always overlapped).
    evaluation = _cascade(
        [_latency_spike(_at("04:10")), _trend("request_latency_p95")],
        [_error_spike(_at("20:00")), _trend("error_rate")],
    )

    assert not evaluation.matched


def test_a_level_change_counts_from_its_change_point_to_the_end_of_the_window() -> None:
    # Memory shifted to a new level at 12:05; errors spiking at 18:00 happen while it is still there.
    definition = DEFINITIONS["memory_pressure_with_errors"]
    memory = extract_facts(
        [_signal("memory_usage", "ruptures", "ruptures", DAY_START, DAY_END, percent_change=40.0, change_point_time=_at("12:05"))]
    )["memory_usage"]
    errors_after = extract_facts([_error_spike(_at("18:00"))])["error_rate"]
    errors_before = extract_facts([_error_spike(_at("08:00"))])["error_rate"]

    assert memory["ruptures"]["windows"] == [[_at("12:05"), DAY_END]]
    for errors, expected in ((errors_after, True), (errors_before, False)):
        facts = {"memory": memory, "errors": errors}
        conditions = [
            {"fact": f"{alias}.{fact}", "passed": True}
            for alias, fact in (("memory", "ruptures.present"), ("errors", "anomaly.present"))
        ]
        correlation = evaluate_correlation({"correlation": definition.correlation}, facts, conditions)
        assert correlation["matched"] is expected


def test_minimum_overlap_alone_requires_that_much_overlap() -> None:
    facts = {
        "a": extract_facts([_signal("m1", "x", "anomaly", _at("10:00"), _at("10:20"))])["m1"],
        "b": extract_facts([_signal("m2", "x", "anomaly", _at("10:10"), _at("10:40"))])["m2"],
    }
    conditions = [{"fact": "a.anomaly.present", "passed": True}, {"fact": "b.anomaly.present", "passed": True}]

    assert evaluate_correlation({"correlation": {"minimum_overlap": "10m"}}, facts, conditions)["matched"]
    assert not evaluate_correlation({"correlation": {"minimum_overlap": "15m"}}, facts, conditions)["matched"]


def test_facts_stored_without_windows_still_correlate_on_the_overall_window() -> None:
    old_style = {"signal": {"window_start": _at("10:00"), "window_end": _at("11:00")}}

    assert evaluate_correlation({"correlation": {"max_time_gap": "10m"}}, {"a": old_style, "b": old_style})["matched"]
