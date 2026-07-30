from __future__ import annotations

import csv
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[2] / "normalized" / "healthy_cpu_7d.csv"


def main() -> None:
    with SOURCE.open("r", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    event_index = len(rows) // 2
    for index, row in enumerate(rows):
        if index >= event_index:
            row["value"] = str(min(100.0, max(0.0, float(row["value"]) + 15.0)))
    with Path(__file__).with_name("dataset.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "value", "metric", "hostname"])
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
