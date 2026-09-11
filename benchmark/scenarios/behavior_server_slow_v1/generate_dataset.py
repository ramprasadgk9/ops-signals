from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

SEED = 42
SAMPLE_COUNT = 600
INTERVAL_MINUTES = 5
START = datetime(2016, 1, 1, 0, 0, 0)
ANOMALY_START = 380
ANOMALY_LENGTH = 12


def generate_rows() -> list[dict[str, str]]:
    """Two correlated metrics in one CSV: cpu_usage gets a short isolated anomaly burst, and
    memory_usage climbs steadily upward across the whole window - together shaped to match the
    'server_slow' behavior definition in config/behavior_definitions.d/core.yml, which requires a
    CPU anomaly plus an upward memory trend (or memory baseline shift) in the same window."""
    rng = random.Random(SEED)
    rows: list[dict[str, str]] = []
    for index in range(SAMPLE_COUNT):
        timestamp = (START + timedelta(minutes=index * INTERVAL_MINUTES)).strftime("%Y-%m-%dT%H:%M:%SZ")

        cpu = 35.0 + rng.uniform(-1.5, 1.5)
        if ANOMALY_START <= index < ANOMALY_START + ANOMALY_LENGTH:
            cpu = 92.0 + rng.uniform(-2.0, 2.0)
        rows.append({"timestamp": timestamp, "value": f"{max(0.0, min(100.0, cpu)):.4f}", "metric": "cpu_usage", "hostname": "host_0"})

        memory = 30.0 + (40.0 * index / SAMPLE_COUNT) + rng.uniform(-1.0, 1.0)
        rows.append({"timestamp": timestamp, "value": f"{max(0.0, min(100.0, memory)):.4f}", "metric": "memory_usage", "hostname": "host_0"})
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
