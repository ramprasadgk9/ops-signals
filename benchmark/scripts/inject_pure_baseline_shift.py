#!/usr/bin/env python3

import argparse
import csv
import random
from pathlib import Path


def inject_pure_baseline_shift(
    source: Path,
    output: Path,
    baseline_before: float,
    baseline_after: float,
    noise: float,
    event_fraction: float,
    seed: int,
) -> None:
    with source.open("r", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    if not rows:
        raise ValueError("Source dataset is empty")

    required_columns = {"timestamp", "value", "metric", "hostname"}
    missing_columns = required_columns.difference(rows[0].keys())

    if missing_columns:
        raise ValueError(
            f"Source dataset is missing columns: {sorted(missing_columns)}"
        )

    event_index = int(len(rows) * event_fraction)

    if event_index <= 0 or event_index >= len(rows):
        raise ValueError("Event position must be inside the dataset")

    random_generator = random.Random(seed)

    generated_values = []

    for index, row in enumerate(rows):
        baseline = (
            baseline_before
            if index < event_index
            else baseline_after
        )

        generated_value = baseline + random_generator.uniform(-noise, noise)
        generated_value = min(100.0, max(0.0, generated_value))

        row["value"] = f"{generated_value:.4f}"
        generated_values.append(generated_value)

    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["timestamp", "value", "metric", "hostname"],
        )
        writer.writeheader()
        writer.writerows(rows)

    before_values = generated_values[:event_index]
    after_values = generated_values[event_index:]

    before_mean = sum(before_values) / len(before_values)
    after_mean = sum(after_values) / len(after_values)

    print(f"Source: {source}")
    print(f"Output: {output}")
    print(f"Samples: {len(rows)}")
    print(f"Event index: {event_index}")
    print(f"Event timestamp: {rows[event_index]['timestamp']}")
    print(f"Baseline before: {baseline_before}")
    print(f"Baseline after: {baseline_after}")
    print(f"Noise amplitude: +/-{noise}")
    print(f"Before mean: {before_mean:.2f}")
    print(f"After mean: {after_mean:.2f}")
    print(f"Observed difference: {after_mean - before_mean:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a deterministic, low-seasonality baseline-shift "
            "scenario for router benchmarking."
        )
    )

    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--baseline-before", type=float, default=30.0)
    parser.add_argument("--baseline-after", type=float, default=50.0)
    parser.add_argument("--noise", type=float, default=1.0)
    parser.add_argument("--event-fraction", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=42)

    args = parser.parse_args()

    inject_pure_baseline_shift(
        source=Path(args.input),
        output=Path(args.output),
        baseline_before=args.baseline_before,
        baseline_after=args.baseline_after,
        noise=args.noise,
        event_fraction=args.event_fraction,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()