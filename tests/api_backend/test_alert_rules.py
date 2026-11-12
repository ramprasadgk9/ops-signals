"""Findings borrow what the team's Prometheus alert on their metric says: its text, its runbook and
the line it fires at (backend/app/services/alert_rules.py)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.config import PrometheusConnectionConfig
from backend.app.models.db import get_session_local
from backend.app.models.entities import AnalysisRunEntity, FindingEntity, SignalEntity
from backend.app.services import alert_rules as alert_rules_module
from backend.app.services.alert_rules import (
    alert_labels,
    alert_rules,
    alert_summary,
    alert_text,
    matching_alerts,
    parse_alert_rules,
    parse_threshold,
    safe_runbook_url,
)
from backend.app.services.finding_plain import FindingFacts, SignalFacts, build_plain, load_wording, parse_wording, TEMPLATES_PATH, utc_text
from backend.app.services.recording_rules import parse_recording_rules, with_alerts

import yaml

SERVICE_LABELS = ["service", "job", "app", "app_kubernetes_io_name"]
REAL = {item["id"]: item for item in json.loads((Path(__file__).parents[1] / "fixtures" / "plain_findings_real.json").read_text(encoding="utf-8"))}


def _alert(name: str, query: str, *, duration: float = 0, group: str = "alerts", **annotations: str) -> dict:
    return {"type": "alerting", "name": name, "query": query, "duration": duration, "labels": {"severity": "warning"}, "annotations": annotations, "health": "ok"}


def _payload(*rules: dict) -> dict:
    return {"status": "success", "data": {"groups": [{"name": "alerts", "rules": list(rules)}]}}


def _rules(*rules: dict):
    return parse_alert_rules(_payload(*rules))


@pytest.fixture(autouse=True)
def _empty_cache():
    alert_rules_module.clear_cache()
    yield
    alert_rules_module.clear_cache()


# --- Reading the rules -----------------------------------------------------------------------------


def test_parse_reads_text_runbook_wait_and_matchers_and_skips_recording_rules() -> None:
    payload = _payload(
        {"type": "recording", "name": "service:error_rate:percent", "query": "100 * avg by (service) (error_rate)"},
        _alert(
            "SpikeLabErrorRateHigh",
            'service:error_rate:percent{service="spike-lab", env=~"prod|stage"} > 5',
            duration=300,
            summary="spike-lab error rate above 5%",
            description="Orders fail at checkout.",
            runbook_url="https://wiki.example.com/runbooks/spike-lab-errors",
        ),
    )

    [rule] = parse_alert_rules(payload)

    assert rule.name == "SpikeLabErrorRateHigh"
    assert rule.metrics == ("service:error_rate:percent",)
    assert [(m.label, m.op, m.value) for m in rule.matchers["service:error_rate:percent"]] == [("service", "=", "spike-lab"), ("env", "=~", "prod|stage")]
    assert (rule.threshold.metric, rule.threshold.op, rule.threshold.limit, rule.threshold.keep) == ("service:error_rate:percent", ">", 5.0, "below")
    assert rule.wait_seconds == 300
    assert rule.runbook_url == "https://wiki.example.com/runbooks/spike-lab-errors"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("x > 5", ("x", ">", 5.0)),
        ('x{service="a"} >= 0.05', ("x", ">=", 0.05)),
        ("5 < x", ("x", ">", 5.0)),
        ("x < 1e-3", ("x", "<", 0.001)),
        ("rate(x[5m]) > 1", None),
        ("x > 5 and y", None),
        ("x > bool 5", None),
        ("x == 0", None),
        ("x / y > 0.1", None),
    ],
)
def test_only_a_plain_comparison_gives_a_line(query: str, expected) -> None:
    threshold = parse_threshold(query)
    assert (None if threshold is None else (threshold.metric, threshold.op, threshold.limit)) == expected


def test_a_name_inside_a_label_value_is_not_the_selector() -> None:
    [rule] = _rules(_alert("A", 'other{note="error_rate{x}"} + error_rate{service="cart"} > 1'))
    assert [(m.label, m.value) for m in rule.matchers["error_rate"]] == [("service", "cart")]


@pytest.mark.parametrize(
    ("url", "kept"),
    [
        ("https://wiki.example.com/r", True),
        ("http://wiki/r", True),
        ("javascript:alert(1)", False),
        ("wiki.example.com/r", False),
        ("https://wiki/{{ $labels.service }}", False),
        ("https://wiki/a b", False),
        (None, False),
    ],
)
def test_only_web_links_are_kept_as_runbooks(url, kept: bool) -> None:
    assert (safe_runbook_url(url) is not None) == kept


class FakeRulesService:
    def __init__(self, payload=None, error: HTTPException | None = None):
        self.config = PrometheusConnectionConfig(id="local", base_url="http://prometheus:9090")
        self.payload = payload
        self.error = error
        self.calls: list[str | None] = []

    def rules(self, rule_type=None):
        self.calls.append(rule_type)
        if self.error:
            raise self.error
        return self.payload


def test_rules_are_cached_and_a_failure_is_an_empty_list_for_a_while() -> None:
    service = FakeRulesService(_payload(_alert("A", "x > 1")))
    assert [rule.name for rule in alert_rules(service)] == ["A"]
    alert_rules(service)
    assert service.calls == ["alert"]

    alert_rules_module.clear_cache()
    down = FakeRulesService(error=HTTPException(status_code=504, detail="Prometheus request timed out"))
    assert alert_rules(down) == []
    assert alert_rules(down) == []
    assert down.calls == ["alert"]


# --- Which alerts speak for a finding --------------------------------------------------------------


def test_service_specific_alerts_win_over_generic_ones_and_others_services_are_left_out() -> None:
    rules = _rules(
        _alert("AllErrors", "error_rate > 0.1"),
        _alert("CartErrors", 'error_rate{service="cart"} > 0.05'),
        _alert("Shops", 'error_rate{service=~"cart|shop"} > 0.08'),
        _alert("NotCart", 'error_rate{service!="cart"} > 0.02'),
        _alert("Latency", 'latency{service="cart"} > 1'),
    )

    assert [rule.name for rule in matching_alerts(rules, "error_rate", "cart", SERVICE_LABELS)] == ["CartErrors", "Shops"]
    assert [rule.name for rule in matching_alerts(rules, "error_rate", "search", SERVICE_LABELS)] == ["NotCart"]
    # A finding without a service only gets alerts that don't pick a service.
    assert [rule.name for rule in matching_alerts(rules, "error_rate", "unknown", SERVICE_LABELS)] == ["AllErrors"]
    assert matching_alerts(rules, "cpu", "cart", SERVICE_LABELS) == []


def test_a_bad_regex_never_matches() -> None:
    rules = _rules(_alert("Broken", 'error_rate{service=~"(cart"} > 1'), _alert("All", "error_rate > 1"))
    assert [rule.name for rule in matching_alerts(rules, "error_rate", "cart", SERVICE_LABELS)] == ["All"]


def test_alert_text_fills_known_labels_and_leaves_out_sentences_it_cant_fill() -> None:
    [rule] = _rules(
        _alert(
            "A",
            'error_rate{service="cart", env="prod"} > 0.05',
            description="{{ $labels.service }} in {{$labels.env}} fails orders. The rate is {{ $value | humanizePercentage }}. Page {{ $labels.team }}.",
        )
    )
    labels = alert_labels(rule, "error_rate", "cart", SERVICE_LABELS)
    assert alert_text(rule, labels) == "cart in prod fails orders."

    [only_templates] = _rules(_alert("B", "x > 1", description="Value {{ $value }}."))
    assert alert_text(only_templates, {}) is None

    # A summary is a title, usually the condition again: it never stands in for the description.
    [summary_only] = _rules(_alert("C", "x > 1", summary="{{ $labels.service }} errors above 1"))
    assert alert_text(summary_only, {"service": "cart"}) is None
    assert alert_summary(summary_only, {"service": "cart"}) == "cart errors above 1"

    [long] = _rules(_alert("D", "x > 1", description="word " * 200))
    assert len(alert_text(long, {})) == 300


# --- What the finding says -------------------------------------------------------------------------


def _real(finding_id: int) -> tuple[FindingFacts, list[SignalFacts]]:
    item = REAL[finding_id]
    finding = FindingFacts(item["metric_name"], item["service"], item["title"], item["category"], item["comparison_json"] or {}, item["event_start"], item["event_end"])
    signals = [SignalFacts(s["signal_type"], s["analyzer_id"], s["evidence"] or {}, s["start_time"], s["end_time"]) for s in item["signals"] or []]
    return finding, signals


def _rising(ongoing: bool | None = True, after: float = 0.021) -> tuple[FindingFacts, list[SignalFacts]]:
    change = SignalFacts("ruptures", "ruptures", {"left_mean": 0.004, "right_mean": after, "percent_change": 425.0, "change_point_time": "2026-10-19T10:00:00Z"}, None, None)
    title = "error_rate experienced a persistent baseline shift during the selected time window."
    finding = FindingFacts("error_rate", "checkout", title, "behavior_change", {}, None, datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc), ongoing)
    return finding, [change]


def _alert_json(facts: tuple[FindingFacts, list[SignalFacts]], *rules: dict, wording=None) -> dict | None:
    finding, signals = facts
    matched = matching_alerts(_rules(*rules), finding.metric_name, finding.service, SERVICE_LABELS)
    wording = wording or load_wording()
    shown = build_plain(finding, signals, wording, matched, SERVICE_LABELS).to_json(wording)["alert"]
    if shown and shown["line"]:
        shown["line"] = utc_text(shown["line"])
    return shown


def test_a_finding_reads_the_alerts_words_runbook_and_where_it_stands_against_its_line() -> None:
    shown = _alert_json(
        _real(8300),
        _alert(
            "SpikeLabErrorRateHigh",
            'error_rate{service="spike-lab"} > 0.05',
            description="Orders fail at checkout; customers see 'Payment could not be processed'.",
            runbook_url="https://wiki.example.com/runbooks/spike-lab-errors",
        ),
    )

    assert shown == {
        "name": "SpikeLabErrorRateHigh",
        "group": "alerts",
        "summary": None,
        "text": "Orders fail at checkout; customers see 'Payment could not be processed'.",
        "runbook_url": "https://wiki.example.com/runbooks/spike-lab-errors",
        # 11.3% -> 1.2% at 22:54.
        "line": "Back below the 5% alert line since Oct 19, 22:54 UTC.",
        "line_alert": "SpikeLabErrorRateHigh",
    }


def test_past_the_line_says_when_the_alert_fires_while_the_problem_goes_on() -> None:
    rule = _alert("CheckoutErrors", 'error_rate{service="checkout"} > 0.01', duration=300)

    assert _alert_json(_rising(True), rule)["line"] == "Above the 1% alert line since Oct 19, 10:00 UTC (2 hours so far). Alert CheckoutErrors fires once it stays past the line for 5 minutes."
    assert _alert_json(_rising(False), rule)["line"] == "Above the 1% alert line from Oct 19, 10:00 UTC to Oct 19, 12:00 UTC (2 hours)."
    # Below the line: an early warning, no firing sentence.
    assert _alert_json(_rising(True, after=0.008), rule)["line"] == "Still below the 1% alert line."


def test_a_value_already_past_the_line_before_the_change_doesnt_say_when_the_alert_fires() -> None:
    # Above the line before and after: the alert has been firing all along.
    rule = _alert("CheckoutErrors", 'error_rate{service="checkout"} > 0.003', duration=300)
    assert _alert_json(_rising(True), rule)["line"] == "Above the 0.3% alert line both before and after the change."


def test_a_summary_never_replaces_why_it_matters() -> None:
    finding, signals = _rising()
    rule = _alert("CheckoutErrors", 'error_rate{service="checkout"} > 0.01', summary="{{ $labels.service }} error rate above 1%")
    matched = matching_alerts(_rules(rule), finding.metric_name, finding.service, SERVICE_LABELS)
    wording = load_wording()
    shown = build_plain(finding, signals, wording, matched, SERVICE_LABELS).to_json(wording)

    assert shown["alert"]["text"] is None
    assert shown["alert"]["summary"] == "checkout error rate above 1%"
    # The template's Why it matters stays.
    assert shown["why"] == build_plain(finding, signals, wording).why


def test_a_spike_past_the_line_doesnt_say_when_the_alert_fires() -> None:
    finding, signals = _real(8286)  # payments error rate, one reading up to 1.7%
    rule = _alert("PaymentsErrors", 'error_rate{service="payments"} > 0.01', duration=300)
    matched = matching_alerts(_rules(rule), finding.metric_name, finding.service, SERVICE_LABELS)
    wording = load_wording()
    shown = build_plain(finding, signals, wording, matched, SERVICE_LABELS).to_json(wording)["alert"]
    assert utc_text(shown["line"]) == "Went past the 1% alert line, reaching 1.7%."


@pytest.mark.parametrize(
    ("after", "line_alert"),
    [
        (0.025, "Critical"),  # past both lines: the most severe one
        (0.015, "Warning"),  # past the warning line only
        (0.008, "Warning"),  # past neither: the nearest one
    ],
)
def test_with_warning_and_critical_lines_the_one_that_matters_is_shown(after: float, line_alert: str) -> None:
    shown = _alert_json(
        _rising(True, after=after),
        _alert("Warning", 'error_rate{service="checkout"} > 0.01', description="Some orders fail."),
        _alert("Critical", 'error_rate{service="checkout"} > 0.02', description="Checkout is down for many customers."),
    )
    assert shown["line_alert"] == line_alert
    assert shown["name"] == line_alert


def test_a_target_set_in_the_wording_file_wins_over_the_alert_line() -> None:
    raw = yaml.safe_load(TEMPLATES_PATH.read_text(encoding="utf-8"))
    raw["services"] = {"checkout": {"targets": {"error_rate": {"below": 0.02}}}}
    wording = parse_wording(raw)

    shown = _alert_json(_rising(), _alert("A", 'error_rate{service="checkout"} > 0.01', description="Orders fail.", runbook_url="https://wiki/r"), wording=wording)

    assert shown["line"] is None
    assert (shown["text"], shown["runbook_url"]) == ("Orders fail.", "https://wiki/r")


def test_an_alert_without_a_plain_line_still_gives_its_text_and_one_without_anything_gives_none() -> None:
    shown = _alert_json(_rising(), _alert("Ratio", "error_rate / requests > 0.01", description="Orders fail."))
    assert (shown["text"], shown["line"]) == ("Orders fail.", None)

    assert _alert_json(_rising(), _alert("Bare", "rate(error_rate[5m]) > 1")) is None


def test_the_text_comes_from_an_alert_that_has_some_when_the_lined_one_has_none() -> None:
    shown = _alert_json(
        _rising(),
        _alert("Line", 'error_rate{service="checkout"} > 0.01'),
        _alert("Words", 'error_rate{service="checkout"} / 2 > 0', description="Orders fail.", runbook_url="https://wiki/r"),
    )
    assert (shown["name"], shown["text"], shown["line_alert"]) == ("Words", "Orders fail.", "Line")
    assert shown["line"].startswith("Above the 1% alert line")


def test_without_an_alert_the_wording_is_unchanged() -> None:
    finding, signals = _real(8300)
    wording = load_wording()
    assert build_plain(finding, signals, wording).to_json(wording)["alert"] is None


# --- New Analysis: the alerts on a recording rule ---------------------------------------------------


def test_a_recording_rule_lists_the_alerts_built_on_it() -> None:
    recorded = parse_recording_rules({"data": {"groups": [{"name": "lab-rules", "interval": 15, "rules": [
        {"type": "recording", "name": "service:error_rate:percent", "query": "100 * avg by (service, env) (error_rate)", "health": "ok"},
        {"type": "recording", "name": "service:latency:p95", "query": "max by (service) (latency)", "health": "ok"},
    ]}]}})
    alerts = _rules(
        _alert(
            "SpikeLabErrorRateHigh",
            'service:error_rate:percent{service="spike-lab"} > 5',
            duration=300,
            description="{{ $labels.service }} orders fail at checkout.",
            runbook_url="https://wiki/r",
        ),
        _alert("Mixed", "service:error_rate:percent * 2 > 1"),
    )

    errors, latency = with_alerts(recorded, alerts)

    assert [alert.model_dump() for alert in errors.alerts] == [
        {"name": "SpikeLabErrorRateHigh", "group": "alerts", "text": "spike-lab orders fail at checkout.", "fires": "above 5", "wait": "5 minutes", "runbook_url": "https://wiki/r"},
        {"name": "Mixed", "group": "alerts", "text": None, "fires": None, "wait": None, "runbook_url": None},
    ]
    assert latency.alerts == []


# --- Findings API ----------------------------------------------------------------------------------


def _seed(db, finding_id: int, connection_id: str | None, source_type: str = "prometheus") -> None:
    item = REAL[finding_id]
    now = datetime.now(timezone.utc)
    db.add(AnalysisRunEntity(
        id=item["analysis_run_id"], source_type=source_type, provider=source_type, service=item["service"], metric_name=item["metric_name"],
        start_time=now - timedelta(hours=1), end_time=now, sample_count=60, status="completed", connection_id=connection_id,
    ))
    for signal in item["signals"]:
        db.add(SignalEntity(
            signal_id=signal["signal_id"], signal_type=signal["signal_type"], analyzer_id=signal["analyzer_id"], metric_name=item["metric_name"],
            service=item["service"], severity="high", start_time=datetime.fromisoformat(signal["start_time"]) if signal["start_time"] else None,
            end_time=datetime.fromisoformat(signal["end_time"]) if signal["end_time"] else None, evidence_json=signal["evidence"],
            importance_score=0.7, analysis_run_id=item["analysis_run_id"],
        ))
    db.add(FindingEntity(
        id=finding_id, analysis_run_id=item["analysis_run_id"], service=item["service"], metric_name=item["metric_name"], title=item["title"],
        summary=item["summary"], category=item["category"], health_status="significant", importance_score=0.7, investigation_priority=2,
        signal_ids=[signal["signal_id"] for signal in item["signals"]], comparison_json=item["comparison_json"],
        event_start=datetime.fromisoformat(item["event_start"]) if item["event_start"] else None,
        event_end=datetime.fromisoformat(item["event_end"]) if item["event_end"] else None, created_at=now,
    ))
    db.commit()


ERRORS_ALERT = _alert("SpikeLabErrorRateHigh", 'error_rate{service="spike-lab"} > 0.05', description="Orders fail at checkout.", runbook_url="https://wiki/r")


def test_findings_api_adds_the_alert_of_the_runs_connection(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []

    def rules(connection):
        asked.append(connection.id)
        return _rules(ERRORS_ALERT)

    monkeypatch.setattr(alert_rules_module, "_connection_rules", rules)
    with get_session_local()() as db:
        _seed(db, 8300, "default")

    listed = {item["id"]: item for item in client.get("/api/findings").json()}
    one = client.get("/api/findings/8300").json()

    for shown in (listed[8300]["plain"]["alert"], one["plain"]["alert"]):
        assert (shown["name"], shown["text"], shown["runbook_url"]) == ("SpikeLabErrorRateHigh", "Orders fail at checkout.", "https://wiki/r")
        assert utc_text(shown["line"]) == "Back below the 5% alert line since Oct 19, 22:54 UTC."
    assert asked and set(asked) == {"default"}


def test_findings_without_a_prometheus_connection_never_ask_for_rules(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def rules(_connection):
        raise AssertionError("rules were read for an OTLP finding")

    monkeypatch.setattr(alert_rules_module, "_connection_rules", rules)
    with get_session_local()() as db:
        _seed(db, 8300, None, source_type="otlp")

    [finding] = client.get("/api/findings").json()
    assert finding["plain"]["alert"] is None


def test_an_unreachable_ruler_leaves_findings_as_they_are(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    class Down:
        def __init__(self, config):
            self.config = config

        def rules(self, rule_type=None):
            raise HTTPException(status_code=504, detail="Prometheus request timed out")

    monkeypatch.setattr(alert_rules_module, "PrometheusQueryService", Down)
    monkeypatch.setattr(alert_rules_module, "_connection_rules", lambda connection: alert_rules_module.alert_rules(Down(connection)))
    with get_session_local()() as db:
        _seed(db, 8300, "default")

    response = client.get("/api/findings")
    assert response.status_code == 200
    assert response.json()[0]["plain"]["alert"] is None
    assert response.json()[0]["plain"]["headline"] == "Error rate dropped sharply and stayed lower"


def test_the_lookup_asks_with_a_short_timeout_and_skips_unconfigured_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()
    seen: list[float] = []

    class Recorder:
        def __init__(self, config):
            self.config = config

        def rules(self, rule_type=None):
            seen.append(self.config.timeout_seconds)
            return _payload()

    monkeypatch.setattr(alert_rules_module, "PrometheusQueryService", Recorder)
    assert alert_rules_module._connection_rules(PrometheusConnectionConfig(id="a", base_url="http://p:9090", timeout_seconds=30)) == []
    assert alert_rules_module._connection_rules(PrometheusConnectionConfig(id="b", base_url=None)) == []
    assert seen == [alert_rules_module.LOOKUP_TIMEOUT_SECONDS]


# --- The rules hold for every kind of finding, line and annotation ----------------------------------
# Each rule is worked out from the finding's own numbers, not from what the code writes, so a fix
# that only suits one example fails here.

_ANNOTATIONS = {
    "description": {"summary": "{{ $labels.service }} above threshold", "description": "Customers of {{ $labels.service }} are affected by this."},
    "summary_restates": {"summary": "{{ $labels.service }} metric above threshold"},
    "summary_impact": {"summary": "Customers can't complete checkout"},
    "description_value_only": {"summary": "High value", "description": "Value is {{ $value | humanize }}."},
    "none": {},
}


def _synthetic(before: float, after: float) -> dict:
    return {
        "metric_name": "error_rate", "service": "checkout", "category": "behavior_change", "comparison_json": {},
        "title": "error_rate experienced a persistent baseline shift during the selected time window.",
        "event_start": None, "event_end": "2026-10-19T12:00:00+00:00",
        "signals": [{"signal_type": "ruptures", "analyzer_id": "ruptures", "start_time": None, "end_time": None,
                     "evidence": {"left_mean": before, "right_mean": after, "percent_change": (after - before) / before * 100, "change_point_time": "2026-10-19T10:00:00Z"}}],
    }


_ITEMS = {**{f"#{key}": item for key, item in REAL.items()}, "rising": _synthetic(0.004, 0.021), "falling": _synthetic(0.021, 0.004)}


def _matrix_cases():
    wording = load_wording()
    for label, item in _ITEMS.items():
        finding = FindingFacts(item["metric_name"], item["service"], item["title"], item["category"], item["comparison_json"] or {}, item["event_start"], item["event_end"])
        signals = [SignalFacts(s["signal_type"], s["analyzer_id"], s["evidence"] or {}, s["start_time"], s["end_time"]) for s in item["signals"] or []]
        base = build_plain(finding, signals, wording)
        if base is None:
            continue
        values = sorted(v for v in (_number(base.facts.get(key)) for key in ("before", "after", "first", "second", "peak", "value")) if v is not None) or [1.0]
        limits = sorted({round(values[0] * 0.5, 6) or -1.0, round((values[0] + values[-1]) / 2, 6), round(values[-1] * 1.5 + 1e-9, 6)})
        for ongoing in ([None, True, False] if base.kind == "level_change" else [None]):
            for op in (">", "<"):
                for limit in limits:
                    for style in _ANNOTATIONS:
                        yield pytest.param(label, ongoing, op, limit, style, id=f"{label}-{ongoing}-{op}{limit}-{style}")


def _number(value):
    return float(value) if isinstance(value, (int, float)) else None


@pytest.mark.parametrize(("label", "ongoing", "op", "limit", "style"), list(_matrix_cases()))
def test_alert_wording_rules_hold_for_every_case(label: str, ongoing, op: str, limit: float, style: str) -> None:
    item = _ITEMS[label]
    finding = FindingFacts(item["metric_name"], item["service"], item["title"], item["category"], item["comparison_json"] or {}, item["event_start"], item["event_end"], ongoing)
    signals = [SignalFacts(s["signal_type"], s["analyzer_id"], s["evidence"] or {}, s["start_time"], s["end_time"]) for s in item["signals"] or []]
    [rule] = _rules(_alert("TeamAlert", f'{item["metric_name"]}{{service="{item["service"]}"}} {op} {limit}', duration=300, **_ANNOTATIONS[style]))
    wording = load_wording()
    plain = build_plain(finding, signals, wording, matching_alerts([rule], item["metric_name"], item["service"], SERVICE_LABELS), SERVICE_LABELS)
    alert = plain.to_json(wording)["alert"]
    if alert is None:
        return
    line = alert["line"] or ""

    def past(value):
        return value is not None and (value > limit if op == ">" else value < limit)

    before, after = past(_number(plain.facts.get("before"))), past(_number(plain.facts.get("after")))
    # Rule 1: the firing sentence only when the change crossed the line and the problem goes on.
    assert ("fires once" in line) == (plain.kind == "level_change" and not before and after and ongoing is not False)
    # Rule 2: Why it matters comes from the description only, never the summary.
    description = alert_text(rule, alert_labels(rule, item["metric_name"], item["service"], SERVICE_LABELS))
    assert alert["text"] == description
    # Rule 3: the line names the state the numbers say.
    if line and plain.kind == "level_change":
        expected = "both before and after" if before and after else "Back " if before else "Still " if not after else "line since|line from"
        assert any(token in line for token in expected.split("|")), line
