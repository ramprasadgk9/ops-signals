from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.behavior_intelligence.fact_extractor import extract_facts, input_facts
from backend.app.behavior_intelligence.finding_builder import build_evaluation
from backend.app.behavior_intelligence.loader import load_definitions

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFINITIONS = {definition.id: definition for definition in load_definitions(PROJECT_ROOT / "config" / "behavior_definitions.d")}

START, END = "2026-01-01T00:00:00+00:00", "2026-01-01T02:00:00+00:00"


def _signal(metric: str, analyzer: str, start: str = START, end: str = END, **evidence) -> dict:
    signal_type = "anomaly" if analyzer == "pyod_outlier" else analyzer
    return {
        "metric_name": metric,
        "analyzer_id": analyzer,
        "signal_type": signal_type,
        "start_time": start,
        "end_time": end,
        "importance_score": 0.8,
        "evidence": evidence,
    }


def _rising(metric: str, analyzer: str, percent: float = 40.0, **times) -> dict:
    """The signal each change analyzer leaves for a metric that went up by `percent`."""
    if analyzer == "trend":
        return _signal(metric, "trend", slope=0.5 if percent > 0 else -0.5, slope_percent=abs(percent), **times)
    return _signal(metric, analyzer, percent_change=percent, **times)


def _matches(definition_id: str, signals: list[dict]) -> bool:
    """What BehaviorIntelligenceService.evaluate decides, without the database: each input's facts
    from its own metric names and analyzers, the rule skipped when an input has none."""
    definition = DEFINITIONS[definition_id]
    facts = {}
    for item in definition.inputs:
        found = input_facts(item.metric_names, item.analyzers, signals)
        if found is None:
            return False
        facts[item.alias] = found
    return build_evaluation(definition, facts, facts, "svc", "run").matched


def _change(signals: list[dict]) -> dict:
    return extract_facts(signals)[signals[0]["metric_name"]]["change"]


class TestChangeFacts:
    def test_a_trend_up_is_an_upward_change(self) -> None:
        change = _change([_rising("m", "trend", 30.0)])
        assert change["present"] and change["upward"] and not change["downward"]
        assert change["direction"] == "upward"
        assert change["signed_change_percent"] == 30.0
        assert change["sources"] == ["trend"]
        assert change["windows"] == [[START, END]]

    def test_a_falling_baseline_shift_is_a_downward_change(self) -> None:
        change = _change([_rising("m", "baseline_shift", -40.0)])
        assert change["downward"] and not change["upward"]
        assert change["direction"] == "downward"
        assert change["change_percent"] == 40.0

    def test_a_ruptures_change_counts_only_above_25_percent(self) -> None:
        assert _change([_rising("m", "ruptures", 25.0)])["present"] is False
        assert _change([_rising("m", "ruptures", 26.0)])["upward"] is True

    def test_a_small_ruptures_change_point_does_not_hide_a_large_one(self) -> None:
        change = _change([_rising("m", "ruptures", 10.0), _rising("m", "ruptures", 60.0)])
        assert change["signed_change_percent"] == 60.0

    def test_up_and_down_from_different_analyzers_is_mixed(self) -> None:
        change = _change([_rising("m", "trend", 20.0), _rising("m", "ruptures", -50.0)])
        assert change["upward"] and change["downward"]
        assert change["direction"] == "mixed"
        assert change["signed_change_percent"] == -50.0

    def test_an_anomaly_alone_is_no_change(self) -> None:
        change = _change([_signal("m", "pyod_outlier")])
        assert change == {
            "present": False, "upward": False, "downward": False, "direction": "none",
            "change_percent": 0.0, "signed_change_percent": 0.0, "sources": [], "windows": [],
        }

    def test_a_level_change_window_starts_at_its_change_point(self) -> None:
        signal = _rising("m", "ruptures", 40.0)
        signal["evidence"]["change_point_time"] = "2026-01-01T01:00:00+00:00"
        assert _change([signal])["windows"] == [["2026-01-01T01:00:00+00:00", END]]


# Each rule that means "went up", with the metrics it reads. Before the change facts, the trend-only
# rules were skipped whenever the router ran ruptures instead of trend on their metrics.
WENT_UP = {
    "pool_exhaustion": ["db_connection_wait_seconds", "db_connections_active"],
    "benign_maintenance": ["batch_jobs_active", "cpu_usage"],
    "memory_leak": ["memory_usage", "cpu_throttled_seconds"],
}


@pytest.mark.parametrize("analyzer", ["trend", "baseline_shift", "ruptures"])
@pytest.mark.parametrize("definition_id", sorted(WENT_UP))
def test_a_went_up_rule_matches_whichever_change_analyzer_ran(definition_id: str, analyzer: str) -> None:
    signals = [_rising(metric, analyzer) for metric in WENT_UP[definition_id]]
    assert _matches(definition_id, signals)


@pytest.mark.parametrize("definition_id", sorted(WENT_UP))
def test_a_went_up_rule_does_not_match_when_the_metrics_went_down(definition_id: str) -> None:
    signals = [_rising(metric, "ruptures", -40.0) for metric in WENT_UP[definition_id]]
    assert not _matches(definition_id, signals)


@pytest.mark.parametrize("definition_id", sorted(WENT_UP))
def test_a_went_up_rule_does_not_match_a_small_ruptures_change(definition_id: str) -> None:
    signals = [_rising(metric, "ruptures", 20.0) for metric in WENT_UP[definition_id]]
    assert not _matches(definition_id, signals)


def test_pool_exhaustion_matches_the_signals_a_real_csv_run_produced() -> None:
    # The two ruptures signals a CSV upload of rising wait time and active connections on
    # checkout-api produced (2026-10-21): the router ran ruptures, not trend, so before the change
    # facts the shipped rule was skipped.
    signals = [
        _signal("db_connection_wait_seconds", "ruptures", "2026-10-21T15:50:00+00:00", "2026-10-21T19:45:00+00:00", percent_change=131.5, left_mean=0.146, right_mean=0.338),
        _signal("db_connections_active", "ruptures", "2026-10-21T15:50:00+00:00", "2026-10-21T19:45:00+00:00", percent_change=49.0, left_mean=26.67, right_mean=39.747),
    ]
    assert _matches("pool_exhaustion", signals)


def test_a_went_up_rule_still_needs_the_changes_at_the_same_time() -> None:
    signals = [
        _rising("db_connection_wait_seconds", "ruptures", start="2026-01-01T00:00:00+00:00", end="2026-01-01T01:00:00+00:00"),
        _rising("db_connections_active", "ruptures", start="2026-01-01T03:00:00+00:00", end="2026-01-01T04:00:00+00:00"),
    ]
    assert not _matches("pool_exhaustion", signals)


@pytest.mark.parametrize("definition_id", ["server_slow", "memory_pressure_with_errors"])
class TestMemoryRulesKeepTheirMeaning:
    """server_slow and memory_pressure_with_errors already accepted a trend up, a baseline shift up
    or a ruptures change of more than +25% on memory: change.upward says the same in one condition."""

    @staticmethod
    def _with_memory(definition_id: str, memory: dict) -> list[dict]:
        other = "cpu_usage" if definition_id == "server_slow" else "error_rate"
        return [_signal(other, "pyod_outlier"), memory]

    @pytest.mark.parametrize("analyzer", ["trend", "baseline_shift", "ruptures"])
    def test_memory_going_up_matches(self, definition_id: str, analyzer: str) -> None:
        assert _matches(definition_id, self._with_memory(definition_id, _rising("memory_usage", analyzer)))

    def test_memory_going_down_does_not(self, definition_id: str) -> None:
        assert not _matches(definition_id, self._with_memory(definition_id, _rising("memory_usage", "ruptures", -40.0)))

    def test_a_small_ruptures_change_does_not(self, definition_id: str) -> None:
        assert not _matches(definition_id, self._with_memory(definition_id, _rising("memory_usage", "ruptures", 20.0)))


def test_cpu_throttling_accepts_throttling_seen_rising_by_ruptures() -> None:
    signals = [_signal("cpu_usage", "pyod_outlier"), _rising("cpu_throttled_seconds", "ruptures", 40.0)]
    assert _matches("cpu_throttling", signals)


def test_cpu_throttling_still_needs_unusual_cpu() -> None:
    signals = [_rising("cpu_usage", "trend"), _rising("cpu_throttled_seconds", "ruptures", 40.0)]
    assert not _matches("cpu_throttling", signals)
