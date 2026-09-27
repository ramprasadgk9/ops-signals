"""The Turing Change Point Dataset (TCPD) and its benchmark results, at pinned commits.

Two repositories, both MIT-licensed:

- TCPD (alan-turing-institute/TCPD): the series and five annotators' change points. Most series ship
  as JSON; the rest are built by TCPD's own download scripts, which this harness doesn't run.
- TCPDBench (alan-turing-institute/TCPDBench): the published results of 14 methods, including every
  method's predicted change points per series, from van den Burg & Williams (2020).

Only data files are read from either checkout; no code from them is run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from benchmark.fetch import CACHE_DIR, ensure_checkout

TCPD_REPOSITORY = "https://github.com/alan-turing-institute/TCPD.git"
TCPD_COMMIT = "e8f19a3635e3b7f1a8aff59ce7f4d9bea17525c0"
TCPDBENCH_REPOSITORY = "https://github.com/alan-turing-institute/TCPDBench.git"
TCPDBENCH_COMMIT = "167210005c09d2c44f9b2083b95f989a64be4b6b"

# The paper's univariate evaluation set: every series except the multivariate ones, the five
# quality-control series (used to vet annotators), and uk_coal_employ, which the paper leaves out
# of its averages because several methods can't handle its missing values (its "zero_no_coal"
# setting; a method's failure on any other series scores 0).
MULTIVARIATE = {"apple", "bee_waggle_6", "occupancy", "run_log"}
EXCLUDED_FROM_AVERAGES = {"uk_coal_employ"}
PUBLISHED_METHODS = (
    "amoc", "binseg", "bocpd", "bocpdms", "cpnp", "ecp", "kcpa",
    "pelt", "prophet", "rbocpdms", "rfpop", "segneigh", "wbs", "zero",
)


@dataclass(slots=True)
class TcpdSeries:
    name: str
    long_name: str
    values: np.ndarray
    annotations: dict[str, list[int]]


def ensure_tcpd() -> tuple[Path, Path]:
    tcpd = ensure_checkout(TCPD_REPOSITORY, TCPD_COMMIT, CACHE_DIR / "tcpd", required=("datasets", "annotations.json"))
    bench = ensure_checkout(
        TCPDBENCH_REPOSITORY, TCPDBENCH_COMMIT, CACHE_DIR / "tcpdbench", required=("analysis/output/summaries",)
    )
    return tcpd, bench


def evaluation_set(tcpd_dir: Path) -> list[str]:
    names = sorted(json.loads((tcpd_dir / "annotations.json").read_text(encoding="utf-8")))
    return [
        name for name in names
        if name not in MULTIVARIATE and name not in EXCLUDED_FROM_AVERAGES and not name.startswith("quality_control")
    ]


def is_available(tcpd_dir: Path, name: str) -> bool:
    return (tcpd_dir / "datasets" / name / f"{name}.json").exists()


def load_series(tcpd_dir: Path, name: str) -> TcpdSeries:
    raw = json.loads((tcpd_dir / "datasets" / name / f"{name}.json").read_text(encoding="utf-8"))
    annotations = json.loads((tcpd_dir / "annotations.json").read_text(encoding="utf-8"))[name]
    values = np.array([np.nan if value is None else float(value) for value in raw["series"][0]["raw"]])
    return TcpdSeries(name=name, long_name=raw.get("longname") or name, values=values, annotations=annotations)


def published_summary(bench_dir: Path, name: str) -> dict[str, Any]:
    return json.loads((bench_dir / "analysis" / "output" / "summaries" / f"summary_{name}.json").read_text(encoding="utf-8"))


def published_default_scores(bench_dir: Path) -> dict[str, dict[str, dict[str, float | None]]]:
    """{metric: {series: {method: score or None when the method failed}}} for the default experiment."""
    scores_dir = bench_dir / "analysis" / "output" / "scores"
    return {
        metric: json.loads((scores_dir / f"default_{metric}_scores.json").read_text(encoding="utf-8"))
        for metric in ("f1", "cover")
    }
