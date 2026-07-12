from __future__ import annotations

from pathlib import Path

import pandas as pd


def build_learning_dataframe() -> pd.DataFrame:
    timestamps = pd.date_range("2026-07-02T00:00:00Z", periods=288, freq="5min")
    values: list[float] = []

    wobble = [0.0, 1.5, -1.2, 2.1, -0.8, 0.6]
    for i in range(288):
        if i < 96:
            value = 42 + wobble[i % len(wobble)]
        elif i < 192:
            value = 68 + wobble[i % len(wobble)]
        else:
            value = 70 + ((i - 192) * 0.35) + wobble[i % len(wobble)]
        values.append(value)

    # Inject explicit outliers so anomaly_zscore emits at least one signal.
    values[130] = 160.0
    values[220] = 12.0
    values[260] = 175.0

    return pd.DataFrame(
        {
            "timestamp": timestamps.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "metric_name": "cpu_usage",
            "value": values,
            "service": "checkout",
            "env": "prod",
            "host": "host-learning-1",
            "namespace": "checkout",
            "pod": "checkout-learning-0",
            "source": "learning_generator",
            "unit": "percent",
            "metric_type": "gauge",
        }
    )


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output_path = root / "sample_data" / "cpu_usage_learning_day.csv"
    dataframe = build_learning_dataframe()
    dataframe.to_csv(output_path, index=False)
    print(f"Wrote {len(dataframe)} rows to {output_path}")


if __name__ == "__main__":
    main()
