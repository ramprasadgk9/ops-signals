from __future__ import annotations

import csv
import random
from pathlib import Path


SAMPLES_SOURCE = Path(__file__).resolve().parents[2] / "normalized" / "healthy_cpu_7d.csv"
SEED = 42
BASELINE = 40.0
NOISE = 1.0


def generate_rows() -> list[dict[str, str]]:
    """Stable CPU series with no injected shift, trend, seasonality, or spike - a negative
    control for validating the system stays quiet on unremarkable data instead of manufacturing
    false-positive recommendations, signals, or findings."""
    with SAMPLES_SOURCE.open("r", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rng = random.Random(SEED)
    for row in rows:
        row["value"] = f"{min(100.0, max(0.0, BASELINE + rng.uniform(-NOISE, NOISE))):.4f}"
    return rows


def main() -> None:
    output = Path(__file__).with_name("dataset.csv")
    rows = generate_rows()
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "value", "metric", "hostname"])
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
