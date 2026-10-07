"""Synthetic metrics for one "cluster" of the local multi-cluster Mimir setup
(dev/multicluster/docker-compose.yml, started by scripts/multicluster.sh).

Two modes, both computing every value from the clock alone, so history and live data line up:

  python cluster_metrics.py serve      Prometheus scrape target on $PORT (default 9100).
  python cluster_metrics.py backfill   Pushes $BACKFILL_HOURS of history straight into Mimir with
                                       the remote-write protocol, labelled exactly as the live
                                       Prometheus pipeline labels it, so analyzers have a baseline
                                       from the first minute.
  python cluster_metrics.py deploys    Posts the deploy events that go with the incidents to Ops
                                       Signals ($OPS_SIGNALS_URL/api/events), for the last
                                       $BACKFILL_HOURS. Safe to run again: events already there are skipped.

The incident service runs 3 pods. Each incident is a release: 2 pods are replaced by the new
version (a canary), and those 2 are the slow ones; when the incident ends the rollout finishes.
Its deploy goes to that cluster only, and the same version went to eu 10 minutes earlier without
trouble, so a finding in us should name the us deploy and never the eu one.

Standard library only (runs in python:3.12-alpine). The remote-write body is hand-encoded
protobuf, compressed with snappy's literal-only encoding, which every snappy decoder accepts.

Environment:
  CLUSTER                 eu | us | staging - scales traffic so clusters look different.
  INCIDENT_SERVICE        service that has a recurring incident (empty = none).
  INCIDENT_EVERY_MINUTES  how often it starts (default 120).
  INCIDENT_FOR_MINUTES    how long it lasts (default 20).
  INCIDENT_FACTOR         latency multiplier during the incident (default 3).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import struct
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SERVICES = {
    # service: (requests/s at the daily peak, base p95 latency ms, base cpu ratio)
    "checkout": (120.0, 180.0, 0.45),
    "payments": (60.0, 240.0, 0.35),
    "search": (300.0, 90.0, 0.55),
}
CLUSTER_SCALE = {"eu": 1.0, "us": 0.6, "staging": 0.1}
DAY = 86400.0
PODS = 3
# Gauges are split by pod; the request counter stays per service (a new pod's counter would start at 0).
POD_METRICS = ("request_latency_p95", "error_rate", "cpu_usage")
EARLIER_CLUSTER = "eu"


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name, "").strip()
    return float(value) if value else default


CLUSTER = os.environ.get("CLUSTER", "eu")
INCIDENT_SERVICE = os.environ.get("INCIDENT_SERVICE", "").strip()
INCIDENT_EVERY = _env_int("INCIDENT_EVERY_MINUTES", 120) * 60
INCIDENT_FOR = _env_int("INCIDENT_FOR_MINUTES", 20) * 60
INCIDENT_FACTOR = _env_float("INCIDENT_FACTOR", 3.0)


def _noise(service: str, metric: str, t: float, spread: float) -> float:
    """Same value for the same cluster/service/metric/minute, in every process."""
    seed = f"{CLUSTER}:{service}:{metric}:{int(t // 60)}"
    return random.Random(seed).uniform(-spread, spread)


def _daily(t: float) -> float:
    """0..1, lowest around 03:00 UTC and highest around 15:00 UTC."""
    return 0.5 + 0.5 * math.sin(2 * math.pi * (t / DAY - 0.375))


def in_incident(service: str, t: float) -> bool:
    return bool(INCIDENT_SERVICE) and service == INCIDENT_SERVICE and (t % INCIDENT_EVERY) < INCIDENT_FOR


def _release(t: float) -> int:
    return int(t // INCIDENT_EVERY)


def release_version(release: int) -> str:
    return f"v2.{release % 100}.0"


def _pod(service: str, release: int, index: int) -> str:
    template = hashlib.sha1(f"{service}:{release}".encode()).hexdigest()[:8]
    suffix = hashlib.sha1(f"{service}:{release}:{index}".encode()).hexdigest()[:5]
    return f"{service}-{template}-{suffix}"


def pods_at(service: str, t: float) -> list[tuple[str, bool]]:
    """(pod, slow) for the incident service, [] for every other service. During an incident pod 0
    still runs the previous release and pods 1 and 2 the new, slow one."""
    if not INCIDENT_SERVICE or service != INCIDENT_SERVICE:
        return []
    release = _release(t)
    if in_incident(service, t):
        return [(_pod(service, release - 1, 0), False), *((_pod(service, release, index), True) for index in range(1, PODS))]
    return [(_pod(service, release, index), False) for index in range(PODS)]


def values_at(t: float) -> dict[str, dict[str, float]]:
    """{metric_name: {service: value}} at unix time t."""
    scale = CLUSTER_SCALE.get(CLUSTER, 1.0)
    result: dict[str, dict[str, float]] = {"http_requests_total": {}, "request_latency_p95": {}, "cpu_usage": {}, "error_rate": {}}
    for service, (peak_rps, base_latency, base_cpu) in SERVICES.items():
        incident = in_incident(service, t)
        load = _daily(t)
        latency = base_latency * (1 + 0.3 * load) * (1 + _noise(service, "latency", t, 0.04))
        errors = 0.004 + 0.002 * load + _noise(service, "errors", t, 0.001)
        if incident:
            latency *= INCIDENT_FACTOR
            errors += 0.05
        result["request_latency_p95"][service] = round(latency, 3)
        result["error_rate"][service] = round(max(errors, 0.0), 5)
        result["cpu_usage"][service] = round(min(0.98, base_cpu * (0.6 + 0.6 * load) + _noise(service, "cpu", t, 0.02)), 5)
        result["http_requests_total"][service] = round(_requests_counter(peak_rps * scale, t), 1)
    return result


def _requests_counter(peak_rps: float, t: float) -> float:
    """Integral of rps(t) = peak * (0.2 + 0.8 * daily(t)), so rate() recovers the daily cycle."""
    w = 2 * math.pi / DAY
    phase = 2 * math.pi * 0.375
    # integral of 0.5 + 0.5*sin(w t - phase) dt = 0.5 t - 0.5/w * cos(w t - phase)
    daily_integral = 0.5 * t - (0.5 / w) * math.cos(w * t - phase)
    return peak_rps * (0.2 * t + 0.8 * daily_integral)


METRIC_TYPES = {
    "http_requests_total": "counter",
    "request_latency_p95": "gauge",
    "cpu_usage": "gauge",
    "error_rate": "gauge",
}


def samples_at(t: float) -> list[tuple[str, dict[str, str], float]]:
    """(metric, labels, value) at unix time t, one per series - per pod where the service has pods.
    A pod reports the service value, or the healthy one if it isn't on the slow release."""
    values = values_at(t)
    samples: list[tuple[str, dict[str, str], float]] = []
    for metric, by_service in values.items():
        for service, value in by_service.items():
            labels = {"service": service, "env": "prod"}
            pods = pods_at(service, t) if metric in POD_METRICS else []
            if not pods:
                samples.append((metric, labels, value))
                continue
            for name, slow in pods:
                pod_value = value if slow else _healthy(metric, service, t)
                pod_value *= 1 + _noise(service, f"{metric}:{name}", t, 0.03)
                samples.append((metric, {**labels, "pod": name}, round(pod_value, 5)))
    return samples


def _healthy(metric: str, service: str, t: float) -> float:
    global INCIDENT_SERVICE
    saved, INCIDENT_SERVICE = INCIDENT_SERVICE, ""
    try:
        return values_at(t)[metric][service]
    finally:
        INCIDENT_SERVICE = saved


def exposition(t: float) -> str:
    lines: list[str] = []
    typed: set[str] = set()
    for metric, labels, value in samples_at(t):
        if metric not in typed:
            typed.add(metric)
            lines.append(f"# TYPE {metric} {METRIC_TYPES[metric]}")
        rendered = ",".join(f'{name}="{text}"' for name, text in labels.items())
        lines.append(f"{metric}{{{rendered}}} {value}")
    return "\n".join(lines) + "\n"


def deploy_events(start: float, end: float) -> list[dict[str, object]]:
    """The deploys that go with the incidents starting in (start, end]: the release reaches
    EARLIER_CLUSTER 10 minutes ahead without trouble, then this cluster a minute before its incident."""
    if not INCIDENT_SERVICE:
        return []
    events: list[dict[str, object]] = []
    for release in range(_release(start) + 1, _release(end) + 1):
        begins = release * INCIDENT_EVERY
        version = release_version(release)
        for cluster, lead in ((EARLIER_CLUSTER, 10 * 60), (CLUSTER, 60)):
            events.append({"service": INCIDENT_SERVICE, "type": "deploy", "version": version, "cluster": cluster,
                           "timestamp": begins - lead, "source": "multicluster-dev",
                           "description": f"{INCIDENT_SERVICE} {version} to {cluster}"})
    return events


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path not in ("/metrics", "/"):
            self.send_response(404)
            self.end_headers()
            return
        body = exposition(time.time()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        return


def serve() -> None:
    port = _env_int("PORT", 9100)
    print(f"cluster-metrics: cluster={CLUSTER} incident={INCIDENT_SERVICE or 'none'} listening on :{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), _Handler).serve_forever()


# --- remote write (backfill) --------------------------------------------------------------------


def _uvarint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _field(number: int, payload: bytes) -> bytes:
    """Length-delimited protobuf field."""
    return _uvarint((number << 3) | 2) + _uvarint(len(payload)) + payload


def encode_write_request(series: list[tuple[dict[str, str], list[tuple[int, float]]]]) -> bytes:
    """prometheus.WriteRequest: timeseries=1 { labels=1 {name=1, value=2}, samples=2 {value=1 double, timestamp=2 int64 ms} }."""
    body = bytearray()
    for labels, samples in series:
        ts = bytearray()
        for name in sorted(labels):
            ts += _field(1, _field(1, name.encode()) + _field(2, labels[name].encode()))
        for timestamp_ms, value in samples:
            sample = b"\x09" + struct.pack("<d", value) + b"\x10" + _uvarint(timestamp_ms)
            ts += _field(2, sample)
        body += _field(1, bytes(ts))
    return bytes(body)


def snappy_literal(data: bytes) -> bytes:
    """Snappy block made only of literal elements - valid input for any snappy decoder."""
    out = bytearray(_uvarint(len(data)))
    for start in range(0, len(data), 65536):
        chunk = data[start : start + 65536]
        n = len(chunk) - 1
        if n < 60:
            out.append(n << 2)
        elif n < 256:
            out += bytes([60 << 2, n])
        else:
            out += bytes([61 << 2]) + struct.pack("<H", n)
        out += chunk
    return bytes(out)


def _push(url: str, tenant: str, payload: bytes) -> None:
    request = urllib.request.Request(
        url,
        data=snappy_literal(payload),
        method="POST",
        headers={
            "Content-Type": "application/x-protobuf",
            "Content-Encoding": "snappy",
            "X-Prometheus-Remote-Write-Version": "0.1.0",
            "X-Scope-OrgID": tenant,
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        response.read()


def _wait_for(url: str, attempts: int = 120) -> None:
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(2)
    raise SystemExit(f"backfill: {url} did not become ready")


def backfill() -> None:
    """Writes history for every target in $BACKFILL_TARGETS, a ';'-separated list of
    cluster|tenant|instance|replica_label=value,...|incident_service entries (last two optional)."""
    mimir = os.environ.get("MIMIR_URL", "http://mimir:9009").rstrip("/")
    hours = _env_int("BACKFILL_HOURS", 72)
    step = _env_int("BACKFILL_STEP_SECONDS", 60)
    job = os.environ.get("SCRAPE_JOB", "cluster-metrics")
    marker = os.environ.get("BACKFILL_MARKER", "/state/backfilled")
    if os.path.exists(marker):
        print("backfill: history already written, skipping (reset with scripts/multicluster.sh reset)", flush=True)
        return
    _wait_for(f"{mimir}/ready")

    global CLUSTER, INCIDENT_SERVICE
    end = int(time.time()) - 120
    start = end - hours * 3600
    total = 0
    for entry in filter(None, (item.strip() for item in os.environ.get("BACKFILL_TARGETS", "").split(";"))):
        cluster, tenant, instance, *rest = entry.split("|")
        replicas = [dict([pair.split("=", 1)]) for pair in rest[0].split(",")] if rest and rest[0] else [{}]
        incident = rest[1] if len(rest) > 1 else ""
        CLUSTER, INCIDENT_SERVICE = cluster, incident
        # One request per 6h of data keeps each push small.
        for window_start in range(start, end, 6 * 3600):
            window = range(window_start, min(window_start + 6 * 3600, end), step)
            by_series: dict[tuple[tuple[str, str], ...], list[tuple[int, float]]] = {}
            for t in window:
                for metric, labels, value in samples_at(t):
                    key = tuple(sorted({"__name__": metric, **labels}.items()))
                    by_series.setdefault(key, []).append((t * 1000, value))
            series = []
            for key, samples in by_series.items():
                for replica in replicas:
                    labels = {**dict(key), "job": job, "instance": instance, "cluster": cluster, **replica}
                    series.append((labels, samples))
            _push(f"{mimir}/api/v1/push", tenant, encode_write_request(series))
            total += sum(len(samples) for _, samples in series)
        print(f"backfill: cluster={cluster} tenant={tenant} replicas={len(replicas)} incident={incident or 'none'} done", flush=True)
    os.makedirs(os.path.dirname(marker), exist_ok=True)
    with open(marker, "w", encoding="utf-8") as handle:
        handle.write(f"{start}-{end}\n")
    print(f"backfill: wrote {total} samples covering the last {hours}h", flush=True)


def post_deploys() -> None:
    """Posts deploy_events for the last $BACKFILL_HOURS to $OPS_SIGNALS_URL, skipping ones already there."""
    from datetime import datetime, timezone

    base = os.environ.get("OPS_SIGNALS_URL", "http://localhost:8001").rstrip("/")
    token = os.environ.get("OPS_SIGNALS_EVENTS_TOKEN", "").strip()
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
    end = time.time()
    events = deploy_events(end - _env_int("BACKFILL_HOURS", 72) * 3600, end)
    if not events:
        print("deploys: no incident service set, nothing to post", flush=True)
        return
    listing = urllib.request.Request(f"{base}/api/events?service={INCIDENT_SERVICE}&type=deploy&limit=500", headers=headers)
    with urllib.request.urlopen(listing, timeout=30) as response:
        existing = {(item.get("version"), item.get("cluster")) for item in json.load(response)}
    new = [event for event in events if (event["version"], event["cluster"]) not in existing]
    for event in new:
        event["timestamp"] = datetime.fromtimestamp(float(event["timestamp"]), timezone.utc).isoformat()
    for start in range(0, len(new), 100):
        request = urllib.request.Request(f"{base}/api/events", data=json.dumps(new[start : start + 100]).encode(),
                                         method="POST", headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
    print(f"deploys: posted {len(new)} deploy events ({len(events) - len(new)} were already there)", flush=True)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if mode == "serve":
        serve()
    elif mode == "backfill":
        backfill()
    elif mode == "deploys":
        post_deploys()
    else:
        raise SystemExit(f"unknown mode {mode!r}; use serve, backfill or deploys")
