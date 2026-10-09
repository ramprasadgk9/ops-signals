from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pandas as pd
import pytest

from benchmark.finding_trust import events as ev


def test_label_inside_before_and_outside_a_window() -> None:
    windows = [(100, 140)]
    assert ev.label(120, windows, [125]) == (ev.IN_INCIDENT, 5)
    # Up to one window length (40) ahead of the start counts as an early warning.
    assert ev.label(70, windows, [125]) == (ev.BEFORE_INCIDENT, 55)
    assert ev.label(59, windows, [125]) == (ev.FALSE_ALARM, None)
    assert ev.label(200, windows, [125]) == (ev.FALSE_ALARM, None)


def test_label_respects_scored_range_and_explicit_before() -> None:
    windows = [(100, 140)]
    assert ev.label(10, windows, scored_from=50) == (ev.NOT_SCORED, None)
    assert ev.label(500, windows, scored_until=300) == (ev.NOT_SCORED, None)
    assert ev.label(90, windows, before=5)[0] == ev.FALSE_ALARM
    # A detection after the marked moment has a negative lead: caught, not warned.
    assert ev.label(130, windows, [125]) == (ev.IN_INCIDENT, -5)


def _event(finding_type: str, analyzers: tuple[str, ...], importance: float, outcome: str) -> ev.FindingEvent:
    return ev.FindingEvent(row=0, finding_type=finding_type, analyzers=analyzers, importance=importance, confidence=0.9, outcome=outcome)


def test_rate_tables_count_outcomes_per_group_and_skip_unscored() -> None:
    events = [
        _event("behavior_change", ("baseline_shift", "ruptures"), 0.7, ev.IN_INCIDENT),
        _event("behavior_change", ("baseline_shift", "ruptures"), 0.7, ev.FALSE_ALARM),
        _event("behavior_change", ("ruptures",), 0.4, ev.BEFORE_INCIDENT),
        _event("unusual_activity", ("pyod_outlier",), 0.9, ev.NOT_SCORED),
    ]
    tables = ev.rate_tables(events)

    by_type = {row["group"]["finding_type"]: row for row in tables["type"]}
    assert set(by_type) == {"behavior_change"}
    assert by_type["behavior_change"]["n"] == 3
    assert (by_type["behavior_change"]["real"], by_type["behavior_change"]["early"], by_type["behavior_change"]["false"]) == (1, 1, 1)

    agree = {row["group"]["agreement"]: row for row in tables["type, agreement"]}
    assert agree["2+ analyzers"]["real_rate"] == pytest.approx(0.5)
    assert agree["1 analyzer"]["early_rate"] == pytest.approx(1.0)

    combos = {row["group"]["analyzers"]: row["n"] for row in tables["type, exact analyzers"]}
    assert combos == {"baseline_shift+ruptures": 2, "ruptures": 1}


def test_lookup_falls_back_to_a_broader_group_when_a_group_is_small() -> None:
    big = [_event("behavior_change", ("ruptures",), 0.4, ev.IN_INCIDENT) for _ in range(30)]
    rare = [_event("behavior_change", ("baseline_shift", "ruptures"), 0.9, ev.FALSE_ALARM) for _ in range(3)]
    tables = ev.rate_tables(big + rare)

    common = ev.lookup(big[0], tables)
    assert common["level"] == "type, agreement, importance" and common["n"] == 30

    fallback = ev.lookup(rare[0], tables)
    assert fallback["level"] == "type" and fallback["n"] == 33

    assert ev.lookup(_event("unusual_activity", ("pyod_outlier",), 0.5, ev.IN_INCIDENT), tables) is None


def test_wilson_low_is_cautious_on_small_samples() -> None:
    assert ev.wilson_low(5, 6) < 0.5 < 5 / 6
    assert ev.wilson_low(500, 600) == pytest.approx(0.80, abs=0.02)
    assert ev.wilson_low(0, 0) is None


def test_importance_band_matches_health_status_cuts() -> None:
    assert [ev.importance_band(v) for v in (0.8, 0.79, 0.55, 0.54)] == ["high", "medium", "medium", "low"]


@dataclass
class _Signal:
    signal_id: str
    analyzer_id: str
    signal_type: str
    start_time: pd.Timestamp
    confidence: float
    evidence: dict = field(default_factory=dict)


@dataclass
class _Finding:
    signal_ids: list[str]
    importance_score: float
    category: str = ""


@dataclass
class _ScriptedPipeline:
    """Returns, for each run, the signals whose start the window already contains."""

    signals: list[_Signal]
    seen_windows: list[int] = field(default_factory=list)

    def run_dataframe(self, window: pd.DataFrame):
        last = window["timestamp"].iloc[-1]
        visible = [s for s in self.signals if s.start_time <= last]
        self.seen_windows.append(len(window))
        findings = [_Finding([s.signal_id for s in visible], 0.6)] if visible else []
        return SimpleNamespace(signals=visible, findings=findings, executed_analyzers=[])


def test_replay_raises_each_event_once_at_the_first_run_that_sees_it() -> None:
    times = pd.date_range("2024-01-01", periods=100, freq="5min", tz="UTC")
    frame = pd.DataFrame({"timestamp": times, "value": 1.0, "metric_name": "m"})
    pipeline = _ScriptedPipeline(
        [
            _Signal("a", "ruptures", "ruptures", times[45], 0.7),
            _Signal("b", "baseline_shift", "baseline_shift", times[46], 0.8),
            _Signal("c", "pyod_outlier", "anomaly", times[75], 0.6),
        ]
    )

    events, runs, errors = ev.replay_events(pipeline, frame, step=10, window=50, horizon=20, min_history=30)

    assert errors == 0 and runs == 7
    assert pipeline.seen_windows[-1] == 50
    assert [(e.row, e.finding_type, e.analyzers) for e in events] == [
        (50, "behavior_change", ("baseline_shift", "ruptures")),
        (80, "unusual_activity", ("pyod_outlier",)),
    ]
    assert events[0].agreement == "2+ analyzers" and events[1].agreement == "1 analyzer"


def test_replay_dates_a_change_point_by_its_evidence_not_the_window_start() -> None:
    times = pd.date_range("2024-01-01", periods=100, freq="5min", tz="UTC")
    frame = pd.DataFrame({"timestamp": times, "value": 1.0, "metric_name": "m"})
    # ruptures starts its signal at the window's first row and names the change in its evidence.
    shift = _Signal("r", "ruptures", "ruptures", times[0], 0.7, {"change_point_time": times[62].isoformat()})
    pipeline = _ScriptedPipeline([shift])
    pipeline.run_dataframe = lambda window: SimpleNamespace(  # visible once the change is in the window
        signals=[shift] if window["timestamp"].iloc[-1] >= times[62] else [],
        findings=[_Finding(["r"], 0.6)] if window["timestamp"].iloc[-1] >= times[62] else [],
        executed_analyzers=[],
    )

    events, _, _ = ev.replay_events(pipeline, frame, step=10, window=50, horizon=20, min_history=30)

    # One event, at the first run after the change; later runs re-finding it stay quiet.
    assert [(e.row, e.finding_type) for e in events] == [(70, "behavior_change")]


def test_chance_rate_is_the_share_of_scored_time_inside_incidents() -> None:
    assert ev.chance_rate([(100, 140)], 0, 200) == pytest.approx(0.2)
    # Only the part of a window inside the scored range counts.
    assert ev.chance_rate([(150, 300)], 0, 200) == pytest.approx(0.25)
    assert ev.chance_rate([(0, 10)], 50, 50) is None


def test_rate_rows_compare_the_real_rate_with_chance() -> None:
    events = [_event("unusual_activity", ("pyod_outlier",), 0.6, outcome) for outcome in (ev.IN_INCIDENT, ev.FALSE_ALARM, ev.FALSE_ALARM, ev.FALSE_ALARM)]
    for event in events:
        event.source = {"chance": 0.125}
    row = ev.overall(events)
    assert row["chance"] == pytest.approx(0.125)
    assert row["lift"] == pytest.approx(2.0)


def test_rcaeval_refuses_an_archive_that_does_not_match_its_pinned_checksum(tmp_path, monkeypatch) -> None:
    import io

    from benchmark import fetch
    from benchmark.finding_trust import rcaeval

    assert set(rcaeval.ARCHIVE_SHA256) == set(rcaeval.SYSTEMS)
    monkeypatch.setattr(fetch.urllib.request, "urlopen", lambda url, timeout=60: io.BytesIO(b"not the real archive"))

    with pytest.raises(fetch.CheckoutError, match="expected pinned"):
        rcaeval.ensure_rcaeval("RE1-OB", cache_dir=tmp_path)
    assert not (tmp_path / "RE1-OB").exists()
