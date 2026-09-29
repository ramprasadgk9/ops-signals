from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from intelligence.analyzers.stumpy import STUMPYAnalyzer


def test_stumpy_analyzer_uses_real_stumpy_library_when_installed() -> None:
    values = [1.0, 2.0, 3.0, 1.0, 2.0, 3.0, 5.0, 6.0, 1.0, 2.0, 3.0, 7.0]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    dataframe = pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=index) for index in range(len(values))],
            "value": values,
            "metric_name": ["cpu_usage"] * len(values),
            "service": ["checkout"] * len(values),
            "env": ["prod"] * len(values),
        }
    )

    signals = STUMPYAnalyzer(window_size=3, profile_threshold=10.0).analyze(dataframe)

    assert len(signals) == 1
    assert signals[0].evidence["library"] == "stumpy"
    assert signals[0].evidence["algorithm"] == "stump"
    assert signals[0].evidence["implementation"]["library"] == "stumpy"
    assert signals[0].evidence["implementation"]["algorithm"] == "stump"
    assert signals[0].evidence["implementation"]["window_size"] == 4
    assert signals[0].confidence >= 0.75
    assert signals[0].evidence["finding_rules"]["max_motif_distance"] == 1.0
    assert signals[0].evidence["finding_rule_matched"] is True


def test_stumpy_analyzer_marks_finding_rule_as_unmatched_for_weak_motif() -> None:
    values = [1.0, 2.0, 3.0, 1.4, 2.4, 3.4, 5.0, 6.0, 1.8, 2.8, 3.8, 7.0]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    dataframe = pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=index) for index in range(len(values))],
            "value": values,
            "metric_name": ["cpu_usage"] * len(values),
            "service": ["checkout"] * len(values),
            "env": ["prod"] * len(values),
        }
    )

    signals = STUMPYAnalyzer(
        window_size=3,
        profile_threshold=10.0,
        finding_rules={"max_motif_distance": 0.01, "min_confidence": 0.99},
    ).analyze(dataframe)

    assert signals
    assert signals[0].evidence["finding_rule_matched"] is False


def _daily_cycle(days: int = 10, odd_day: int | None = None, noise_seed: int = 3) -> pd.DataFrame:
    # A 5-minute metric that repeats the same daily shape, with a little noise; odd_day (if set)
    # is replaced by a flat, raised day unlike any other.
    timestamps = pd.date_range("2026-01-01", periods=days * 288, freq="5min", tz="UTC")
    hours = (timestamps.hour + timestamps.minute / 60).to_numpy()
    values = 50 + 20 * np.sin(2 * np.pi * hours / 24) + np.random.default_rng(noise_seed).normal(0, 1, len(timestamps))
    if odd_day is not None:
        values[odd_day * 288 : (odd_day + 1) * 288] = 65 + np.random.default_rng(9).normal(0, 1, 288)
    return pd.DataFrame(
        {"timestamp": timestamps, "value": values, "metric_name": "requests", "service": "checkout", "env": "prod"}
    )


DISCORD = {"mode": "discord"}


def test_discord_mode_reports_the_one_day_unlike_the_others() -> None:
    [signal] = STUMPYAnalyzer(implementation=DISCORD).analyze(_daily_cycle(odd_day=6))

    assert signal.signal_type == "anomaly"
    assert signal.evidence["detector"] == "matrix_profile_discord"
    assert 280 <= signal.evidence["window_size"] <= 296  # about one period: a day of 5-minute points
    assert signal.evidence["surprise"] >= 8.0
    odd_start = pd.Timestamp("2026-01-07", tz="UTC")
    assert odd_start - pd.Timedelta(days=1) <= signal.start_time <= odd_start + pd.Timedelta(days=1)


def test_discord_mode_stays_quiet_when_every_day_looks_alike() -> None:
    # Every series has a most unusual stretch; on a clean daily cycle none stands out enough.
    assert STUMPYAnalyzer(implementation=DISCORD).analyze(_daily_cycle()) == []


def test_discord_mode_threshold_is_a_finding_rule() -> None:
    signals = STUMPYAnalyzer(implementation=DISCORD, finding_rules={"min_surprise": 1000.0}).analyze(_daily_cycle(odd_day=6))

    assert signals == []


def test_motif_mode_stays_the_default() -> None:
    # Analyzer Labs' motif page constructs the analyzer without a mode.
    assert STUMPYAnalyzer().config.mode == "motif"
