from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

SEED = 7
SAMPLE_COUNT = 600
INTERVAL_MINUTES = 5
START = datetime(2016, 1, 1, 0, 0, 0)
ANOMALY_START = 380
ANOMALY_LENGTH = 12


def generate_rows() -> list[dict[str, str]]:
    """Two correlated metrics in the same overlapping window - request_latency_p95 and
    error_rate both spike together - shaped to match the 'latency_error_cascade' behavior
    definition in config/behavior_definitions.d/latency_and_errors.yml, which requires an
    anomaly on both metrics in the same analysis window."""
    rng = random.Random(SEED)
    rows: list[dict[str, str]] = []
    for index in range(SAMPLE_COUNT):
        timestamp = (START + timedelta(minutes=index * INTERVAL_MINUTES)).strftime("%Y-%m-%dT%H:%M:%SZ")

        latency = 120.0 + rng.uniform(-5.0, 5.0)
        if ANOMALY_START <= index < ANOMALY_START + ANOMALY_LENGTH:
            latency = 420.0 + rng.uniform(-10.0, 10.0)
        rows.append({"timestamp": timestamp, "value": f"{max(0.0, latency):.4f}", "metric": "request_latency_p95", "hostname": "host_0"})

        error_rate = 0.5 + rng.uniform(-0.1, 0.1)
        if ANOMALY_START <= index < ANOMALY_START + ANOMALY_LENGTH:
            error_rate = 14.0 + rng.uniform(-1.0, 1.0)
        rows.append({"timestamp": timestamp, "value": f"{max(0.0, error_rate):.4f}", "metric": "error_rate", "hostname": "host_0"})
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
