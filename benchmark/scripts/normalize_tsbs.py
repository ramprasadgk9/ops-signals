#!/usr/bin/env python3

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path


def parse_tags(line: str) -> dict[str, str]:
    parts = line.strip().split(",")
    metadata: dict[str, str] = {}

    for item in parts[1:]:
        if "=" in item:
            key, value = item.split("=", 1)
            metadata[key] = value

    return metadata


def ns_to_iso(timestamp_ns: int) -> str:
    seconds = timestamp_ns / 1_000_000_000
    dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def normalize(source: Path, output: Path) -> None:
    rows: list[dict[str, str]] = []
    current_tags: dict[str, str] = {}
    metric_name: str | None = None

    with source.open("r", encoding="utf-8") as file:
        for line_number, raw_line in enumerate(file, start=1):
            line = raw_line.strip()

            if not line:
                continue

            if line.startswith("tags,") and "=" not in line:
                continue

            if line == "cpu,usage_user":
                metric_name = "cpu.usage_user"
                continue

            if line.startswith("tags,hostname="):
                current_tags = parse_tags(line)
                continue

            if line.startswith("cpu,"):
                parts = line.split(",")

                if len(parts) != 3:
                    raise ValueError(
                        f"Invalid CPU row at line {line_number}: {line}"
                    )

                if not current_tags:
                    raise ValueError(
                        f"CPU row at line {line_number} has no preceding tags row"
                    )
                if metric_name is None:
                    raise ValueError(
                        f"CPU row at line {line_number} has no preceding metric header"
                    )

                timestamp_ns = int(parts[1])
                value = float(parts[2])

                rows.append(
                    {
                        "timestamp": ns_to_iso(timestamp_ns),
                        "value": str(value),
                        "metric": metric_name,
                        "hostname": current_tags.get("hostname", ""),
                    }
                )

    if not rows:
        raise ValueError(f"No CPU rows found in {source}")

    rows.sort(key=lambda row: row["timestamp"])

    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["timestamp", "value", "metric", "hostname"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Source: {source}")
    print(f"Output: {output}")
    print(f"Samples: {len(rows)}")
    print(f"Start: {rows[0]['timestamp']}")
    print(f"End: {rows[-1]['timestamp']}")
    print(f"Hostname: {rows[0]['hostname']}")
    print(f"Metric: {rows[0]['metric']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize TSBS CPU data into a simple CSV format."
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)

    args = parser.parse_args()

    normalize(Path(args.input), Path(args.output))


if __name__ == "__main__":
    main()
