"""The production analysis path, set up for benchmark harnesses: no database, no embeddings.

Every public-dataset harness (NAB, TCPD, ...) runs series through the same SignalPipeline a CSV
upload uses with the `generic` provider, so what's measured is what users get. Only persistence is
stubbed out.
"""

from __future__ import annotations

import copy

from backend.app.services.timeseries_routing_service import load_routing_app_config
from intelligence.pipeline import SignalPipeline

PROVIDER = "generic"


class NullStore:
    """Accepts and discards every store call - a harness needs results, not persistence."""

    def __getattr__(self, name: str):
        return lambda *args, **kwargs: None


class StubEmbedder:
    def embed(self, text: str) -> list[float]:
        return [0.0]


_BASE_CONFIG = None


def _base_config():
    global _BASE_CONFIG
    if _BASE_CONFIG is None:
        config = load_routing_app_config(PROVIDER)
        for attribute in ("save_normalized_data", "save_signals", "save_question_answers", "save_embeddings"):
            setattr(config.output, attribute, False)
        config.capabilities.auto_register = False
        config.questions.auto_generate_from_capabilities = False
        _BASE_CONFIG = config
    return _BASE_CONFIG


def build_pipeline(interval_minutes: int, metric_name: str) -> SignalPipeline:
    """The generic provider's pipeline with the two inputs a user sets on upload: the series'
    sampling interval, and allowing negative values (public datasets have legitimate ones)."""
    config = copy.deepcopy(_base_config())
    config.input.interval = f"{interval_minutes}m"
    config.input.metric_name = metric_name
    config.input.validation = {**(config.input.validation or {}), "allow_negative_values": True}
    return SignalPipeline(config, store=NullStore(), embedder=StubEmbedder())
