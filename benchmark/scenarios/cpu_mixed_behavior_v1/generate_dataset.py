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
    trend = np.linspace(0.0, 25.0, SAMPLES)
    cycle = index % 96
    seasonal = np.piecewise(
        cycle,
        [cycle < 28, (cycle >= 28) & (cycle < 44), (cycle >= 44) & (cycle < 72), cycle >= 72],
        [
            lambda x: 20.0 + (16.0 * x / 27.0),
            37.0,
            lambda x: 37.0 - (15.0 * (x - 44.0) / 27.0),
            22.0,
        ],
    ) - 28.0
    baseline_shift = np.where(index >= SAMPLES // 2, 16.0, 0.0)
    values = 35.0 + trend + seasonal + baseline_shift + rng.normal(0.0, 0.22, SAMPLES)
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
