"""The production analysis path, set up for benchmark harnesses: no database, no embeddings.

Every public-dataset harness (NAB, TCPD, ...) runs series through the same SignalPipeline a CSV
upload uses with the `generic` provider, so what's measured is what users get. Only persistence is
stubbed out.
"""

from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pandas as pd

from backend.app.services.timeseries_routing_service import load_routing_app_config
from benchmark.methods import ALL_ANALYZERS, ROUTER_PICKS
from intelligence.analyzers.base import Analyzer
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


NO_OVERRIDES = Path("/nonexistent/analyzer_overrides.d")


class OnlyAnalyzersPipeline(SignalPipeline):
    """The production pipeline with exactly the given analyzers, whatever the router decides.
    Normalization, finding rules and importance scoring stay the product's own."""

    def __init__(self, *args, only: tuple[str, ...], **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.only = set(only)

    def _build_analyzers(self, analyzer_routing: list[dict[str, object]] | None = None) -> list[Analyzer]:
        return [analyzer for analyzer in super()._build_analyzers(None) if analyzer.analyzer_id in self.only]


def build_pipeline(
    interval_minutes: int, metric_name: str, analyzers: str | tuple[str, ...] = ROUTER_PICKS
) -> SignalPipeline:
    """The generic provider's pipeline with the two inputs a user sets on upload: the series'
    sampling interval, and allowing negative values (public datasets have legitimate ones).

    `analyzers` picks what runs: ROUTER_PICKS (the product default - the router's top picks above
    the score threshold, plus always-run analyzers), ALL_ANALYZERS (every enabled analyzer, the
    "run everything" baseline), or a tuple of analyzer ids to run only those."""
    config = copy.deepcopy(_base_config())
    config.input.interval = f"{interval_minutes}m"
    config.input.metric_name = metric_name
    config.input.validation = {**(config.input.validation or {}), "allow_negative_values": True}
    if analyzers == ROUTER_PICKS:
        pipeline = SignalPipeline(config, store=NullStore(), embedder=StubEmbedder())
    else:
        config.analysis.selection_mode = "all"
        if analyzers == ALL_ANALYZERS:
            pipeline = SignalPipeline(config, store=NullStore(), embedder=StubEmbedder())
        else:
            pipeline = OnlyAnalyzersPipeline(config, store=NullStore(), embedder=StubEmbedder(), only=tuple(analyzers))
    # Benchmarks measure the shipped settings, not per-service overrides someone added locally.
    pipeline.overrides_dir = NO_OVERRIDES
    return pipeline


_WARMED_UP = False


def warm_up() -> None:
    """Run every analyzer once on a small series, once per process, before anything is timed.
    Some analyzers compile on first use (stumpy's numba kernels take seconds), and without this
    that one-time cost lands on whichever method happens to run first, skewing time comparisons."""
    global _WARMED_UP
    if _WARMED_UP:
        return
    _WARMED_UP = True
    rng = np.random.default_rng(0)
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2000-01-01", periods=400, freq="5min", tz="UTC"),
            "value": 10 + rng.normal(0, 1, 400),
            "metric_name": "warm_up",
        }
    )
    try:
        build_pipeline(5, "warm_up", ALL_ANALYZERS).run_dataframe(frame)
    except Exception:
        pass


def user_facing_signals(result) -> list:
    """The signals a user actually sees: those that became part of a finding. Each analyzer's own
    finding rules (e.g. pyod_outlier's minimum outlier points and confidence) decide this inside the
    pipeline; a signal left out of every finding was a hunch the product itself dropped, so it
    counts as neither a catch nor a false alarm."""
    kept = {signal_id for finding in result.findings for signal_id in finding.signal_ids}
    return [signal for signal in result.signals if signal.signal_id in kept]
