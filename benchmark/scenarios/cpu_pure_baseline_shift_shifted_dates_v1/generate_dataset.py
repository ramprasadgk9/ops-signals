from __future__ import annotations

from pathlib import Path

import pandas as pd


SOURCE = Path(__file__).resolve().parents[1] / "cpu_pure_baseline_shift_v1" / "dataset.csv"


def main() -> None:
    dataframe = pd.read_csv(SOURCE)
    timestamps = pd.date_range("2026-01-01T00:00:00Z", periods=len(dataframe), freq="5min")
    dataframe["timestamp"] = timestamps.strftime("%Y-%m-%dT%H:%M:%SZ")
    dataframe.to_csv(Path(__file__).with_name("dataset.csv"), index=False)


if __name__ == "__main__":
    main()
