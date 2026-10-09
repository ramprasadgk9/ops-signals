"""RCAEval RE1 (Pham et al., 2024): faults injected into three microservice demo systems, with the
injection moment recorded. Metrics only, 1-second samples.

Source: https://zenodo.org/records/14590730 (CC BY 4.0), cached under benchmark/.cache/rcaeval.
Each archive is pinned by SHA-256 (checked against the MD5 Zenodo publishes when pinned) and a
download that doesn't match is refused, as for every other public dataset here.

| System | Services x faults x repeats | Normal time before the fault | Metric columns |
| --- | --- | --- | --- |
| RE1-OB Online Boutique | 5 x 5 x 5 | ~35 min | ready-made: <svc>_cpu, <svc>_mem, <svc>_latency |
| RE1-SS Sock Shop | 5 x 5 x 5 | ~6 min | raw Prometheus: cAdvisor container metrics, Istio latency quantiles |
| RE1-TT Train Ticket | 5 x 5 x 5 | ~8 min | raw Prometheus, like Sock Shop |

Faults: cpu, mem, disk, delay, loss. For each case we watch the faulty service's own CPU, memory
and latency. Counters (`*-total`) become per-second rates, the way a PromQL rate() query reads them.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from benchmark.fetch import CACHE_DIR, ensure_download

ZENODO_RECORD = "https://zenodo.org/records/14590730"
RCAEVAL_CACHE_DIR = CACHE_DIR / "rcaeval"
SYSTEMS = ("RE1-OB", "RE1-SS", "RE1-TT")
ARCHIVE_SHA256 = {
    "RE1-OB": "4a709297e0a829f0f2ee8a7792a6d74da32d663c600565b7fffc860963b840c4",
    "RE1-SS": "b4424b0b3863b7397712caa0f305ef59964b03784dfcb23e23e0a95a2e746f99",
    "RE1-TT": "2b33b7ab07198e0d69f229e697bfcef794a656e8db73a1d732142effde17c595",
}
METRIC_KINDS = ("cpu", "mem", "latency")

# One cadence for every system: 2-second points, a scheduled run every 30 seconds over the last
# hour, after 4 minutes of history. Sock Shop has only ~6 minutes before its faults, so a longer
# warm-up would leave nothing normal to score.
INTERVAL_SECONDS = 2
REPLAY_STEP = 15
REPLAY_WINDOW = 1800
REPLAY_NEW_EVENT_HORIZON = 60
REPLAY_MIN_HISTORY = 120

_RAW_COLUMNS = {
    "cpu": "{service}_container-cpu-usage-seconds-total",
    "mem": "{service}_container-memory-working-set-bytes",
    "latency": "{service}_istio-latency-95",
}


def ensure_rcaeval(system: str = "RE1-OB", cache_dir: Path = RCAEVAL_CACHE_DIR) -> Path:
    """The extracted system folder, downloading and verifying its archive first if needed."""
    if system not in ARCHIVE_SHA256:
        raise ValueError(f"unknown RCAEval system {system!r}; expected one of {sorted(ARCHIVE_SHA256)}")
    archive = ensure_download(f"{ZENODO_RECORD}/files/{system}.zip?download=1", ARCHIVE_SHA256[system], cache_dir / f"{system}.zip")
    target = cache_dir / system
    if not (target.is_dir() and any(target.iterdir())):
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(cache_dir)
    return target


def cases(root: Path, repeats: tuple[str, ...] | None = ("1",)) -> list[Path]:
    """Case folders (<service>_<fault>/<repeat>), sorted; every repeat when `repeats` is None."""
    return sorted(
        case for fault_dir in root.iterdir() if fault_dir.is_dir()
        for case in fault_dir.iterdir()
        if case.is_dir() and (repeats is None or case.name in repeats) and (case / "data.csv").exists()
    )


def describe(case: Path) -> tuple[str, str, str]:
    """(system, service, fault) from a case folder such as .../RE1-OB/cartservice_cpu/1."""
    service, fault = case.parent.name.rsplit("_", 1)
    return case.parent.parent.name, service, fault


def column_for(system: str, service: str, kind: str) -> str:
    if system == "RE1-OB":
        return f"{service}_{kind}"
    return _RAW_COLUMNS[kind].format(service=service)


def load_metric(case: Path, column: str) -> tuple[pd.DataFrame, pd.Timestamp] | None:
    """The metric resampled to INTERVAL_SECONDS, and the injection moment; None if it's missing."""
    data = pd.read_csv(case / "data.csv", usecols=lambda name: name in ("time", column))
    if column not in data:
        return None
    data = data.drop_duplicates("time").sort_values("time")
    values = data[column].to_numpy(dtype=float)
    if column.endswith("-total"):
        values = np.clip(np.diff(values, prepend=values[0]) / np.diff(data["time"].to_numpy(dtype=float), prepend=1.0), 0, None)
    series = pd.Series(values, index=pd.to_datetime(data["time"], unit="s", utc=True))
    series = series.resample(f"{INTERVAL_SECONDS}s").mean().interpolate(limit_direction="both")
    if not series.notna().any():
        return None
    frame = pd.DataFrame({"timestamp": series.index, "value": series.to_numpy(), "metric_name": column})
    injected = pd.Timestamp(int(float((case / "inject_time.txt").read_text().strip())), unit="s", tz="UTC")
    return frame.reset_index(drop=True), injected
