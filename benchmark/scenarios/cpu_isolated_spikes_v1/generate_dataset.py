from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


SAMPLES = 2016
SEED = 42
SPIKE_INDEXES = [180, 412, 777, 1040, 1399, 1742]


def generate() -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    timestamps = pd.date_range("2026-01-01T00:00:00Z", periods=SAMPLES, freq="5min")
    values = np.full(SAMPLES, 38.0) + rng.normal(0.0, 0.18, SAMPLES)
    for offset, index in enumerate(SPIKE_INDEXES):
        direction = 1.0 if offset % 2 == 0 else -1.0
        values[index] += direction * 18.0
    return pd.DataFrame(
        {
            "timestamp": timestamps.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "value": np.round(values, 4),
            "metric": "cpu.usage_user",
            "hostname": "host_0",
        }
    )


if __name__ == "__main__":
    generate().to_csv(Path(__file__).with_name("dataset.csv"), index=False)
