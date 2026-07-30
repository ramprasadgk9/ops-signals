from __future__ import annotations

import csv
import random
from pathlib import Path


SAMPLES_SOURCE = Path(__file__).resolve().parents[2] / "normalized" / "healthy_cpu_7d.csv"
SEED = 42


def generate_rows() -> list[dict[str, str]]:
    with SAMPLES_SOURCE.open("r", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rng = random.Random(SEED)
    event_index = len(rows) // 2
    for index, row in enumerate(rows):
        baseline = 30.0 if index < event_index else 50.0
        row["value"] = f"{min(100.0, max(0.0, baseline + rng.uniform(-1.0, 1.0))):.4f}"
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
