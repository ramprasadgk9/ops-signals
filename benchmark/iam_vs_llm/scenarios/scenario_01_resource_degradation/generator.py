from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from benchmark.iam_vs_llm.evaluators.taxonomy import RootCauseClass


def generate_scenario_1(
    output_dir: str | Path | None = None,
    seed: int = 42,
    noise_level: float = 1.0,
) -> dict[str, Path]:
    """Generates synthetic multi-source telemetry for Scenario 1: Resource Degradation.
    
    Story: payment-service suffers from a memory leak starting at T=30min.
    At T=75min, aggressive garbage collection causes CPU throttling.
    At T=105min, the container exceeds its 1000Mi memory limit, triggering an OOMKill.
    auth-service is included as a healthy baseline service.
    """
    rng = np.random.default_rng(seed)
    base_time = datetime(2026, 9, 7, 10, 0, 0, tzinfo=timezone.utc)
    num_points = 120  # 2 hours, 1-minute resolution
    timestamps = [base_time + timedelta(minutes=i) for i in range(num_points)]

    records: list[dict[str, Any]] = []

    # 1. Generate payment-service telemetry
    leak_start_idx = 30     # 10:30 UTC
    gc_start_idx = 75       # 11:15 UTC
    crash_idx = 105         # 11:45 UTC

    for i, ts in enumerate(timestamps):
        iso_ts = ts.isoformat()
        
        # Memory Usage (MB)
        if i < leak_start_idx:
            mem_val = 200.0 + rng.normal(0, 3.0 * noise_level)
        elif i <= crash_idx:
            # Linear rise from 200MB to 960MB
            progress = (i - leak_start_idx) / (crash_idx - leak_start_idx)
            mem_val = 200.0 + progress * 760.0 + rng.normal(0, 4.0 * noise_level)
        else:
            # Post-crash restart back to 200MB
            mem_val = 210.0 + rng.normal(0, 3.0 * noise_level)

        records.append({
            "timestamp": iso_ts,
            "service": "payment-service",
            "metric_name": "memory_usage",
            "value": round(float(mem_val), 2),
        })

        # CPU Usage (%)
        if i < gc_start_idx:
            cpu_val = 18.0 + rng.normal(0, 2.0 * noise_level)
        elif i <= crash_idx:
            # GC thrashing causes severe CPU spikes
            cpu_val = 78.0 + rng.normal(0, 5.0 * noise_level)
        else:
            cpu_val = 19.0 + rng.normal(0, 2.0 * noise_level)

        records.append({
            "timestamp": iso_ts,
            "service": "payment-service",
            "metric_name": "cpu_usage",
            "value": round(float(cpu_val), 2),
        })

        # CPU Throttling (seconds per interval)
        if i < gc_start_idx:
            throttled_val = max(0.0, 0.05 + rng.normal(0, 0.02 * noise_level))
        elif i <= crash_idx:
            throttled_val = max(0.5, 3.2 + rng.normal(0, 0.4 * noise_level))
        else:
            throttled_val = max(0.0, 0.06 + rng.normal(0, 0.02 * noise_level))

        records.append({
            "timestamp": iso_ts,
            "service": "payment-service",
            "metric_name": "cpu_throttled_seconds",
            "value": round(float(throttled_val), 3),
        })

        # 2. Generate auth-service telemetry (healthy control service)
        auth_mem = 150.0 + rng.normal(0, 2.0 * noise_level)
        auth_cpu = 12.0 + rng.normal(0, 1.5 * noise_level)
        records.append({
            "timestamp": iso_ts,
            "service": "auth-service",
            "metric_name": "memory_usage",
            "value": round(float(auth_mem), 2),
        })
        records.append({
            "timestamp": iso_ts,
            "service": "auth-service",
            "metric_name": "cpu_usage",
            "value": round(float(auth_cpu), 2),
        })

    df = pd.DataFrame(records)

    # 3. K8s Events
    k8s_events = [
        {
            "timestamp": (base_time + timedelta(minutes=crash_idx)).isoformat(),
            "service": "payment-service",
            "pod": "payment-service-7b9f898-x8z9",
            "type": "Warning",
            "reason": "OOMKilled",
            "message": "Container payment-service exceeded memory limit (1000Mi) and was terminated with exit code 137.",
            "details": {
                "exit_code": 137,
                "restart_count": 1,
                "limit": "1000Mi",
            },
        },
        {
            "timestamp": (base_time + timedelta(minutes=crash_idx + 1)).isoformat(),
            "service": "payment-service",
            "pod": "payment-service-7b9f898-x8z9",
            "type": "Warning",
            "reason": "BackOff",
            "message": "Back-off restarting failed container payment-service in pod payment-service-7b9f898-x8z9.",
            "details": {
                "status": "CrashLoopBackOff",
            },
        },
    ]

    # 4. Ground Truth
    ground_truth = {
        "scenario_id": "01_resource_degradation",
        "entity": "payment-service",
        "root_cause": RootCauseClass.MEMORY_LEAK.value,
        "secondary_symptoms": [
            "CPU_THROTTLING",
            "CONTAINER_OOM_KILLED",
        ],
        "fault_window": {
            "start": (base_time + timedelta(minutes=leak_start_idx)).isoformat(),
            "end": (base_time + timedelta(minutes=crash_idx)).isoformat(),
        },
        "key_evidence": [
            "memory_usage",
            "cpu_throttled_seconds",
            "trend",
            "baseline_shift",
        ],
    }

    # Write files if output_dir specified
    target_dir = Path(output_dir) if output_dir else Path(__file__).parent
    target_dir.mkdir(parents=True, exist_ok=True)

    metrics_csv_path = target_dir / "metrics.csv"
    k8s_json_path = target_dir / "k8s_events.json"
    ground_truth_path = target_dir / "ground_truth.yaml"

    df.to_csv(metrics_csv_path, index=False)
    k8s_json_path.write_text(json.dumps(k8s_events, indent=2), encoding="utf-8")
    ground_truth_path.write_text(yaml.safe_dump(ground_truth, sort_keys=False), encoding="utf-8")

    return {
        "metrics_csv": metrics_csv_path,
        "k8s_events": k8s_json_path,
        "ground_truth": ground_truth_path,
    }


if __name__ == "__main__":
    paths = generate_scenario_1()
    print("Generated Scenario 1 files:")
    for k, v in paths.items():
        print(f"  {k}: {v}")
