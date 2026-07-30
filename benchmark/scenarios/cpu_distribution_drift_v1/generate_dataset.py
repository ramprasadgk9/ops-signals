from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


SAMPLES = 2016
SEED = 42


def generate() -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    timestamps = pd.date_range("2026-01-01T00:00:00Z", periods=SAMPLES, freq="5min")
    index = np.linspace(0.0, 1.0, SAMPLES)
    mean = 38.0 + 5.0 * index
    stddev = 0.3 + 4.0 * index
    values = mean + rng.normal(0.0, stddev, SAMPLES)
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
