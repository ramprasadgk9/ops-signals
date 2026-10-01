from __future__ import annotations

import json

from backend.app.notifications.message_builder import build_alert_enrichment_blocks, build_alert_resolved_blocks

UI = "http://ops-signals.local"


def _enrichment(**overrides) -> dict:
    enrichment = {
        "source": "alertmanager",
        "alert": {
            "name": "CheckoutHighLatency",
            "status": "firing",
            "service": "checkout-api",
            "severity": "warning",
            "summary": "checkout-api p95 latency above 300ms",
            "starts_at": "2026-09-23T14:13:00+00:00",
            "fingerprint": "a1b2c3d4",
            "generator_url": "http://prometheus:9090/graph?g0.expr=x",
            "external_url": "http://alertmanager:9093",
            "metric_key": "http_request_duration_seconds_bucket",
        },
        "analysis": {
            "status": "analyzed",
            "lookback_seconds": 21600,
            "finding": {
                "id": 7,
                "title": "Sustained latency baseline shift on checkout-api",
                "summary": "p95 moved from ~180ms to ~420ms.",
                "health_status": "significant",
                "importance_score": 0.82,
            },
            "change_point_time": "2026-09-23T14:08:00+00:00",
            "timing": {"basis": "step_change", "time": "2026-09-23T14:08:00+00:00", "analyzer_id": "baseline_shift", "trend_direction": None},
        },
        "changes": {
            "service_has_any_events": True,
            "window_before_minutes": 30,
            "matches": [
                {
                    "id": 1,
                    "event_type": "deploy",
                    "version": "v2.3.1",
                    "author": "alice",
                    "url": "https://github.com/acme/checkout/pull/812",
                    "minutes_before_anchor": 5.8,
                }
            ],
        },
        "context": {
            "recommendation": "likely_real",
            "history": {"total_prior_occurrences": 4, "confirmed": 3, "rejected": 1, "most_common_root_cause": "db_pool"},
            "similar_cases": [
                {"case_id": 112, "title": "checkout latency after release", "similarity_score": 0.81, "outcome_summary": "Raised pool to 50"}
            ],
            "raw_activity": {"total_occurrences": 0},
        },
    }
    enrichment.update(overrides)
    return enrichment


def _text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def test_message_clearly_identifies_it_came_from_an_alertmanager_alert() -> None:
    payload = build_alert_enrichment_blocks(_enrichment(), UI)
    header = payload["blocks"][0]["text"]["text"]
    origin = payload["blocks"][1]["elements"][0]["text"]
    footer = payload["blocks"][-1]["elements"][0]["text"]

    assert header == "🟡 [FIRING] CheckoutHighLatency · checkout-api"
    assert origin.startswith("🔔 *Alertmanager alert*")
    assert "rule `CheckoutHighLatency`" in origin
    assert "<http://alertmanager:9093|Alertmanager>" in origin
    assert "<http://prometheus:9090/graph?g0.expr=x|view rule source>" in origin
    assert footer.startswith("Enriched by Ops Signals from an alertmanager alert")
    assert "fingerprint `a1b2c3d4`" in footer


def test_generic_source_is_labelled_as_external_alert() -> None:
    payload = build_alert_enrichment_blocks(_enrichment(source="generic"), UI)
    assert "*External alert*" in _text(payload)
    assert "Alertmanager alert" not in _text(payload)


def test_all_three_sections_render_their_evidence() -> None:
    text = _text(build_alert_enrichment_blocks(_enrichment(), UI))
    assert "Sustained latency baseline shift" in text
    assert "around *14:08 UTC*" in text
    assert "Started *6 min after*" in text
    assert "<https://github.com/acme/checkout/pull/812|deploy `v2.3.1`> by alice" in text
    assert "Verdict: *likely real*" in text
    assert f"<{UI}/cases/112|#112 checkout latency after release>" in text
    assert "Fix: Raised pool to 50" in text


def test_skipped_analysis_and_empty_history_still_produce_a_useful_message() -> None:
    enrichment = _enrichment(
        analysis={"status": "skipped", "reason": "status_alert", "reason_text": "status/health alert", "lookback_seconds": 21600},
        changes={"service_has_any_events": False, "matches": []},
        context={"recommendation": "insufficient_history", "history": {}, "similar_cases": [], "raw_activity": {}},
    )
    text = _text(build_alert_enrichment_blocks(enrichment, UI))
    assert "Not analyzed: status/health alert." in text
    assert "No change events have ever been recorded for `checkout-api`" in text
    assert "First time Ops Signals has seen this alert." in text


def test_reused_finding_says_how_much_earlier_it_was_detected() -> None:
    analysis = dict(_enrichment()["analysis"], status="reused", detected_before_alert_minutes=5.0)
    text = _text(build_alert_enrichment_blocks(_enrichment(analysis=analysis), UI))
    assert "detected this *5 min before* the alert fired" in text


def test_unavailable_lookups_are_said_plainly() -> None:
    text = _text(build_alert_enrichment_blocks(_enrichment(changes=None, context=None), UI))
    assert "Change-event lookup unavailable." in text
    assert "History lookup unavailable." in text


def test_header_is_truncated_to_slack_limit() -> None:
    alert = dict(_enrichment()["alert"], name="A" * 300)
    payload = build_alert_enrichment_blocks(_enrichment(alert=alert), UI)
    assert len(payload["blocks"][0]["text"]["text"]) <= 150


def test_resolved_message_names_the_alertmanager_alert_and_duration() -> None:
    payload = build_alert_resolved_blocks(_enrichment(), UI, open_minutes=22)
    text = _text(payload)
    assert payload["blocks"][0]["text"]["text"] == "✅ [RESOLVED] CheckoutHighLatency · checkout-api"
    assert "*Alertmanager alert* `CheckoutHighLatency` resolved after 22 min" in text


def _what_changed_text(timing: dict | None, matches: list[dict] | None = None) -> str:
    enrichment = _enrichment()
    enrichment["analysis"]["timing"] = timing
    if matches is not None:
        enrichment["changes"]["matches"] = matches
    payload = build_alert_enrichment_blocks(enrichment, UI)
    return next(block["text"]["text"] for block in payload["blocks"] if "What changed" in block.get("text", {}).get("text", ""))


DEPLOY = {"id": 1, "event_type": "deploy", "version": "v4.1", "author": "bob", "minutes_before_anchor": 2.0}


def test_step_change_says_started_after_and_names_where_the_start_time_came_from() -> None:
    text = _what_changed_text({"basis": "step_change", "time": "2026-09-23T14:08:00+00:00", "analyzer_id": "baseline_shift"})
    assert "• Started *6 min after* <https://github.com/acme/checkout/pull/812|deploy `v2.3.1`> by alice" in text
    assert "_Start time 14:08 UTC, from a step change (baseline shift)._" in text


def test_spike_on_a_trend_times_the_spike_and_says_the_trend_is_separate() -> None:
    text = _what_changed_text(
        {"basis": "spike", "time": "2026-09-23T13:58:00+00:00", "analyzer_id": "anomaly_zscore", "trend_direction": "upward"},
        [DEPLOY],
    )
    assert "• Spike started *2 min after* deploy `v4.1` by bob" in text
    assert "from a spike (z-score). It sits on a gradual upward trend, which these changes may not explain." in text


def test_trend_lists_changes_for_reference_without_claiming_a_start() -> None:
    text = _what_changed_text({"basis": "trend", "time": None, "trend_direction": "upward"}, [{**DEPLOY, "minutes_before_anchor": 10.0}])
    assert "Gradual upward trend with no clear start time. Changes near when the alert fired, for reference:" in text
    assert "• deploy `v4.1` by bob, 10 min before the alert fired" in text
    assert "rarely explained by a single change" in text
    assert "Started" not in text


def test_no_start_time_says_so_instead_of_implying_one() -> None:
    for timing in ({"basis": "alert_time"}, None):
        text = _what_changed_text(timing, [{**DEPLOY, "minutes_before_anchor": -3.0}])
        assert "No start time found in the metric. Changes near when the alert fired, for reference:" in text
        assert "• deploy `v4.1` by bob, 3 min after the alert fired" in text
        assert "Started" not in text


def test_no_matching_changes_names_the_window_it_searched() -> None:
    step = _what_changed_text({"basis": "step_change", "time": "2026-09-23T14:08:00+00:00", "analyzer_id": "ruptures"}, [])
    assert "No changes recorded for `checkout-api` in the 30 min before the step change at 14:08 UTC." in step
    trend = _what_changed_text({"basis": "trend", "trend_direction": "downward"}, [])
    assert trend.endswith("Gradual downward trend with no clear start time. No changes recorded for `checkout-api` in the 30 min before the alert fired.")
