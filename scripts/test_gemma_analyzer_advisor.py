#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.ai.config import AIConfig, OllamaConfig
from backend.app.ai.exceptions import AIError
from backend.app.ai.factory import build_optional_ai_services
from backend.app.metric_analyzer_recommendations.gemma_advisor import GemmaAnalyzerAdvisor
from experiments.analyzer_router.analyzer_registry import AnalyzerRegistry
from experiments.analyzer_router.router import UniversalTimeSeriesRouter
import pandas as pd


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Gemma-backed analyzer recommendations through Ollama.")
    parser.add_argument("--model", default="gemma3:4b", help="Ollama model name to use.")
    parser.add_argument("--base-url", default="http://localhost:11434", help="Ollama base URL.")
    parser.add_argument("--timeout", type=float, default=60.0, help="LLM request timeout in seconds.")
    parser.add_argument(
        "--scenario",
        choices=["trend", "baseline_shift", "seasonal", "all"],
        default="all",
        help="Synthetic time-series scenario to test.",
    )
    parser.add_argument("--csv", type=Path, help="Optional CSV file with timestamp/value columns to test instead of synthetic scenarios.")
    parser.add_argument("--timestamp-column", default="timestamp", help="Timestamp column name for --csv input.")
    parser.add_argument("--value-column", default="value", help="Value column name for --csv input.")
    parser.add_argument("--service", default="unknown-service", help="Service name for CSV metric context.")
    parser.add_argument("--metric", default="unknown_metric", help="Metric name for CSV metric context.")
    args = parser.parse_args()

    ai = build_optional_ai_services(
        AIConfig(
            enabled=True,
            provider="ollama",
            timeout_seconds=args.timeout,
            ollama=OllamaConfig(base_url=args.base_url, model=args.model, timeout_seconds=args.timeout),
        )
    )
    if ai is None:
        print("AI services were not created. Check AIConfig.", file=sys.stderr)
        return 1

    advisor = GemmaAnalyzerAdvisor(ai.structured)
    router = UniversalTimeSeriesRouter(
        registry=AnalyzerRegistry("experiments/analyzer_router/analyzer_registry.yaml"),
        config={
            "data_validation": {
                "interpolation": {
                    "enabled": True,
                    "maximum_gap_points": 5,
                    "maximum_interpolated_percentage": 20,
                }
            }
        },
    )
    if args.csv:
        points = load_csv_points(args.csv, args.timestamp_column, args.value_column)
        runs = [(args.csv.stem, points, {"service": args.service, "metric_name": args.metric, "input": str(args.csv)})]
    else:
        scenarios = ["trend", "baseline_shift", "seasonal"] if args.scenario == "all" else [args.scenario]
        runs = [
            (
                scenario,
                build_scenario(scenario),
                {
                    "metric_name": "cpu_usage",
                    "operational_purpose": "recommend the best analyzer for observed CPU behavior",
                    "scenario": scenario,
                },
            )
            for scenario in scenarios
        ]

    for label, points, metric_context in runs:
        print(f"\n=== Scenario: {label} ===")
        profile, analyzer_decisions = current_router_recommendations(router, points)
        print_current_router_decisions(analyzer_decisions)
        try:
            result = advisor.recommend(
                profile=profile,
                timeseries=points,
                analyzer_decisions=analyzer_decisions,
                metric_context=metric_context,
            )
        except AIError as exc:
            print(f"Gemma advisor failed: {exc}", file=sys.stderr)
            print("Make sure Ollama is running and the model is pulled, for example:")
            print(f"  ollama pull {args.model}")
            print("  ollama serve")
            return 1

        print("\nGemma advisory recommendation:")
        print(result.model_dump_json(indent=2))

    return 0


def build_scenario(name: str) -> list[tuple[datetime, float]]:
    start = datetime.now(UTC) - timedelta(hours=5)
    if name == "trend":
        points = [(start + timedelta(minutes=index * 5), 100 + index * 1.5) for index in range(60)]
    elif name == "baseline_shift":
        points = [(start + timedelta(minutes=index * 5), 100 if index < 30 else 160) for index in range(60)]
    elif name == "seasonal":
        points = [(start + timedelta(minutes=index * 5), 100 + 20 * math.sin(index / 4)) for index in range(80)]
    else:
        raise ValueError(f"Unknown scenario: {name}")
    return points


def load_csv_points(path: Path, timestamp_column: str, value_column: str) -> list[tuple[datetime, float]]:
    dataframe = pd.read_csv(path)
    missing = [column for column in [timestamp_column, value_column] if column not in dataframe.columns]
    if missing:
        raise ValueError(f"CSV {path} is missing required columns: {missing}")
    points: list[tuple[datetime, float]] = []
    for row in dataframe[[timestamp_column, value_column]].dropna().itertuples(index=False):
        timestamp_raw, value_raw = row
        timestamp = pd.to_datetime(timestamp_raw, utc=True).to_pydatetime()
        points.append((timestamp, float(value_raw)))
    if not points:
        raise ValueError(f"CSV {path} did not contain any valid timestamp/value rows.")
    return points


def current_router_recommendations(
    router: UniversalTimeSeriesRouter,
    points: list[tuple[datetime, float]],
):
    dataframe = pd.DataFrame(
        [{"timestamp": timestamp.isoformat(), "value": value} for timestamp, value in points]
    )
    validation, profile, _ = router.profile_dataframe(dataframe, "timestamp", "value")
    if not validation.valid:
        raise ValueError(f"Router validation failed: {validation.reasons}")
    profile.notes.extend(router._profile_notes(profile))
    decisions = router.recommend_analyzers_for_profile(profile)
    return profile, decisions


def print_current_router_decisions(decisions) -> None:
    print("Current deterministic router recommendations:")
    for decision in sorted(decisions, key=lambda item: item.final_score, reverse=True):
        matched = decision.parameters_tested.get("matched_profiles", [])
        print(
            f"  {decision.analyzer:18} {decision.recommendation:15} "
            f"score={decision.final_score:.4f} eligible={str(decision.eligible):5} matched={matched}"
        )
        print(f"    reason: {decision.routing_reason}")


if __name__ == "__main__":
    raise SystemExit(main())
