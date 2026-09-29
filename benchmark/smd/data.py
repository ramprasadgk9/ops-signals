"""The Server Machine Dataset (SMD; Su et al., KDD 2019, "OmniAnomaly"), pinned to a commit of the
OmniAnomaly repository, which publishes it under the MIT license.

28 machines from a large internet company, 38 metrics each, 5 weeks at one-minute intervals, split
into a train half and a test half of equal length. The metrics are unnamed - each row is 38 numbers
already scaled to 0-1 - so they are called metric_01..metric_38 here, numbered as the labels number
them (1-based). Two label files per machine:

- test_label: 0/1 per test row. A run of 1s is one incident. This is the answer key for detection,
  as in the published evaluations.
- interpretation_label: "start-end:d1,d2,..." per incident, the metrics involved. Used only to score
  which metrics an alert points at. Its ranges normally end one row past the labeled run. On 5 machines
  it disagrees with test_label beyond that (a shifted range, a labeled incident missing from the list,
  extra overlapping ranges), so each incident takes the metrics of every range that overlaps it, and
  `label_discrepancy` marks those machines.

The README doesn't say the train half is incident-free. It's used as history the analyzers see, and
as the "normal" data the static threshold learns from; alerts are scored only in the test half.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from benchmark.fetch import CACHE_DIR, ensure_checkout

SMD_REPOSITORY = "https://github.com/NetManAIOps/OmniAnomaly.git"
SMD_COMMIT = "7fb0e0acf89ea49908896bcc9f9e80fcfff6baf4"
SMD_CACHE_DIR = CACHE_DIR / "omnianomaly"
DATASET_DIR = "ServerMachineDataset"
METRIC_COUNT = 38


@dataclass(slots=True)
class Incident:
    start: int  # 0-based test row, inclusive
    end: int  # inclusive
    metrics: list[int] = field(default_factory=list)  # 1-based metric numbers, from interpretation_label


@dataclass(slots=True)
class SmdMachine:
    name: str
    train: np.ndarray  # rows x 38
    test: np.ndarray
    labels: np.ndarray  # 0/1 per test row
    incidents: list[Incident]
    interpretation_ranges: int
    label_discrepancy: bool


def ensure_smd(cache_dir: Path = SMD_CACHE_DIR, commit: str = SMD_COMMIT) -> Path:
    checkout = ensure_checkout(
        SMD_REPOSITORY,
        commit,
        cache_dir,
        required=tuple(f"{DATASET_DIR}/{part}" for part in ("train", "test", "test_label", "interpretation_label")),
    )
    return checkout / DATASET_DIR


def machine_names(dataset_dir: Path) -> list[str]:
    return sorted(path.stem for path in (dataset_dir / "test").glob("machine-*.txt"))


def metric_name(number: int) -> str:
    return f"metric_{number:02d}"


def load_machine(dataset_dir: Path, name: str) -> SmdMachine:
    train = np.loadtxt(dataset_dir / "train" / f"{name}.txt", delimiter=",", dtype=float)
    test = np.loadtxt(dataset_dir / "test" / f"{name}.txt", delimiter=",", dtype=float)
    labels = np.loadtxt(dataset_dir / "test_label" / f"{name}.txt", dtype=int)
    ranges = _interpretation_ranges(dataset_dir / "interpretation_label" / f"{name}.txt")
    incidents = [
        Incident(start, end, sorted({m for r_start, r_end, metrics in ranges if r_start <= end and r_end >= start for m in metrics}))
        for start, end in label_runs(labels)
    ]
    exact = {(start, end) for start, end in label_runs(labels)}
    discrepancy = len(ranges) != len(incidents) or any(
        (r_start, r_end) not in exact and (r_start, r_end - 1) not in exact for r_start, r_end, _ in ranges
    )
    return SmdMachine(name, train, test, labels, incidents, len(ranges), discrepancy)


def label_runs(labels: np.ndarray) -> list[tuple[int, int]]:
    """Each run of consecutive 1s as (first row, last row), 0-based and inclusive."""
    padded = np.concatenate([[0], np.asarray(labels, dtype=int), [0]])
    changes = np.flatnonzero(np.diff(padded))
    return [(int(start), int(end) - 1) for start, end in zip(changes[::2], changes[1::2])]


def _interpretation_ranges(path: Path) -> list[tuple[int, int, list[int]]]:
    ranges = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        span, metrics = line.split(":")
        start, end = (int(value) for value in span.split("-"))
        ranges.append((start, end, [int(value) for value in metrics.split(",") if value.strip()]))
    return ranges
