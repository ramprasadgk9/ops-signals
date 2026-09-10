from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from benchmark.iam_vs_llm.evaluators.taxonomy import RootCauseClass


def generate_scenario_3(
    output_dir: str | Path | None = None,
    seed: int = 42,
    noise_level: float = 1.0,
) -> dict[str, Path]:
    """Generates synthetic multi-source telemetry for Scenario 3: Benign Maintenance.

    Story: Scheduled nightly database re-indexing and batch report generation on `report-service`
    at T=30min produces transient surges in CPU (88%) and memory (840MB), but zero transactions fail
    and error rates remain 0.0%. Evaluates whether the system suppresses false-positive outage alerts.
    `frontend-service` serves as a healthy control service.
    """
    rng = np.random.default_rng(seed)
    base_time = datetime(2026, 9, 7, 14, 0, 0, tzinfo=timezone.utc)
    num_points = 120  # 2 hours, 1-minute intervals
    timestamps = [base_time + timedelta(minutes=i) for i in range(num_points)]

    records: list[dict[str, Any]] = []

    batch_start_idx = 30  # 14:30 UTC: batch begins
    batch_end_idx = 70    # 15:10 UTC: batch concludes successfully

    for i, ts in enumerate(timestamps):
        iso_ts = ts.isoformat()

        # 1. report-service: cpu_usage (%)
        if i < batch_start_idx or i > batch_end_idx:
            cpu_val = 12.0 + rng.normal(0, 1.2 * noise_level)
        else:
            cpu_val = 86.0 + rng.normal(0, 3.5 * noise_level)

        records.append({
            "timestamp": iso_ts,
            "service": "report-service",
            "metric_name": "cpu_usage",
            "value": round(float(np.clip(cpu_val, 0.0, 100.0)), 2),
        })

        # report-service: memory_usage (MB)
        if i < batch_start_idx or i > batch_end_idx:
            mem_val = 240.0 + rng.normal(0, 3.0 * noise_level)
        else:
            mem_val = 840.0 + rng.normal(0, 8.0 * noise_level)

        records.append({
            "timestamp": iso_ts,
            "service": "report-service",
            "metric_name": "memory_usage",
            "value": round(float(max(0.0, mem_val)), 2),
        })

        # report-service: batch_jobs_active
        batch_val = 1.0 if (batch_start_idx <= i <= batch_end_idx) else 0.0
        records.append({
            "timestamp": iso_ts,
            "service": "report-service",
            "metric_name": "batch_jobs_active",
            "value": float(batch_val),
        })

        # report-service: http_error_rate (flat 0.0 throughout)
        records.append({
            "timestamp": iso_ts,
            "service": "report-service",
            "metric_name": "http_error_rate",
            "value": 0.0,
        })

        # 2. frontend-service: healthy control
        front_cpu = 14.0 + rng.normal(0, 1.0 * noise_level)
        front_mem = 175.0 + rng.normal(0, 2.0 * noise_level)
        records.append({
            "timestamp": iso_ts,
            "service": "frontend-service",
            "metric_name": "cpu_usage",
            "value": round(float(front_cpu), 2),
        })
        records.append({
            "timestamp": iso_ts,
            "service": "frontend-service",
            "metric_name": "memory_usage",
            "value": round(float(front_mem), 2),
        })

    df = pd.DataFrame(records)

    # Kubernetes Events
    k8s_events = [
        {
            "timestamp": (base_time + timedelta(minutes=batch_start_idx)).isoformat(),
            "service": "report-service",
            "pod": "report-nightly-sync-job-4k2x",
            "type": "Normal",
            "reason": "JobStarted",
            "message": "CronJob report-nightly-sync triggered scheduled batch pod report-nightly-sync-job-4k2x.",
            "details": {
                "schedule": "0 2 * * *",
                "job_name": "report-nightly-sync",
            },
        },
        {
            "timestamp": (base_time + timedelta(minutes=batch_end_idx)).isoformat(),
            "service": "report-service",
            "pod": "report-nightly-sync-job-4k2x",
            "type": "Normal",
            "reason": "JobCompleted",
            "message": "CronJob report-nightly-sync completed batch indexing successfully with exit code 0.",
            "details": {
                "exit_code": 0,
                "duration_minutes": batch_end_idx - batch_start_idx,
            },
        },
    ]

    # Ground Truth
    ground_truth = {
        "scenario_id": "03_benign_maintenance",
        "entity": "report-service",
        "root_cause": RootCauseClass.BENIGN_MAINTENANCE.value,
        "secondary_symptoms": [
            "CPU_SPIKE",
            "MEMORY_STEP_INCREASE",
        ],
        "fault_window": {
            "start": (base_time + timedelta(minutes=batch_start_idx)).isoformat(),
            "end": (base_time + timedelta(minutes=batch_end_idx)).isoformat(),
        },
        "key_evidence": {
            "metrics": [
                "batch_jobs_active",
                "cpu_usage",
                "memory_usage",
            ],
            "signals": [
                "baseline_shift",
                "batch_activity",
            ],
        },
    }

    # Pre-computed Signals for Baseline B
    signals = [
        {
            "service": "report-service",
            "signal_type": "batch_activity",
            "metric_name": "batch_jobs_active",
            "severity": 0.25,
            "confidence": 0.99,
            "start_time": (base_time + timedelta(minutes=batch_start_idx)).isoformat(),
            "end_time": (base_time + timedelta(minutes=batch_end_idx)).isoformat(),
            "details": "Scheduled batch job activity confirmed active (exit code 0).",
        },
        {
            "service": "report-service",
            "signal_type": "baseline_shift",
            "metric_name": "cpu_usage",
            "severity": 0.60,
            "confidence": 0.90,
            "start_time": (base_time + timedelta(minutes=batch_start_idx)).isoformat(),
            "end_time": (base_time + timedelta(minutes=batch_end_idx)).isoformat(),
            "details": "Transient step increase in CPU usage corresponding to CronJob indexing window.",
        },
        {
            "service": "report-service",
            "signal_type": "baseline_shift",
            "metric_name": "memory_usage",
            "severity": 0.50,
            "confidence": 0.85,
            "start_time": (base_time + timedelta(minutes=batch_start_idx)).isoformat(),
            "end_time": (base_time + timedelta(minutes=batch_end_idx)).isoformat(),
            "details": "Controlled memory allocation within container limits during batch execution.",
        },
    ]

    # Mock Baseline Trajectory (Baseline A)
    mock_trajectory = {
        "turns": [
            {
                "turn": 1,
                "thought": "Discovering active services in the cluster.",
                "tool": "list_services",
                "tool_input": {},
            },
            {
                "turn": 2,
                "thought": "Checking Kubernetes events for crashes or scheduled jobs.",
                "tool": "query_k8s_events",
                "tool_input": {},
            },
            {
                "turn": 3,
                "thought": "Observing CronJob report-nightly-sync lifecycle events. Inspecting report-service CPU trend.",
                "tool": "query_prometheus",
                "tool_input": {"query": 'cpu_usage{service="report-service"}'},
            },
            {
                "turn": 4,
                "thought": "Verifying active batch jobs to correlate high resource utilization with scheduled maintenance.",
                "tool": "query_prometheus",
                "tool_input": {"query": 'batch_jobs_active{service="report-service"}'},
            },
            {
                "turn": 5,
                "thought": "Checking error rates on report-service to confirm whether transaction failures occurred.",
                "tool": "query_prometheus",
                "tool_input": {"query": 'http_error_rate{service="report-service"}'},
            },
        ],
        "final_text": (
            "Investigation Complete:\n\n"
            "Telemetry and event analysis confirms that elevated CPU and memory metrics on report-service "
            f"between {(base_time + timedelta(minutes=batch_start_idx)).isoformat()} and {(base_time + timedelta(minutes=batch_end_idx)).isoformat()} "
            "were entirely attributable to the scheduled CronJob report-nightly-sync. Error rates remained at 0.00% and the job completed with exit code 0. "
            "No production outage or incident occurred; resource spikes represent planned, benign maintenance.\n\n"
            "ROOT_CAUSE: BENIGN_MAINTENANCE\n"
            "ENTITY: report-service\n"
            f"WINDOW: {(base_time + timedelta(minutes=batch_start_idx)).isoformat()} to {(base_time + timedelta(minutes=batch_end_idx)).isoformat()}\n"
            "EVIDENCE: batch_jobs_active, cpu_usage, memory_usage\n"
        ),
    }

    # Mock Baseline B Trajectory (Signals-Augmented Agent)
    mock_baseline_b_trajectory = {
        "turns": [
            {
                "turn": 1,
                "thought": "Querying pre-computed signals across all cluster services.",
                "tool": "list_signals",
                "tool_input": {},
            },
            {
                "turn": 2,
                "thought": "Detected batch_activity signal with low severity and 0 error signals on report-service. Querying batch jobs metric.",
                "tool": "query_prometheus",
                "tool_input": {"query": 'batch_jobs_active{service="report-service"}'},
            },
            {
                "turn": 3,
                "thought": "Correlating batch schedule with zero error rates.",
                "tool": "query_prometheus",
                "tool_input": {"query": 'http_error_rate{service="report-service"}'},
            },
        ],
        "final_text": (
            "Investigation Complete:\n\n"
            "Signal extraction confirms scheduled batch_activity on report-service with 0 errors. "
            f"The transient resource surge from {(base_time + timedelta(minutes=batch_start_idx)).isoformat()} to "
            f"{(base_time + timedelta(minutes=batch_end_idx)).isoformat()} is confirmed as benign scheduled maintenance.\n\n"
            "ROOT_CAUSE: BENIGN_MAINTENANCE\n"
            "ENTITY: report-service\n"
            f"WINDOW: {(base_time + timedelta(minutes=batch_start_idx)).isoformat()} to {(base_time + timedelta(minutes=batch_end_idx)).isoformat()}\n"
            "EVIDENCE: batch_jobs_active, cpu_usage, memory_usage\n"
        ),
    }

    target_dir = Path(output_dir) if output_dir else Path(__file__).parent
    target_dir.mkdir(parents=True, exist_ok=True)

    metrics_csv_path = target_dir / "metrics.csv"
    k8s_json_path = target_dir / "k8s_events.json"
    ground_truth_path = target_dir / "ground_truth.yaml"
    mock_traj_path = target_dir / "mock_baseline_trajectory.yaml"
    mock_b_traj_path = target_dir / "mock_baseline_b_trajectory.yaml"
    signals_json_path = target_dir / "signals.json"

    df.to_csv(metrics_csv_path, index=False)
    k8s_json_path.write_text(json.dumps(k8s_events, indent=2), encoding="utf-8")
    ground_truth_path.write_text(yaml.safe_dump(ground_truth, sort_keys=False), encoding="utf-8")
    mock_traj_path.write_text(yaml.safe_dump(mock_trajectory, sort_keys=False), encoding="utf-8")
    mock_b_traj_path.write_text(yaml.safe_dump(mock_baseline_b_trajectory, sort_keys=False), encoding="utf-8")
    signals_json_path.write_text(json.dumps(signals, indent=2), encoding="utf-8")

    return {
        "metrics_csv": metrics_csv_path,
        "k8s_events": k8s_json_path,
        "ground_truth": ground_truth_path,
        "mock_trajectory": mock_traj_path,
        "mock_baseline_b_trajectory": mock_b_traj_path,
        "signals": signals_json_path,
    }


if __name__ == "__main__":
    paths = generate_scenario_3()
    print("Generated Scenario 3 files:")
    for k, v in paths.items():
        print(f"  {k}: {v}")
