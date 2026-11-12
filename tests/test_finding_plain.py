"""Plain wording for finding cards (backend/app/services/finding_plain.py).

The golden cases are real findings from a local database, with their signals' evidence
(tests/fixtures/plain_findings_real.json): the texts below are what a reader sees for them.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
import yaml

from backend.app.services.active_findings import LEVEL_BACK, ProblemState
from backend.app.services.finding_plain import (
    TEMPLATES_PATH,
    FindingFacts,
    SignalFacts,
    build_plain,
    change_words,
    duration_words,
    format_value,
    link_related,
    load_wording,
    parse_wording,
    plain_for_result,
    significant,
    utc_text,
)
from intelligence.analyzers.anomaly_zscore import ZScoreAnomalyAnalyzer
from intelligence.analyzers.pyod_outlier import PyODOutlierAnalyzer
from intelligence.findings.schema import OperationalFinding
from intelligence.signals.schema import OperationalSignal

FIXTURE = Path(__file__).parent / "fixtures" / "plain_findings_real.json"
REAL = {item["id"]: item for item in json.loads(FIXTURE.read_text(encoding="utf-8"))}

# badge, headline, what changed, why it matters, what to check (times shown in UTC here).
GOLDEN = {
    522: (
        "better",
        "CPU usage ran lower than expected",
        "0.26, where about 0.42 was expected (38% off).",
        "drift-lab is using less CPU. If traffic didn't drop too, a fix or a config change may have helped.",
        "Traffic to drift-lab, recent deploys, and busy background jobs.",
    ),
    6724: (
        "worse",
        "Requests dropped sharply and stayed lower",
        "About 243 until Oct 8, 21:31 UTC. Since then about 88 (down 64%).",
        "Fewer requests are reaching search. Users may not be getting through, or something in front of it is failing.",
        "Deploys or config changes in search between Oct 8, 21:01 UTC and Oct 8, 22:01 UTC.",
    ),
    8233: (
        "noise",
        "CPU usage had 10 odd-looking readings, all within its normal range",
        "Between Oct 19, 02:39 UTC and Oct 19, 03:30 UTC. Values stayed between 0.25 and 0.71, as usual.",
        "No sign of user impact. It's shown because the pattern was unusual, not the level.",
        None,
    ),
    8279: (
        "worse",
        "Process memory went above normal 5 times, up to 91 MB",
        "Between Oct 19, 05:13 UTC and Oct 20, 01:02 UTC. Normally 44 MB to 65 MB.",
        "The process is using more memory. If it keeps growing it can run out and be restarted.",
        "The memory limit for this process, and whether it restarted.",
    ),
    8282: (
        "worse",
        "Slow-request time (p95) has been climbing unevenly",
        "Averaged 363 ms in the first 12 hours and 431 ms in the last 12 hours (up 19%), with a high of 657 ms. It has turned down in the last 12 hours.",
        "Pages and API calls feel slower, mostly for the users who wait longest. Not urgent yet, the change is gradual and uneven.",
        "Load on spike-lab, slow database queries, and the services it calls.",
    ),
    8286: (
        "blip",
        "Error rate went above normal once, up to 1.7%",
        "At Oct 19, 11:06 UTC, for one reading. Normally 0.6% to 1.2%.",
        "More requests fail, so more users see errors or failed actions.",
        "Deploys or config changes in payments, and errors in the services it calls.",
    ),
    8299: (
        "better",
        "Slow-request time (p95) dropped and stayed lower",
        "About 571 ms until Oct 19, 22:54 UTC. Since then about 357 ms (down 38%).",
        "Pages and API calls feel quicker for the users who waited longest.",
        "Deploys or config changes in spike-lab between Oct 19, 22:24 UTC and Oct 19, 23:24 UTC.",
    ),
    8300: (
        "better",
        "Error rate dropped sharply and stayed lower",
        "About 11.3% until Oct 19, 22:54 UTC. Since then about 1.2% (down 89%).",
        "Fewer requests fail, so fewer users see errors. If nobody changed anything on purpose, check that traffic didn't drop at the same time.",
        "Deploys or config changes in spike-lab between Oct 19, 22:24 UTC and Oct 19, 23:24 UTC.",
    ),
    8305: (
        "gap",
        "We lost alert-notification errors data for 22 hours",
        "No data from Oct 19, 21:40 UTC to Oct 20, 19:32 UTC (1,311 readings missing).",
        "Alerts and dashboards using this metric couldn't see problems during this time.",
        "Is the data source running? Did the metric name or a label change?",
    ),
    8306: (
        "changed",
        "ops_signal_lab_value has been climbing unevenly",
        "Averaged 0.53 in the first 12 hours and 0.72 in the last 12 hours (up 36%), with a high of 1.4.",
        "We don't know what this metric means for your users, so we can't say if this is good or bad. Describe it in config/finding_templates.yaml to see the impact here.",
        None,
    ),
}

# What the stored summaries say today that a reader can't use. No plain line may contain them.
UNREADABLE = [
    r"around sample \d",
    r"more (up|down)ward",
    r"x its normal range",
    r"\de[+-]\d",
    r"\.;",
    r"(?i)pyod|ruptures|stumpy|trend regression|structural change",
    r"batch window|selected time window",
    r"\b\d+\.\d{3,}\b",
]


def _facts(item: dict) -> tuple[FindingFacts, list[SignalFacts]]:
    finding = FindingFacts(item["metric_name"], item["service"], item["title"], item["category"], item["comparison_json"] or {}, item["event_start"], item["event_end"])
    signals = [SignalFacts(s["signal_type"], s["analyzer_id"], s["evidence"] or {}, s["start_time"], s["end_time"]) for s in item["signals"] or []]
    return finding, signals


def _plain(finding_id: int, wording=None):
    finding, signals = _facts(REAL[finding_id])
    return build_plain(finding, signals, wording or load_wording())


def _shipped() -> dict:
    return yaml.safe_load(TEMPLATES_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("finding_id", sorted(GOLDEN))
def test_real_findings_read_in_plain_words(finding_id: int) -> None:
    plain = _plain(finding_id)
    assert plain is not None
    shown = plain.to_json(load_wording())
    assert (shown["badge"], *(utc_text(shown[key]) if shown[key] else None for key in ("headline", "what", "why", "check"))) == GOLDEN[finding_id]


@pytest.mark.parametrize("finding_id", sorted(GOLDEN))
def test_plain_lines_never_use_todays_hard_to_read_wording(finding_id: int) -> None:
    shown = _plain(finding_id).to_json(load_wording())
    for key in ("headline", "what", "why", "check"):
        text = utc_text(shown[key] or "")
        for pattern in UNREADABLE:
            assert not re.search(pattern, text), f"{key} of #{finding_id} has {pattern!r}: {text}"


def test_times_are_markers_each_screen_shows_in_its_own_time_zone() -> None:
    plain = _plain(8300)
    assert "[[time:2026-10-19T22:54:17Z]]" in plain.what
    assert plain.change_time == "[[time:2026-10-19T22:54:17Z]]"


def test_the_shipped_wording_loads_with_every_template_on(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        wording = parse_wording(_shipped())
    assert caplog.records == []
    assert set(wording.templates) == {"level_change", "trend", "spikes", "odd_stretch", "data_gap", "flatline", "forecast", "targets", "alerts"}
    # Shipped without services: every finding reads as it would without this section.
    assert wording.services == {}
    assert wording.badges["worse"] == "Worse"


def test_a_wrong_placeholder_switches_only_that_template_off(caplog: pytest.LogCaptureFixture) -> None:
    raw = _shipped()
    raw["templates"]["level_change"]["what"] = "About {befor} until {change_time}."
    with caplog.at_level(logging.WARNING):
        wording = parse_wording(raw)
    assert "level_change" not in wording.templates
    assert "befor" in caplog.text
    # Its findings fall back to the stored summary; the others keep their wording.
    assert _plain(8300, wording) is None
    assert _plain(8305, wording) is not None


def test_a_concept_line_with_a_wrong_placeholder_is_left_out(caplog: pytest.LogCaptureFixture) -> None:
    raw = _shipped()
    raw["concepts"]["error_rate"]["better"] = "Fewer errors in {servce}."
    with caplog.at_level(logging.WARNING):
        wording = parse_wording(raw)
    assert "servce" in caplog.text
    plain = _plain(8300, wording)
    assert plain is not None and plain.why is None


def test_an_unreadable_or_missing_file_means_no_plain_wording(tmp_path: Path) -> None:
    broken = tmp_path / "finding_templates.yaml"
    broken.write_text("templates: [unclosed", encoding="utf-8")
    assert load_wording(broken) is None
    assert load_wording(tmp_path / "missing.yaml") is None


def test_an_edit_is_picked_up_without_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "finding_templates.yaml"
    raw = _shipped()
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert load_wording(path).badges["better"] == "Better"
    raw["badges"]["better"] = "Improved"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    import os

    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 5))
    assert load_wording(path).badges["better"] == "Improved"


def test_a_metric_nobody_described_gets_no_good_or_bad_badge() -> None:
    plain = _plain(8306)
    assert plain.badge == "changed"
    assert "We don't know what this metric means" in plain.why


def test_a_metric_named_by_pattern_gets_its_unit_and_meaning() -> None:
    wording = load_wording()
    finding = FindingFacts("checkout_request_duration_seconds", "checkout", "checkout_request_duration_seconds experienced a persistent baseline shift during the selected time window.", "behavior_change")
    signal = SignalFacts("ruptures", "ruptures", {"left_mean": 0.21, "right_mean": 1.9, "percent_change": 804.8, "change_point_time": "2026-10-19T10:00:00Z"}, None, None)
    plain = build_plain(finding, [signal], wording)
    assert plain.badge == "worse"
    assert utc_text(plain.what) == "About 210 ms until Oct 19, 10:00 UTC. Since then about 1.9 s (about 9 times as high)."
    assert plain.why.startswith("Pages and API calls feel slower")


def test_a_finding_without_usable_evidence_keeps_its_summary() -> None:
    finding = FindingFacts("error_rate", "checkout", "error_rate has unusual behaviour.", "operational_insight")
    assert build_plain(finding, [], load_wording()) is None
    assert build_plain(finding, [SignalFacts("pattern_discovery", "stumpy", {"motif_distance": 0.1}, None, None)], load_wording()) is None


def _marker_times(text: str) -> list[str]:
    return re.findall(r"\[\[time:([^\]]+)\]\]", text)


def test_the_chart_marks_the_times_the_sentence_names() -> None:
    gap = _plain(8305).to_json(load_wording())
    assert gap["marks"] == {"bands": [{"start": "2026-10-19T21:40:00Z", "end": "2026-10-20T19:32:00Z"}], "style": "gap"}
    assert _marker_times(gap["what"])[:2] == ["2026-10-19T21:40:00Z", "2026-10-20T19:32:00Z"]

    change = _plain(6724).to_json(load_wording())
    assert change["marks"] == {"lines": [{"at": _marker_times(change["change_time"])[0], "kind": "change"}]}


def test_each_burst_gets_its_own_band_inside_the_sentences_first_and_last_time() -> None:
    plain = _plain(8279).to_json(load_wording())
    first, last = _marker_times(plain["what"])[:2]
    bands = plain["marks"]["bands"]
    assert len(bands) == 5
    assert bands == sorted(bands, key=lambda band: band["start"])
    assert bands[0]["start"] == first and max(band["end"] for band in bands) == last


def test_a_stuck_value_is_shaded_from_its_first_to_its_last_stuck_reading() -> None:
    finding = FindingFacts("error_rate", "trend-lab", "", "data_quality", {}, "2026-11-09T04:36:00Z", "2026-11-09T21:33:00Z", True)
    signal = SignalFacts("flatline", "data_health", {"stuck_value": 0.006, "flatline_minutes": 1017, "normal_change_ratio": 0.89}, "2026-11-09T04:36:00Z", "2026-11-09T21:33:00Z")
    plain = build_plain(finding, [signal], load_wording()).to_json(load_wording())
    assert plain["marks"] == {"bands": [{"start": "2026-11-09T04:36:00Z", "end": "2026-11-09T21:33:00Z"}]}


def test_a_level_that_came_back_marks_the_jump_and_the_way_back() -> None:
    finding, signals = _facts(REAL[8300])
    jumped, back = datetime(2026, 10, 19, 22, 54, tzinfo=timezone.utc), datetime(2026, 10, 20, 2, 54, tzinfo=timezone.utc)
    finding = dataclasses.replace(finding, level=ProblemState(ended_at=back, how=LEVEL_BACK, changed_at=jumped, level_before=11.3, level_during=1.2, level_now=11.0))
    plain = build_plain(finding, signals, load_wording()).to_json(load_wording())
    assert plain["marks"] == {"lines": [{"at": "2026-10-19T22:54:00Z", "kind": "change"}, {"at": "2026-10-20T02:54:00Z", "kind": "back"}]}


@pytest.mark.parametrize("finding_id", [522, 8282])
def test_a_trend_or_forecast_is_not_about_one_moment_so_nothing_is_marked(finding_id: int) -> None:
    assert _plain(finding_id).to_json(load_wording())["marks"] is None


def test_level_changes_of_one_service_at_the_same_moment_mention_each_other() -> None:
    errors, latency = _plain(8300), _plain(8299)
    link_related([(8300, errors), (8299, latency)])
    assert [item["finding_id"] for item in errors.related] == [8299]
    assert utc_text(errors.related[0]["text"]) == "Slow-request time (p95) also dropped at Oct 19, 22:54 UTC (571 ms to 357 ms)."
    assert [item["finding_id"] for item in latency.related] == [8300]


def test_unrelated_changes_are_not_linked() -> None:
    errors, latency, traffic = _plain(8300), _plain(8299), _plain(6724)
    latency.service = "other-service"
    link_related([(8300, errors), (8299, latency), (6724, traffic)])
    assert errors.related == []
    # The same metric seen again by another run is the same problem, not a related one.
    again = _plain(8300)
    link_related([(8300, errors), (9999, again)])
    assert errors.related == []


def test_validation_results_get_plain_wording_too() -> None:
    item = REAL[8300]
    signals = [
        OperationalSignal(
            signal_type=s["signal_type"],
            analyzer_id=s["analyzer_id"],
            metric_name=item["metric_name"],
            service=item["service"],
            env=None,
            severity="high",
            confidence=0.9,
            start_time=datetime.fromisoformat(s["start_time"]),
            end_time=datetime.fromisoformat(s["end_time"]),
            summary="",
            evidence=s["evidence"],
            signal_id=s["signal_id"],
        )
        for s in item["signals"]
    ]
    finding = OperationalFinding(service=item["service"], metric_name=item["metric_name"], title=item["title"], summary=item["summary"], category=item["category"], signal_ids=[s.signal_id for s in signals], comparison_json=item["comparison_json"])
    [plain] = plain_for_result([finding], signals)
    assert plain["badge"] == "better"
    assert plain["badge_label"] == "Better"
    assert plain["headline"] == "Error rate dropped sharply and stayed lower"


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (0.1131, "ratio", "11.3%"),
        (0.006, "ratio", "0.6%"),
        (0.0121, "ratio", "1.2%"),
        (571.1157, "ms", "571 ms"),
        (1260, "ms", "1.3 s"),
        (0.21, "s", "210 ms"),
        (43736678.4, "bytes", "44 MB"),
        (4.2e9, "bytes", "4.2 GB"),
        (0.2595, "cores", "0.26 cores"),
        (1311, "count", "1,311"),
        (243.2997, None, "243"),
        (87.734, None, "88"),
        (0.5302, None, "0.53"),
        (0.0000123, None, "0.000012"),
        (12345678.9, None, "12,300,000"),
        (None, "ms", None),
        ("n/a", None, None),
    ],
)
def test_values_are_written_in_their_unit(value, unit, expected) -> None:
    assert format_value(value, unit) == expected


def test_numbers_never_use_scientific_notation() -> None:
    for value in (1e-7, 3.2e-5, 4.374e7, 9.9e12):
        assert "e" not in significant(value).lower()


def test_changes_and_durations_read_as_words() -> None:
    assert change_words(0.1131, 0.0121, -89.3) == "down 89%"
    assert change_words(362.8, 430.5) == "up 19%"
    assert change_words(0.21, 1.9) == "about 9 times as high"
    assert change_words(10, 10.01) == "about the same"
    assert duration_words(65) == "65 minutes"
    assert duration_words(1311) == "22 hours"
    assert duration_words(60 * 24 * 5) == "5 days"
    assert duration_words(0.5) == "under a minute"


def _frame(values: list[float]) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=index) for index in range(len(values))],
            "value": values,
            "metric_name": ["error_rate"] * len(values),
            "service": ["checkout"] * len(values),
            "env": ["prod"] * len(values),
        }
    )


def test_spike_signals_save_their_peak_for_the_card() -> None:
    values = [0.01 + 0.001 * (index % 5) for index in range(80)]
    values[60] = 0.09
    zscore = ZScoreAnomalyAnalyzer(finding_rules={"min_abs_zscore": 3.0, "min_points": 1}).analyze(_frame(values))
    assert zscore and zscore[0].evidence["peak_value"] == pytest.approx(0.09)
    pyod = PyODOutlierAnalyzer().analyze(_frame(values))
    peaks = [signal.evidence["peak_value"] for signal in pyod]
    assert pytest.approx(0.09) in peaks


# --- Service context: what a service does and the targets it's held to ---------------------------


def _with_services(services: dict):
    raw = _shipped()
    raw["services"] = services
    return parse_wording(raw)


def _target(finding_id: int, services: dict) -> str | None:
    plain = _plain(finding_id, _with_services(services))
    return utc_text(plain.target) if plain.target else None


def test_a_service_says_what_it_does_and_how_important_it_is() -> None:
    wording = _with_services({"Spike-Lab": {"about": "Customers pay for their orders here.", "importance": "critical"}})
    shown = _plain(8300, wording).to_json(wording)
    assert shown["service_about"] == "Customers pay for their orders here."
    assert (shown["service_importance"], shown["service_importance_label"]) == ("critical", "Critical service")
    # No target set for the metric: no target line.
    assert shown["target"] is None


@pytest.mark.parametrize(
    ("finding_id", "services", "expected"),
    [
        # Error rate 11.3% -> 1.2% at 22:54: back under a 5% target, over a 1% one before and after.
        (8300, {"spike-lab": {"targets": {"error_rate": {"below": 0.05}}}}, "Back within your 5% target since Oct 19, 22:54 UTC."),
        (8300, {"spike-lab": {"targets": {"error_rate": {"below": 0.01}}}}, "Above your 1% target both before and after the change."),
        (8300, {"spike-lab": {"targets": {"error_rate": {"below": 0.2}}}}, "Still within your 20% target."),
        # Latency 571 ms -> 357 ms.
        (8299, {"spike-lab": {"targets": {"request_latency_p95": {"below": 400}}}}, "Back within your 400 ms target since Oct 19, 22:54 UTC."),
        # Traffic 243 -> 88, held to at least 100.
        (6724, {"search": {"targets": {"http_requests_total": {"above": 100}}}}, "Below your 100 target since Oct 8, 21:31 UTC."),
        # Latency trend: 363 ms then 431 ms on average.
        (8282, {"spike-lab": {"targets": {"request_latency_p95": {"below": 400}}}}, "Above your 400 ms target on average in the last 12 hours."),
        (8282, {"spike-lab": {"targets": {"request_latency_p95": {"below": 300}}}}, "Above your 300 ms target on average all through this window."),
        (8282, {"spike-lab": {"targets": {"request_latency_p95": {"below": 500}}}}, "Still within your 500 ms target."),
        # One-minute error spike to 1.7% on payments.
        (8286, {"payments": {"targets": {"error_rate": {"below": 0.01}}}}, "Went past your 1% target, reaching 1.7%."),
        (8286, {"payments": {"targets": {"error_rate": {"below": 0.02}}}}, "Still within your 2% target."),
        # A data gap has no value to hold against a target.
        (8305, {"unknown": {"targets": {"prometheus_notifications_errors_total": {"below": 1}}}}, None),
    ],
)
def test_findings_say_how_they_stand_against_the_services_target(finding_id: int, services: dict, expected: str | None) -> None:
    assert _target(finding_id, services) == expected


def test_a_target_breach_says_how_long_it_has_lasted() -> None:
    wording = _with_services({"checkout": {"targets": {"error_rate": {"below": 0.01}}}})
    change = SignalFacts("ruptures", "ruptures", {"left_mean": 0.004, "right_mean": 0.021, "percent_change": 425.0, "change_point_time": "2026-10-19T10:00:00Z"}, None, None)
    title = "error_rate experienced a persistent baseline shift during the selected time window."
    end = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)

    def line(ongoing: bool | None) -> str:
        finding = FindingFacts("error_rate", "checkout", title, "behavior_change", {}, None, end, ongoing)
        return utc_text(build_plain(finding, [change], wording).target)

    assert line(True) == "Above your 1% target since Oct 19, 10:00 UTC (2 hours so far)."
    assert line(False) == "Above your 1% target from Oct 19, 10:00 UTC to Oct 19, 12:00 UTC (2 hours)."
    assert line(None) == "Above your 1% target since Oct 19, 10:00 UTC."


def test_a_wrong_service_entry_is_left_out_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        wording = _with_services(
            {
                "payments": {"importance": "urgent", "targets": {"error_rate": {"under": 0.01}, "request_latency_p95": {"below": 500}}},
                "search": "customers find products here",
            }
        )
    assert "urgent" in caplog.text and "error_rate" in caplog.text and "'search'" in caplog.text
    payments = wording.services["payments"]
    assert payments.importance is None
    assert list(payments.targets) == ["request_latency_p95"]
    assert "search" not in wording.services


def test_a_service_without_context_reads_as_before() -> None:
    plain = _plain(8300)
    shown = plain.to_json(load_wording())
    assert (shown["target"], shown["service_about"], shown["service_importance"], shown["service_importance_label"]) == (None, None, None, None)


def test_an_odd_stretch_on_a_described_metric_says_why_and_what_to_check() -> None:
    finding = FindingFacts("request_latency_p95", "checkout", "request_latency_p95 has unusual activity in the selected time window.", "unusual_activity")
    stretch = SignalFacts("anomaly", "stumpy", {"surprise": 13.9}, "2026-10-19T22:49:00Z", "2026-10-20T21:09:00Z")
    plain = build_plain(finding, [stretch], load_wording())
    assert (plain.kind, plain.badge) == ("odd_stretch", "changed")
    assert plain.why == "A stretch unlike the rest can be an early sign of trouble, or a one-off such as a batch job, a test or a release."
    assert plain.check == "Load on checkout, slow database queries, and the services it calls."


def test_an_odd_stretch_on_an_undescribed_metric_says_it_needs_describing() -> None:
    finding = FindingFacts("ops_signal_lab_value", "spike-lab", "ops_signal_lab_value has unusual activity in the selected time window.", "unusual_activity")
    stretch = SignalFacts("anomaly", "stumpy", {"surprise": 13.9}, "2026-10-19T22:49:00Z", "2026-10-20T21:09:00Z")
    plain = build_plain(finding, [stretch], load_wording())
    assert plain.why.startswith("We don't know what this metric means")
    assert plain.check is None


def _cpu_trend(previous_mean: float, current_mean: float) -> object:
    # Like mixed-lab's CPU on Oct 20: a falling fit line, but the two halves average about the same.
    finding = FindingFacts(
        "cpu_usage", "mixed-lab", "cpu_usage is trending in one direction.", "behavior_change",
        {"previous_mean": previous_mean, "current_mean": current_mean, "previous_max": 1.7, "current_max": 1.4},
    )
    trend = SignalFacts("trend", "trend", {"slope_percent": -12.0, "r_squared": 0.1}, "2026-10-20T01:00:00Z", "2026-10-21T01:00:00Z")
    return build_plain(finding, [trend], load_wording())


def test_a_trend_that_barely_moved_the_level_is_not_called_better_or_worse() -> None:
    plain = _cpu_trend(0.98, 0.97)
    assert (plain.kind, plain.badge) == ("trend", "changed")
    assert plain.headline == "CPU usage has been falling unevenly"
    assert plain.why == "The level has barely moved (down 1% between the two halves), so users are unlikely to notice."
    assert plain.check is None


def test_a_trend_that_moved_the_level_keeps_its_direction() -> None:
    plain = _cpu_trend(1.0, 0.9)
    assert plain.badge == "better"
    assert plain.why.startswith("mixed-lab is using less CPU")
    assert plain.check is not None


def _ended(finding_id: int, ongoing: bool | None):
    """A real finding, as the analysis saw it: over since its last bad reading, or still going."""
    finding, signals = _facts(REAL[finding_id])
    finding = dataclasses.replace(finding, ongoing=ongoing)
    return build_plain(finding, signals, load_wording()), finding


@pytest.mark.parametrize(
    ("finding_id", "sentence"),
    [
        (8305, "Data has been arriving again since Oct 20, 19:32 UTC."),
        (8286, "Normal again since Oct 19, 11:06 UTC."),
        (8279, "Normal again since Oct 20, 01:02 UTC."),
    ],
)
def test_a_finished_problem_says_since_when_it_is_normal_again(finding_id: int, sentence: str) -> None:
    plain, finding = _ended(finding_id, ongoing=False)
    assert utc_text(plain.what) == f"{GOLDEN[finding_id][2]} {sentence}"
    # Still going, or not known: the card reads as before.
    for ongoing in (True, None):
        assert utc_text(_ended(finding_id, ongoing)[0].what) == GOLDEN[finding_id][2]


@pytest.mark.parametrize("finding_id", [8233, 8300, 8282])
def test_only_kinds_that_can_end_say_so(finding_id: int) -> None:
    # Readings inside the normal range were never abnormal; level changes and trends end at the last reading.
    plain, _ = _ended(finding_id, ongoing=False)
    assert utc_text(plain.what) == GOLDEN[finding_id][2]


def test_a_finished_problem_reads_the_same_on_every_finding_of_it() -> None:
    from backend.app.models.db import get_engine, get_session_local, init_engine
    from backend.app.models.entities import Base, FindingEntity, SignalEntity
    from backend.app.services.finding_plain import finding_plain

    init_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(get_engine())
    item = REAL[8305]
    gap = item["signals"][0]
    end = datetime.fromisoformat(item["event_end"].replace("Z", "+00:00"))
    with get_session_local()() as db:
        db.add(SignalEntity(signal_id="gap", signal_type=gap["signal_type"], analyzer_id=gap["analyzer_id"], metric_name=item["metric_name"],
                            service=item["service"], severity="high", start_time=gap["start_time"] and datetime.fromisoformat(gap["start_time"].replace("Z", "+00:00")),
                            end_time=end, evidence_json=gap["evidence"], importance_score=0.7, analysis_run_id="run"))

        def finding(finding_id: int, minutes: int, ongoing: bool, problem_id: int | None = None) -> None:
            db.add(FindingEntity(id=finding_id, analysis_run_id="run", service=item["service"], metric_name=item["metric_name"], title=item["title"],
                                 summary="s", category=item["category"], health_status="significant", importance_score=0.7, investigation_priority=2,
                                 signal_ids=["gap"], comparison_json={}, created_at=end + timedelta(minutes=minutes), problem_id=problem_id,
                                 event_start=end - timedelta(hours=1), event_end=end, ongoing=ongoing))

        # Problem 1: still going at the first run, over at the second.
        finding(1, -5, True)
        finding(2, 5, False, problem_id=1)
        # Problem 3: over at the first run, back at the second.
        finding(3, -5, False)
        finding(4, 5, True, problem_id=3)
        db.commit()
        plain = finding_plain(db, db.query(FindingEntity).all())

    over = "Data has been arriving again since Oct 20, 19:32 UTC."
    assert utc_text(plain[1]["what"]).endswith(over) and utc_text(plain[2]["what"]).endswith(over)
    assert over not in utc_text(plain[3]["what"]) and over not in utc_text(plain[4]["what"])
