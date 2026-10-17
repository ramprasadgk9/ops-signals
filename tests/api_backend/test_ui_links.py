"""QA-24: alert messages and tickets linked to http://localhost:3000 when OPS_SIGNALS_UI_BASE_URL
wasn't set, which opens nothing for anyone reading them elsewhere. Without it the links are left
out, and startup says so."""

from __future__ import annotations

import logging

from backend.app.config import get_alert_enrichment_config, ui_base_url
from backend.app.main import warn_if_links_have_no_ui_address
from backend.app.notifications.message_builder import build_alert_enrichment_blocks, build_alert_resolved_blocks

_ENRICHMENT = {
    "source": "alertmanager",
    "alert": {"name": "HighCPU", "service": "checkout", "fingerprint": "abc"},
    "analysis": {},
    "context": {"recommendation": "investigate", "history": {}, "similar_cases": [{"case_id": 7, "title": "CPU spike", "similarity_score": 0.9}]},
}


def _text(message: dict) -> str:
    return str(message["blocks"])


def test_without_a_ui_address_messages_have_no_links(monkeypatch) -> None:
    monkeypatch.delenv("OPS_SIGNALS_UI_BASE_URL", raising=False)
    assert ui_base_url() is None
    assert get_alert_enrichment_config().ui_base_url is None

    firing = _text(build_alert_enrichment_blocks(_ENRICHMENT, None))
    resolved = _text(build_alert_resolved_blocks(_ENRICHMENT, None, 12))

    assert "localhost" not in firing + resolved
    assert "<" not in firing.replace("<!", "")
    assert "#7 CPU spike" in firing
    assert "Open findings" not in firing
    assert "Record the outcome on a case" in resolved


def test_with_a_ui_address_messages_link_to_it(monkeypatch) -> None:
    monkeypatch.setenv("OPS_SIGNALS_UI_BASE_URL", "https://ops.example.com/")
    base = ui_base_url()
    assert base == "https://ops.example.com"

    firing = _text(build_alert_enrichment_blocks(_ENRICHMENT, base))

    assert "<https://ops.example.com/cases/7|#7 CPU spike>" in firing
    assert "<https://ops.example.com/findings|Open findings>" in firing


def test_startup_warns_only_when_something_would_link(monkeypatch, caplog) -> None:
    monkeypatch.delenv("OPS_SIGNALS_UI_BASE_URL", raising=False)
    monkeypatch.setenv("OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED", "true")
    with caplog.at_level(logging.WARNING):
        warn_if_links_have_no_ui_address()
    assert "OPS_SIGNALS_UI_BASE_URL is not set, so alert messages" in caplog.text

    caplog.clear()
    monkeypatch.setenv("OPS_SIGNALS_UI_BASE_URL", "https://ops.example.com")
    with caplog.at_level(logging.WARNING):
        warn_if_links_have_no_ui_address()
    assert "OPS_SIGNALS_UI_BASE_URL" not in caplog.text
