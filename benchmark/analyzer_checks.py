"""Own-scenario checks for every analyzer: does it report the kind of problem it's built for, and stay
quiet on healthy data?

The public datasets only have answer keys for anomalies (NAB, UCR, SMD) and change points (TCPD). A
trend, a repeating pattern, a gap or a flatline isn't marked in any of them, so trend, stumpy and
data_health can only be checked on scenarios with a known answer. Every analyzer gets:

- target cases: a scenario containing its kind of problem. Pass = it reports a signal of that kind.
- the healthy control (cpu_healthy_stable_v1): stable CPU with no problem. Pass = it reports nothing.

The data_health targets are the healthy series with a problem put in on purpose: two hours of rows
removed (a gap) and two hours held at the series' median (a flatline), both mid-series.

Each analyzer runs alone through the production pipeline, and only what a user would see counts: signals
that became part of a finding, after the analyzer's own finding rules. Raw signal counts are kept too.

This is this project's own test with its own answer key - a regression check, not independent evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from benchmark import harness
from benchmark.router_benchmark import PROJECT_ROOT

SCENARIOS = PROJECT_ROOT / "benchmark" / "scenarios"
CONTROL = "cpu_healthy_stable_v1"
GAP_ROWS = (1000, 1024)  # 24 rows of 5-minute data = 2 hours
FLATLINE_ROWS = (1300, 1324)


def _scenario(name: str) -> Callable[[], pd.DataFrame]:
    return lambda: pd.read_csv(SCENARIOS / name / "dataset.csv")


def _with_gap() -> pd.DataFrame:
    frame = pd.read_csv(SCENARIOS / CONTROL / "dataset.csv")
    return frame.drop(index=range(*GAP_ROWS)).reset_index(drop=True)


def _with_flatline() -> pd.DataFrame:
    frame = pd.read_csv(SCENARIOS / CONTROL / "dataset.csv")
    frame.loc[FLATLINE_ROWS[0] : FLATLINE_ROWS[1] - 1, "value"] = float(frame["value"].median())
    return frame


@dataclass(frozen=True)
class Case:
    name: str
    description: str
    build: Callable[[], pd.DataFrame]


TARGETS: dict[str, list[tuple[Case, set[str]]]] = {
    "trend": [(Case("cpu_linear_trend_v1", "CPU climbing steadily", _scenario("cpu_linear_trend_v1")), {"trend"})],
    "stumpy": [(Case("cpu_pure_seasonality_v1", "CPU repeating a daily pattern", _scenario("cpu_pure_seasonality_v1")), {"pattern_discovery"})],
    "ruptures": [(Case("cpu_pure_baseline_shift_v1", "CPU jumping to a new level", _scenario("cpu_pure_baseline_shift_v1")), {"ruptures"})],
    "baseline_shift": [(Case("cpu_pure_baseline_shift_v1", "CPU jumping to a new level", _scenario("cpu_pure_baseline_shift_v1")), {"baseline_shift"})],
    "pyod_outlier": [(Case("cpu_isolated_spikes_v1", "CPU with short isolated spikes", _scenario("cpu_isolated_spikes_v1")), {"anomaly"})],
    "anomaly_zscore": [(Case("cpu_isolated_spikes_v1", "CPU with short isolated spikes", _scenario("cpu_isolated_spikes_v1")), {"anomaly", "anomaly_zscore"})],
    "data_health": [
        (Case("healthy_with_gap", "Healthy CPU with 2 hours of data missing", _with_gap), {"data_gap"}),
        (Case("healthy_with_flatline", "Healthy CPU stuck at one value for 2 hours", _with_flatline), {"flatline"}),
    ],
    # No own scenario has a time-of-day anomaly yet; seasonal_anomaly gets the healthy control only.
    "seasonal_anomaly": [],
}


def run_analyzer_checks(raw_dir: Path | None = None) -> dict[str, Any]:
    control = Case(CONTROL, "Stable, healthy CPU", _scenario(CONTROL))
    analyzers: dict[str, Any] = {}
    for analyzer_id, targets in TARGETS.items():
        checks = []
        for case, kinds in targets:
            seen, raw = _signals(analyzer_id, case)
            found = [s for s in seen if s.signal_type in kinds]
            checks.append({"case": case.name, "description": case.description, "kind": "target", "expected": sorted(kinds),
                           "signals": len(found), "raw_signals": raw, "passed": bool(found)})
        seen, raw = _signals(analyzer_id, control)
        checks.append({"case": control.name, "description": control.description, "kind": "control", "expected": [],
                       "signals": len(seen), "raw_signals": raw, "passed": not seen,
                       "signal_types": sorted({s.signal_type for s in seen})})
        passed = sum(c["passed"] for c in checks)
        analyzers[analyzer_id] = {"checks": checks, "passed": passed, "total": len(checks), "has_target": bool(targets)}
    return {"analyzers": analyzers, "control": CONTROL}


def _signals(analyzer_id: str, case: Case) -> tuple[list, int]:
    """What a user would see from this analyzer alone on this case, and how many raw signals it raised."""
    frame = case.build().rename(columns={"metric": "metric_name"})[["timestamp", "value", "metric_name"]]
    result = harness.build_pipeline(5, "cpu.usage_user", (analyzer_id,)).run_dataframe(frame)
    return harness.user_facing_signals(result), len(result.signals)
