from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


SAMPLES = 2016
SEED = 42


def generate() -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    timestamps = pd.date_range("2026-01-01T00:00:00Z", periods=SAMPLES, freq="5min")
    cycle = np.arange(SAMPLES) % 96
    shape = np.piecewise(
        cycle,
        [cycle < 28, (cycle >= 28) & (cycle < 44), (cycle >= 44) & (cycle < 72), cycle >= 72],
        [
            lambda x: 22.0 + (18.0 * x / 27.0),
            41.0,
            lambda x: 41.0 - (17.0 * (x - 44.0) / 27.0),
            24.0,
        ],
    )
    values = shape + rng.normal(0.0, 0.18, SAMPLES)
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
