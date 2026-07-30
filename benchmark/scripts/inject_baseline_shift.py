#!/usr/bin/env python3

import argparse
import csv
from pathlib import Path


def inject_shift(
    source: Path,
    output: Path,
    shift: float,
    event_fraction: float,
) -> None:
    with source.open("r", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    if not rows:
        raise ValueError("Source dataset is empty")

    event_index = int(len(rows) * event_fraction)

    if event_index <= 0 or event_index >= len(rows):
        raise ValueError("Event position must be inside the dataset")

    original_values = [float(row["value"]) for row in rows]

    for index, row in enumerate(rows):
        original_value = float(row["value"])

        if index >= event_index:
            shifted_value = min(100.0, max(0.0, original_value + shift))
            row["value"] = str(shifted_value)

    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["timestamp", "value", "metric", "hostname"],
        )
        writer.writeheader()
        writer.writerows(rows)

    before_values = original_values[:event_index]
    after_values = [float(row["value"]) for row in rows[event_index:]]

    before_mean = sum(before_values) / len(before_values)
    after_mean = sum(after_values) / len(after_values)

    print(f"Source: {source}")
    print(f"Output: {output}")
    print(f"Samples: {len(rows)}")
    print(f"Event index: {event_index}")
    print(f"Event timestamp: {rows[event_index]['timestamp']}")
    print(f"Configured shift: {shift}")
    print(f"Before mean: {before_mean:.2f}")
    print(f"After mean: {after_mean:.2f}")
    print(f"Observed difference: {after_mean - before_mean:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inject a deterministic CPU baseline shift."
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--shift", type=float, default=15.0)
    parser.add_argument("--event-fraction", type=float, default=0.5)

    args = parser.parse_args()

    inject_shift(
        source=Path(args.input),
        output=Path(args.output),
        shift=args.shift,
        event_fraction=args.event_fraction,
    )


if __name__ == "__main__":
    main()
