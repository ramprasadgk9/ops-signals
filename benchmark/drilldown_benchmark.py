"""Finding drill-down benchmark: does the breakdown name the right pods and the right spread?

Synthetic per-pod series with known ground truth, varied over the things that make the job harder:
pod count, noise, size of the change, and pods with different normal levels. Four situations:

  one_pod   - one pod changes            -> spread "concentrated", that pod ranked first
  two_pods  - two pods change            -> spread "partial", those two ranked first
  all_pods  - every pod changes (jitter) -> spread "widespread"
  new_pods  - a rollout adds two new pods that behave differently, old pods stay -> "partial",
              the two new pods ranked first and flagged new

each in both modes: "share" (an error rate, additive) and "changed_parts" (a latency, not additive).

    python -m benchmark.drilldown_benchmark            # small sample, seconds
    python -m benchmark.drilldown_benchmark --seeds 50 # fuller run

Writes benchmark/reports/drilldown/<timestamp>.json (gitignored) and prints a summary.
"""

from __future__ import annotations

import argparse
import itertools
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from intelligence.drilldown import BreakdownWindow, compute_breakdown

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "benchmark" / "reports" / "drilldown"

START = datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc)
CHANGE = START + timedelta(minutes=60)
END = START + timedelta(minutes=120)
WINDOW = BreakdownWindow(before_start=START, change_start=CHANGE, change_end=END)
TIMESTAMPS = pd.date_range(START, END, freq="1min")

KINDS = ["one_pod", "two_pods", "all_pods", "new_pods"]
MODES = ["share", "changed_parts"]
POD_COUNTS = [3, 6, 12]
NOISE_LEVELS = [0.02, 0.10, 0.25]
# How much the affected pods change: after = before * factor.
MAGNITUDES = {"small": 1.5, "medium": 3.0, "large": 10.0}
EXPECTED_SPREAD = {"one_pod": "concentrated", "two_pods": "partial", "all_pods": "widespread", "new_pods": "partial"}


@dataclass(slots=True)
class CaseResult:
    kind: str
    mode: str
    pods: int
    noise: float
    magnitude: str
    seed: int
    expected_spread: str
    actual_spread: str | None
    culprits: list[str]
    ranked_first: list[str]
    culprits_first: bool
    spread_correct: bool
    new_flagged: bool | None
    status: str


def _case(kind: str, mode: str, pods: int, noise: float, factor: float, seed: int) -> tuple[pd.DataFrame, list[str]]:
    rng = np.random.default_rng(seed)
    base = 0.2 if mode == "share" else 0.12
    names = [f"pod-{index:02d}" for index in range(pods)]
    levels = {name: base * rng.uniform(0.5, 1.5) for name in names}
    before_after: dict[str, tuple[float | None, float | None]] = {name: (level, level) for name, level in levels.items()}

    if kind == "one_pod":
        culprits = [str(rng.choice(names))]
    elif kind == "two_pods":
        culprits = [str(name) for name in rng.choice(names, size=2, replace=False)]
    elif kind == "all_pods":
        culprits = list(names)
    else:
        culprits = ["new-a", "new-b"]
        for name in culprits:
            before_after[name] = (None, base * factor * rng.uniform(0.8, 1.2))

    if kind != "new_pods":
        for name in culprits:
            jitter = rng.uniform(0.8, 1.2) if kind == "all_pods" else 1.0
            before_after[name] = (levels[name], levels[name] * factor * jitter)

    rows = []
    for name, (before, after) in before_after.items():
        for timestamp in TIMESTAMPS:
            level = before if timestamp < CHANGE else after
            if level is None:
                continue
            rows.append({"part": name, "timestamp": timestamp, "value": max(0.0, level + rng.normal(0, level * noise))})
    return pd.DataFrame(rows), culprits


def run(seeds: int) -> list[CaseResult]:
    results = []
    for kind, mode, pods, noise, (magnitude, factor), seed in itertools.product(
        KINDS, MODES, POD_COUNTS, NOISE_LEVELS, MAGNITUDES.items(), range(seeds)
    ):
        # Two of three pods changing is most of the service, not a "partial" subset.
        if kind == "two_pods" and pods < 6:
            continue
        parts, culprits = _case(kind, mode, pods, noise, factor, seed)
        breakdown = compute_breakdown(parts, label="pod", window=WINDOW, mode=mode)
        top = [part["value"] for part in breakdown.get("top", [])]
        first = top[: len(culprits)] if kind != "all_pods" else []
        culprits_first = kind == "all_pods" or set(first) == set(culprits)
        new_flagged = None
        if kind == "new_pods":
            new_flagged = all(part["new"] for part in breakdown.get("top", [])[:2])
        results.append(
            CaseResult(
                kind=kind,
                mode=mode,
                pods=pods,
                noise=noise,
                magnitude=magnitude,
                seed=seed,
                expected_spread=EXPECTED_SPREAD[kind],
                actual_spread=breakdown.get("spread"),
                culprits=culprits if kind != "all_pods" else [],
                ranked_first=first,
                culprits_first=culprits_first,
                spread_correct=breakdown.get("spread") == EXPECTED_SPREAD[kind],
                new_flagged=new_flagged,
                status=str(breakdown["status"]),
            )
        )
    return results


def summarize(results: list[CaseResult]) -> dict[str, object]:
    def rates(items: list[CaseResult]) -> dict[str, float | int]:
        return {
            "cases": len(items),
            "culprits_ranked_first": round(sum(item.culprits_first for item in items) / len(items), 4),
            "spread_correct": round(sum(item.spread_correct for item in items) / len(items), 4),
        }

    groups: dict[str, dict[str, list[CaseResult]]] = {
        "kind": defaultdict(list), "mode": defaultdict(list), "noise": defaultdict(list),
        "magnitude": defaultdict(list), "pods": defaultdict(list),
    }
    for item in results:
        groups["kind"][item.kind].append(item)
        groups["mode"][item.mode].append(item)
        groups["noise"][str(item.noise)].append(item)
        groups["magnitude"][item.magnitude].append(item)
        groups["pods"][str(item.pods)].append(item)
    return {
        "overall": rates(results),
        **{f"by_{name}": {key: rates(items) for key, items in grouped.items()} for name, grouped in groups.items()},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark the finding drill-down breakdown on synthetic per-pod data")
    parser.add_argument("--seeds", type=int, default=5, help="random cases per combination (default 5: a few seconds)")
    parser.add_argument("--reports-dir", type=Path, default=REPORTS_DIR)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    results = run(args.seeds)
    summary = summarize(results)
    args.reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = args.reports_dir / f"{stamp}.json"
    path.write_text(json.dumps({"summary": summary, "cases": [asdict(item) for item in results]}, indent=2))

    overall = summary["overall"]
    print(f"Drill-down benchmark: {overall['cases']} cases")
    print(f"  culprits ranked first: {overall['culprits_ranked_first']:.1%}")
    print(f"  spread correct:        {overall['spread_correct']:.1%}")
    for group in ["by_kind", "by_mode", "by_noise", "by_magnitude", "by_pods"]:
        print(f"\n{group.removeprefix('by_')}:")
        for key, rate in summary[group].items():
            print(f"  {key:<14} culprits first {rate['culprits_ranked_first']:>6.1%}   spread {rate['spread_correct']:>6.1%}   ({rate['cases']} cases)")
    print(f"\nWrote {path.relative_to(PROJECT_ROOT) if path.is_relative_to(PROJECT_ROOT) else path}")


if __name__ == "__main__":
    main()
