from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


SAMPLES = 2016
SEED = 42


def generate() -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    timestamps = pd.date_range("2026-01-01T00:00:00Z", periods=SAMPLES, freq="5min")
    index = np.arange(SAMPLES, dtype=float)
    nonlinear = 0.000009 * index**2
    daily = 8.0 * np.sin(2.0 * np.pi * index / 96.0)
    short_cycle = 3.5 * np.sin(2.0 * np.pi * index / 24.0)
    weekly_arc = 4.0 * np.sin(2.0 * np.pi * index / SAMPLES)
    values = 30.0 + nonlinear + daily + short_cycle + weekly_arc + rng.normal(0.0, 0.25, SAMPLES)
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
