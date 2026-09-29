from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

SEED = 43
SAMPLE_COUNT = 600
INTERVAL_MINUTES = 5
START = datetime(2016, 1, 1, 0, 0, 0)
ANOMALY_START = 380
ANOMALY_LENGTH = 12
MEMORY_STEP_AT = 300


def generate_rows() -> list[dict[str, str]]:
    """The same short CPU anomaly burst as behavior_server_slow_v1, but memory_usage jumps to a
    new level half way through and stays there instead of climbing steadily. 'server_slow' accepts
    either an upward memory trend or a memory baseline shift, so this exercises the baseline-shift
    side of the rule - the side only the baseline_shift analyzer can report."""
    rng = random.Random(SEED)
    rows: list[dict[str, str]] = []
    for index in range(SAMPLE_COUNT):
        timestamp = (START + timedelta(minutes=index * INTERVAL_MINUTES)).strftime("%Y-%m-%dT%H:%M:%SZ")

        cpu = 35.0 + rng.uniform(-1.5, 1.5)
        if ANOMALY_START <= index < ANOMALY_START + ANOMALY_LENGTH:
            cpu = 92.0 + rng.uniform(-2.0, 2.0)
        rows.append({"timestamp": timestamp, "value": f"{max(0.0, min(100.0, cpu)):.4f}", "metric": "cpu_usage", "hostname": "host_0"})

        memory = (30.0 if index < MEMORY_STEP_AT else 55.0) + rng.uniform(-1.0, 1.0)
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
