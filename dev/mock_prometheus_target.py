from __future__ import annotations

import math
from itertools import count
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


SCRAPE_BUCKET_SECONDS = 15.0
_SCRAPE_COUNTER = count()


def _next_bucket() -> int:
    return next(_SCRAPE_COUNTER)


def _wave(bucket: int, period_buckets: int, phase: float = 0.0) -> float:
    return math.sin(((bucket + phase) / period_buckets) * math.tau)


def _saw(bucket: int, period_buckets: int, phase: int = 0) -> float:
    return ((bucket + phase) % period_buckets) / max(period_buckets - 1, 1)


def _square_window(bucket: int, period_buckets: int, duty_cycle: float = 0.5, phase: int = 0) -> bool:
    position = ((bucket + phase) % period_buckets) / period_buckets
    return position < duty_cycle


def _deterministic_noise(bucket: int, service_index: int, scale: float = 0.015) -> float:
    # Stable pseudo-noise gives the data a production-like texture without randomness across scrapes.
    raw = math.sin((bucket * 12.9898) + (service_index * 78.233)) * 43758.5453
    fractional = raw - math.floor(raw)
    return (fractional - 0.5) * 2.0 * scale


def _cpu_usage_for_profile(profile: str, bucket: int, service_index: int, baseline: float, amplitude: float, phase: float) -> float:
    noise = _deterministic_noise(bucket, service_index)
    if profile == "baseline_shift":
        # Repeats a clean low/high operating regime. Good for Ruptures and baseline shift.
        shifted = 0.9 if not _square_window(bucket, 160, duty_cycle=0.5, phase=0) else 0.0
        return baseline + shifted + (_wave(bucket, 20, phase) * 0.015) + (noise * 0.35)
    if profile == "seasonal":
        # Repeating daily-like load pattern compressed into minutes. Good for Prophet, STUMPY, and Darts.
        return baseline + (_wave(bucket, 24, phase) * amplitude) + (_wave(bucket, 8, phase) * 0.06) + noise
    if profile == "spiky":
        # Mostly normal with brief incident-like bursts. Good for ADTK, PyOD, and River.
        spike = 1.35 if _square_window(bucket, 30, duty_cycle=0.04, phase=2) else 0.0
        return baseline + (_wave(bucket, 18, phase) * amplitude) + spike + (noise * 0.25)
    if profile == "trend":
        # Slow ramp that resembles memory/CPU pressure building up. Good for trend regression.
        return baseline + (_saw(bucket, 480, phase=int(phase * 10)) * 1.15) + (_wave(bucket, 18, phase) * amplitude) + noise
    if profile == "drift":
        # Distribution slowly moves between operating modes. Good for drift-oriented analyzers.
        drift = 0.28 * _wave(bucket, 64, phase)
        variance_mode = 0.10 if _square_window(bucket, 40, duty_cycle=0.45, phase=5) else 0.02
        return baseline + drift + (_wave(bucket, 6, phase) * variance_mode) + noise
    if profile == "mixed":
        # Combines seasonality, a baseline step, and occasional spikes for broad analyzer testing.
        shifted = 0.28 if _square_window(bucket, 40, duty_cycle=0.45, phase=4) else 0.0
        spike = 0.45 if _square_window(bucket, 18, duty_cycle=0.11, phase=1) else 0.0
        return baseline + shifted + spike + (_wave(bucket, 20, phase) * amplitude) + noise
    return baseline + (_wave(bucket, 12, phase) * amplitude) + noise


def _metric_lines() -> str:
    bucket = _next_bucket()

    services = [
        {
            "service": "sample-ec2-instance",
            "instance": "i-local-01",
            "env": "local",
            "phase": 0.0,
            "baseline": 0.78,
            "amplitude": 0.42,
        },
        {
            "service": "checkout",
            "instance": "checkout-pod-01",
            "env": "local",
            "phase": 1.4,
            "baseline": 0.34,
            "amplitude": 0.22,
        },
        {
            "service": "payments",
            "instance": "payments-pod-01",
            "env": "local",
            "phase": 2.2,
            "baseline": 0.48,
            "amplitude": 0.28,
        },
        {
            "service": "ruptures-lab",
            "instance": "ruptures-lab-01",
            "env": "local",
            "phase": 0.0,
            "baseline": 0.28,
            "amplitude": 0.04,
            "profile": "baseline_shift",
        },
        {
            "service": "forecast-lab",
            "instance": "forecast-lab-01",
            "env": "local",
            "phase": 0.6,
            "baseline": 0.48,
            "amplitude": 0.26,
            "profile": "seasonal",
        },
        {
            "service": "spike-lab",
            "instance": "spike-lab-01",
            "env": "local",
            "phase": 1.2,
            "baseline": 0.2,
            "amplitude": 0.03,
            "profile": "spiky",
        },
        {
            "service": "trend-lab",
            "instance": "trend-lab-01",
            "env": "local",
            "phase": 1.8,
            "baseline": 0.18,
            "amplitude": 0.04,
            "profile": "trend",
        },
        {
            "service": "drift-lab",
            "instance": "drift-lab-01",
            "env": "local",
            "phase": 2.4,
            "baseline": 0.42,
            "amplitude": 0.08,
            "profile": "drift",
        },
        {
            "service": "mixed-lab",
            "instance": "mixed-lab-01",
            "env": "local",
            "phase": 3.0,
            "baseline": 0.38,
            "amplitude": 0.14,
            "profile": "mixed",
        },
    ]

    lines = [
        "# HELP cpu_usage Synthetic CPU usage ratio for local Ops Signals testing",
        "# TYPE cpu_usage gauge",
        "# HELP request_latency_p95 Synthetic p95 latency in milliseconds",
        "# TYPE request_latency_p95 gauge",
        "# HELP error_rate Synthetic error rate ratio",
        "# TYPE error_rate gauge",
        "# HELP ops_signal_lab_value Synthetic analyzer-router lab signal with purpose-built behavior",
        "# TYPE ops_signal_lab_value gauge",
    ]

    for index, item in enumerate(services):
        profile = item.get("profile", "cpu")
        cpu_usage = _cpu_usage_for_profile(
            profile,
            bucket,
            index,
            float(item["baseline"]),
            float(item["amplitude"]),
            float(item["phase"]),
        )
        cpu_usage = max(0.01, min(1.7, cpu_usage))
        latency = max(15.0, 140.0 + (cpu_usage * 320.0) + (index * 9.0))
        errors = max(0.0, min(0.35, 0.006 + max(cpu_usage - 0.72, 0.0) * 0.22))
        labels = f'service="{item["service"]}",instance="{item["instance"]}",env="{item["env"]}"'
        lines.append(f"cpu_usage{{{labels}}} {cpu_usage:.5f}")
        lines.append(f"request_latency_p95{{{labels}}} {latency:.5f}")
        lines.append(f"error_rate{{{labels}}} {errors:.5f}")
        if "profile" in item:
            lab_labels = f'{labels},profile="{profile}"'
            lines.append(f"ops_signal_lab_value{{{lab_labels}}} {cpu_usage:.5f}")

    return "\n".join(lines) + "\n"


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path not in {"/metrics", "/"}:
            self.send_response(404)
            self.end_headers()
            return

        payload = _metric_lines().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 9101), MetricsHandler)
    print("Mock Prometheus target listening on :9101")
    server.serve_forever()
