from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


SAMPLES = 2016
SEED = 42


def generate() -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    timestamps = pd.date_range("2026-01-01T00:00:00Z", periods=SAMPLES, freq="5min")
    index = np.arange(SAMPLES)
    local_baseline = 34.0 + 2.0 * np.sin(2.0 * np.pi * index / 360.0)
    values = local_baseline + rng.normal(0.0, 0.28, SAMPLES)
    for spike_index in range(220, SAMPLES, 170):
        values[spike_index] += 10.0
    for spike_index in range(1250, SAMPLES, 70):
        values[spike_index] += 13.0
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
