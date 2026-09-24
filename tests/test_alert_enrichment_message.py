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
