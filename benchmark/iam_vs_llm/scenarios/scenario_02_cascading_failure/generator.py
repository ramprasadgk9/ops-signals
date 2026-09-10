from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from benchmark.iam_vs_llm.evaluators.taxonomy import RootCauseClass


def generate_scenario_2(
    output_dir: str | Path | None = None,
    seed: int = 42,
    noise_level: float = 1.0,
) -> dict[str, Path]:
    """Generates synthetic multi-source telemetry for Scenario 2: Cascading Failure.

    Story: Database connection pool exhaustion on upstream `orders-service` at T=25min causes
    request queueing, thread pool exhaustion in `auth-service`, and cascading HTTP 504 Gateway
    Timeouts in `api-gateway`. HPA scales up `api-gateway` uselessly because the bottleneck is upstream.
    `inventory-service` serves as a healthy control service.
    """
    rng = np.random.default_rng(seed)
    base_time = datetime(2026, 9, 7, 14, 0, 0, tzinfo=timezone.utc)
    num_points = 120  # 2 hours, 1-minute intervals
    timestamps = [base_time + timedelta(minutes=i) for i in range(num_points)]

    records: list[dict[str, Any]] = []

    pool_start_idx = 25   # 14:25 UTC: pool starts filling
    exhaust_idx = 45      # 14:45 UTC: pool hits ceiling (100)
    auth_impact_idx = 48  # 14:48 UTC: auth threads exhaust
    gateway_504_idx = 50  # 14:50 UTC: gateway throws 504s
    recover_idx = 85      # 15:25 UTC: pool drained/restarted

    for i, ts in enumerate(timestamps):
        iso_ts = ts.isoformat()

        # 1. orders-service: db_connections_active (max limit 100)
        if i < pool_start_idx:
            active_conns = 18.0 + rng.normal(0, 1.5 * noise_level)
        elif i < exhaust_idx:
            prog = (i - pool_start_idx) / (exhaust_idx - pool_start_idx)
            active_conns = 18.0 + prog * 82.0 + rng.normal(0, 1.0 * noise_level)
        elif i <= recover_idx:
            active_conns = 100.0 + rng.normal(0, 0.2 * noise_level)  # Saturated at pool max
        else:
            active_conns = 20.0 + rng.normal(0, 1.5 * noise_level)

        records.append({
            "timestamp": iso_ts,
            "service": "orders-service",
            "metric_name": "db_connections_active",
            "value": round(float(np.clip(active_conns, 0.0, 100.0)), 2),
        })

        # orders-service: db_connection_wait_seconds
        if i < exhaust_idx:
            wait_sec = 0.005 + max(0.0, rng.normal(0, 0.002 * noise_level))
        elif i <= recover_idx:
            wait_sec = 14.8 + rng.normal(0, 1.2 * noise_level)
        else:
            wait_sec = 0.006 + max(0.0, rng.normal(0, 0.002 * noise_level))

        records.append({
            "timestamp": iso_ts,
            "service": "orders-service",
            "metric_name": "db_connection_wait_seconds",
            "value": round(float(max(0.0, wait_sec)), 3),
        })

        # 2. auth-service: thread_pool_active_percent
        if i < auth_impact_idx:
            auth_threads = 24.0 + rng.normal(0, 2.0 * noise_level)
        elif i <= recover_idx:
            auth_threads = 96.0 + rng.normal(0, 1.5 * noise_level)
        else:
            auth_threads = 26.0 + rng.normal(0, 2.0 * noise_level)

        records.append({
            "timestamp": iso_ts,
            "service": "auth-service",
            "metric_name": "thread_pool_active_percent",
            "value": round(float(np.clip(auth_threads, 0.0, 100.0)), 2),
        })

        # 3. api-gateway: http_504_rate (req/sec)
        if i < gateway_504_idx:
            http_504 = 0.0
        elif i <= recover_idx:
            http_504 = 48.0 + rng.normal(0, 3.5 * noise_level)
        else:
            http_504 = 0.0

        records.append({
            "timestamp": iso_ts,
            "service": "api-gateway",
            "metric_name": "http_504_rate",
            "value": round(float(max(0.0, http_504)), 2),
        })

        # 4. inventory-service: healthy control
        inv_cpu = 15.0 + rng.normal(0, 1.2 * noise_level)
        inv_mem = 180.0 + rng.normal(0, 2.0 * noise_level)
        records.append({
            "timestamp": iso_ts,
            "service": "inventory-service",
            "metric_name": "cpu_usage",
            "value": round(float(inv_cpu), 2),
        })
        records.append({
            "timestamp": iso_ts,
            "service": "inventory-service",
            "metric_name": "memory_usage",
            "value": round(float(inv_mem), 2),
        })

    df = pd.DataFrame(records)

    # Kubernetes Events
    k8s_events = [
        {
            "timestamp": (base_time + timedelta(minutes=exhaust_idx)).isoformat(),
            "service": "orders-service",
            "pod": "orders-service-9c7f12-v4b2",
            "type": "Warning",
            "reason": "PoolExhausted",
            "message": "HikariPool-1 - Connection is not available, request timed out after 30000ms.",
            "details": {
                "active_connections": 100,
                "max_connections": 100,
                "waiting_threads": 42,
            },
        },
        {
            "timestamp": (base_time + timedelta(minutes=gateway_504_idx + 2)).isoformat(),
            "service": "api-gateway",
            "pod": "api-gateway-3x9a10-m5k1",
            "type": "Normal",
            "reason": "SuccessfulRescale",
            "message": "HorizontalPodAutoscaler scaled up replica set api-gateway from 3 to 8 pods due to request queue length.",
            "details": {
                "previous_replicas": 3,
                "current_replicas": 8,
                "target_metric": "http_requests_in_flight",
            },
        },
    ]

    # Ground Truth
    ground_truth = {
        "scenario_id": "02_cascading_failure",
        "entity": "orders-service",
        "root_cause": RootCauseClass.POOL_EXHAUSTION.value,
        "secondary_symptoms": [
            "GATEWAY_TIMEOUT_504",
            "HPA_SCALE_UP",
            "THREAD_POOL_SATURATION",
        ],
        "fault_window": {
            "start": (base_time + timedelta(minutes=pool_start_idx)).isoformat(),
            "end": (base_time + timedelta(minutes=recover_idx)).isoformat(),
        },
        "key_evidence": {
            "metrics": [
                "db_connections_active",
                "db_connection_wait_seconds",
                "http_504_rate",
            ],
            "signals": [
                "saturation",
                "baseline_shift",
                "anomaly_zscore",
            ],
        },
    }

    # Pre-computed Signals for Baseline B
    signals = [
        {
            "service": "orders-service",
            "signal_type": "saturation",
            "metric_name": "db_connections_active",
            "severity": 0.95,
            "confidence": 0.98,
            "start_time": (base_time + timedelta(minutes=pool_start_idx)).isoformat(),
            "end_time": (base_time + timedelta(minutes=recover_idx)).isoformat(),
            "details": "Database connection pool saturated at maximum capacity of 100 connections.",
        },
        {
            "service": "orders-service",
            "signal_type": "baseline_shift",
            "metric_name": "db_connection_wait_seconds",
            "severity": 0.92,
            "confidence": 0.94,
            "start_time": (base_time + timedelta(minutes=exhaust_idx)).isoformat(),
            "end_time": (base_time + timedelta(minutes=recover_idx)).isoformat(),
            "details": "Abrupt mean shift in db_connection_wait_seconds from 5ms to 14.8s.",
        },
        {
            "service": "auth-service",
            "signal_type": "baseline_shift",
            "metric_name": "thread_pool_active_percent",
            "severity": 0.75,
            "confidence": 0.88,
            "start_time": (base_time + timedelta(minutes=auth_impact_idx)).isoformat(),
            "end_time": (base_time + timedelta(minutes=recover_idx)).isoformat(),
            "details": "Downstream thread pool saturation caused by blocking orders-service calls.",
        },
        {
            "service": "api-gateway",
            "signal_type": "spike",
            "metric_name": "http_504_rate",
            "severity": 0.80,
            "confidence": 0.90,
            "start_time": (base_time + timedelta(minutes=gateway_504_idx)).isoformat(),
            "end_time": (base_time + timedelta(minutes=recover_idx)).isoformat(),
            "details": "Downstream HTTP 504 Gateway Timeout spike resulting from upstream connection timeout.",
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
                "thought": "Checking Kubernetes events for crashes or warning events.",
                "tool": "query_k8s_events",
                "tool_input": {},
            },
            {
                "turn": 3,
                "thought": "Checking api-gateway HTTP 504 errors reported in events.",
                "tool": "query_prometheus",
                "tool_input": {"query": 'http_504_rate{service="api-gateway"}'},
            },
            {
                "turn": 4,
                "thought": "Observing PoolExhausted warning on orders-service. Querying active database connections.",
                "tool": "query_prometheus",
                "tool_input": {"query": 'db_connections_active{service="orders-service"}'},
            },
            {
                "turn": 5,
                "thought": "Verifying database connection wait latency on orders-service to confirm connection starvation.",
                "tool": "query_prometheus",
                "tool_input": {"query": 'db_connection_wait_seconds{service="orders-service"}'},
            },
        ],
        "final_text": (
            "Investigation Complete:\n\n"
            "Telemetric and cluster analysis demonstrates that orders-service suffered complete database connection pool exhaustion "
            f"beginning at {(base_time + timedelta(minutes=pool_start_idx)).isoformat()}, reaching the 100 connection ceiling at "
            f"{(base_time + timedelta(minutes=exhaust_idx)).isoformat()}. This induced an abrupt escalation in connection wait latency to 15s, "
            "causing blocking in auth-service and triggering cascading HTTP 504 Gateway Timeouts at api-gateway. "
            "The HPA scaling of api-gateway was symptomatic and did not alleviate the upstream database bottleneck.\n\n"
            "ROOT_CAUSE: POOL_EXHAUSTION\n"
            "ENTITY: orders-service\n"
            f"WINDOW: {(base_time + timedelta(minutes=pool_start_idx)).isoformat()} to {(base_time + timedelta(minutes=recover_idx)).isoformat()}\n"
            "EVIDENCE: db_connections_active, db_connection_wait_seconds, http_504_rate\n"
        ),
    }

    # Mock Baseline B Trajectory (Signals-Augmented Agent)
    mock_baseline_b_trajectory = {
        "turns": [
            {
                "turn": 1,
                "thought": "Querying pre-computed statistical signals across all active services.",
                "tool": "list_signals",
                "tool_input": {},
            },
            {
                "turn": 2,
                "thought": "Top anomalous signal is saturation on orders-service db_connections_active. Inspecting wait latency metric.",
                "tool": "query_prometheus",
                "tool_input": {"query": 'db_connection_wait_seconds{service="orders-service"}'},
            },
            {
                "turn": 3,
                "thought": "Correlating pool saturation on orders-service with downstream 504 spike on api-gateway.",
                "tool": "query_prometheus",
                "tool_input": {"query": 'http_504_rate{service="api-gateway"}'},
            },
        ],
        "final_text": (
            "Investigation Complete:\n\n"
            "Pre-computed signal analysis isolates the primary root cause to orders-service db_connections_active saturation (severity 0.95), "
            f"which provoked database wait times of ~15s starting at {(base_time + timedelta(minutes=pool_start_idx)).isoformat()}. "
            "Downstream auth-service thread exhaustion and api-gateway 504 spikes are direct causal consequences of the upstream connection bottleneck.\n\n"
            "ROOT_CAUSE: POOL_EXHAUSTION\n"
            "ENTITY: orders-service\n"
            f"WINDOW: {(base_time + timedelta(minutes=pool_start_idx)).isoformat()} to {(base_time + timedelta(minutes=recover_idx)).isoformat()}\n"
            "EVIDENCE: db_connections_active, db_connection_wait_seconds, http_504_rate\n"
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
    paths = generate_scenario_2()
    print("Generated Scenario 2 files:")
    for k, v in paths.items():
        print(f"  {k}: {v}")
