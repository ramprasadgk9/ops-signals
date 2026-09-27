"""Run every benchmark suite in one go and write a self-contained, local results snapshot.

    .venv/bin/python -m benchmark.run_all

Each run lands in its own folder under benchmark/results/ (gitignored - snapshots stay on the
machine that produced them):

    benchmark/results/<UTC timestamp>-<short sha>/
        results.json   every suite's raw results plus the run manifest
        report.html    the human-readable evidence report, built from results.json
        raw/           the per-scenario JSON/Markdown the individual runners already write

The manifest records what a reviewer needs to trust or reproduce a number: commit, whether the
tree was dirty, Python and library versions, machine, and SHA-256 hashes of the configs and
datasets used. The accuracy fingerprint hashes every suite's results except wall-clock timings,
so two runs on the same commit and data should print the same fingerprint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import yaml

from benchmark import behavior_benchmark, performance_benchmark, router_benchmark
from benchmark.router_benchmark import DEFAULT_ANALYZER_REGISTRY_DIR, PROJECT_ROOT
from benchmark.run_behavior_scenarios import discover_scenarios as discover_behavior_scenarios
from benchmark.run_router_scenarios import discover_scenarios as discover_router_scenarios
from intelligence.analyzer_registry import load_registrations

RESULTS_ROOT = PROJECT_ROOT / "benchmark" / "results"
SCENARIOS_ROOT = PROJECT_ROOT / "benchmark" / "scenarios"
SCHEMA_VERSION = 1

# Points kept per plotted series in the report - enough to show the shape, small enough that a
# report with a dozen scenarios stays a few hundred KB.
SERIES_POINTS = 240

TRACKED_PACKAGES = [
    "numpy",
    "pandas",
    "scipy",
    "scikit-learn",
    "statsmodels",
    "ruptures",
    "stumpy",
    "prophet",
    "pyod",
    "numba",
]

CONFIG_FILES = [
    "config/analyzers.yaml",
    "experiments/analyzer_router/analyzer_registry.yaml",
    "experiments/analyzer_router/experiment_config.yaml",
]
CONFIG_GLOBS = ["config/analyzer_registry.d/*.yml", "config/behavior_definitions.d/*.yml"]

# Keys holding wall-clock measurements or per-run paths - excluded from the accuracy fingerprint.
TIMING_KEYS = {
    "elapsed_seconds",
    "normalization_seconds",
    "total_seconds",
    "duration_seconds_wall",
    "batch_seconds",
    "replay_seconds",
    "wall_seconds_total",
    "workers",
    "nab_format_dir",
}


def run_router_suite(raw_dir: Path) -> dict[str, Any]:
    scenarios = []
    for scenario_dir in discover_router_scenarios(SCENARIOS_ROOT):
        evaluation = router_benchmark.run_benchmark(scenario_dir, reports_dir=raw_dir)
        ground_truth = _load_yaml(scenario_dir / "ground_truth.yaml")
        scenarios.append(
            {
                "scenario": _scenario_metadata(scenario_dir, ground_truth),
                "expected_router": ground_truth.get("expected_router") or {},
                "expected_event": ground_truth.get("expected_event"),
                "expects_no_actionable_findings": bool(ground_truth.get("expects_no_actionable_findings")),
                "evaluation": asdict(evaluation),
                "series": _series_for_plot(scenario_dir / "dataset.csv"),
            }
        )
    return {
        "scenarios": scenarios,
        "counts": _status_counts(item["evaluation"]["status"] for item in scenarios),
        "executable_analyzers": _executable_router_analyzers(),
    }


def run_behavior_suite(raw_dir: Path) -> dict[str, Any]:
    scenarios = []
    for scenario_dir in discover_behavior_scenarios(SCENARIOS_ROOT):
        evaluation = behavior_benchmark.run_benchmark(scenario_dir, reports_dir=raw_dir)
        ground_truth = _load_yaml(scenario_dir / "ground_truth.yaml")
        scenarios.append(
            {
                "scenario": _scenario_metadata(scenario_dir, ground_truth),
                "expected_behavior_findings": ground_truth.get("expected_behavior_findings") or {},
                "evaluation": asdict(evaluation),
                "series": _series_for_plot(scenario_dir / "dataset.csv"),
            }
        )
    return {"scenarios": scenarios, "counts": _status_counts(item["evaluation"]["status"] for item in scenarios)}


def run_performance_suite(raw_dir: Path) -> dict[str, Any]:
    results = performance_benchmark.run_all()
    performance_benchmark.write_report(results, reports_dir=raw_dir)
    return {
        "datasets": [asdict(result) for result in results],
        "max_seconds_per_analyzer": performance_benchmark.MAX_SECONDS_PER_ANALYZER,
    }


def run_nab_suite(raw_dir: Path) -> dict[str, Any]:
    from benchmark.nab.run import run_nab_suite as run_nab

    return run_nab(raw_dir)


SUITES: dict[str, Callable[[Path], dict[str, Any]]] = {
    "router": run_router_suite,
    "behavior": run_behavior_suite,
    "performance": run_performance_suite,
    "nab": run_nab_suite,
}


def build_manifest(started_at: datetime) -> dict[str, Any]:
    return {
        "started_at": started_at.isoformat(timespec="seconds"),
        "git": _git_state(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu": _cpu_name(),
        "packages": {name: _package_version(name) for name in TRACKED_PACKAGES},
        "config_sha256": {path: _sha256(PROJECT_ROOT / path) for path in _config_paths()},
        "dataset_sha256": {
            str(path.relative_to(PROJECT_ROOT)): _sha256(path)
            for path in sorted(SCENARIOS_ROOT.glob("*/dataset.csv"))
        },
        "command": " ".join([Path(sys.executable).name, "-m", "benchmark.run_all", *sys.argv[1:]]),
    }


def accuracy_fingerprint(suites: dict[str, Any]) -> str:
    """SHA-256 over every suite's results with wall-clock timings stripped, so a rerun on the same
    commit and data reproduces the same value and a changed number is visible at a glance."""
    accuracy = {name: _strip_timings(result) for name, result in suites.items() if name != "performance"}
    performance = suites.get("performance")
    if performance:
        accuracy["performance_signal_counts"] = [
            {"dataset": item["dataset_label"], "signals": {row["analyzer_id"]: row["signal_count"] for row in item["analyzers"]}}
            for item in performance["datasets"]
        ]
    payload = json.dumps(accuracy, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def run(selected: list[str], out_dir: Path | None = None) -> Path:
    started_at = datetime.now(timezone.utc)
    manifest = build_manifest(started_at)
    short_sha = (manifest["git"].get("commit") or "nogit")[:8]
    out_dir = out_dir or RESULTS_ROOT / f"{started_at:%Y%m%dT%H%M%SZ}-{short_sha}"
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    suites: dict[str, Any] = {}
    for name in selected:
        print(f"Running {name} suite...", flush=True)
        suites[name] = SUITES[name](raw_dir)

    finished_at = datetime.now(timezone.utc)
    manifest["finished_at"] = finished_at.isoformat(timespec="seconds")
    manifest["duration_seconds_wall"] = round((finished_at - started_at).total_seconds(), 2)
    results = {
        "schema_version": SCHEMA_VERSION,
        "run_id": out_dir.name,
        "manifest": manifest,
        "fingerprint": accuracy_fingerprint(suites),
        "suites": suites,
    }
    (out_dir / "results.json").write_text(json.dumps(results, indent=2, default=_json_default), encoding="utf-8")

    from benchmark.report_html import write_report

    write_report(out_dir / "results.json")
    if out_dir.resolve().parent == RESULTS_ROOT.resolve():
        _point_latest(out_dir)
    return out_dir


def exit_code(results_path: Path) -> int:
    results = json.loads(results_path.read_text(encoding="utf-8"))
    for suite in results["suites"].values():
        counts = suite.get("counts") or {}
        if counts.get("FAIL") or counts.get("ERROR"):
            return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run every Ops Signals benchmark suite and write a local HTML evidence report")
    parser.add_argument(
        "--suites",
        default=",".join(SUITES),
        help=f"Comma-separated suites to run (default: all - {', '.join(SUITES)})",
    )
    parser.add_argument("--out-dir", type=Path, help="Write the snapshot here instead of benchmark/results/<timestamp>-<sha>/")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    selected = [name.strip() for name in args.suites.split(",") if name.strip()]
    unknown = [name for name in selected if name not in SUITES]
    if unknown:
        raise SystemExit(f"Unknown suite(s): {', '.join(unknown)}. Available: {', '.join(SUITES)}")
    out_dir = run(selected, args.out_dir)
    results = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
    print(f"\nFingerprint: {results['fingerprint']}")
    for name, suite in results["suites"].items():
        if suite.get("counts"):
            print(f"{name}: {', '.join(f'{status} {count}' for status, count in suite['counts'].items())}")
    print(f"Report: {out_dir / 'report.html'}")
    raise SystemExit(exit_code(out_dir / "results.json"))


def _scenario_metadata(scenario_dir: Path, ground_truth: dict[str, Any]) -> dict[str, Any]:
    scenario = ground_truth.get("scenario") or {}
    return {
        "id": str(scenario.get("id") or scenario_dir.name),
        "name": scenario.get("name") or scenario_dir.name,
        "description": " ".join(str(scenario.get("description") or "").split()),
        "notes": [" ".join(str(note).split()) for note in ground_truth.get("notes") or []],
        "path": str(scenario_dir.relative_to(PROJECT_ROOT)),
    }


def _series_for_plot(csv_path: Path) -> dict[str, list[list[Any]]]:
    """Bucket-averaged series per metric, for the report's charts - never used for grading."""
    if not csv_path.exists():
        return {}
    frame = pd.read_csv(csv_path)
    if not {"timestamp", "value"}.issubset(frame.columns):
        return {}
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["timestamp"])
    metric_column = "metric" if "metric" in frame.columns else None
    groups = frame.groupby(metric_column) if metric_column else [("value", frame)]
    series: dict[str, list[list[Any]]] = {}
    for metric, group in groups:
        group = group.sort_values("timestamp").reset_index(drop=True)
        bucket = max(1, -(-len(group) // SERIES_POINTS))
        grouped = group.groupby(group.index // bucket).agg(timestamp=("timestamp", "first"), value=("value", "mean"))
        series[str(metric)] = [[row.timestamp.isoformat(), round(float(row.value), 4)] for row in grouped.itertuples()]
    return series


def _executable_router_analyzers() -> list[str]:
    """Router analyzer ids with a real pipeline analyzer behind them. The rest can be recommended
    by the router but have nothing to run, and the report marks them so."""
    registered = {registration.analyzer_id for registration in load_registrations(DEFAULT_ANALYZER_REGISTRY_DIR)}
    router_ids = set(registered) | set(router_benchmark.ROUTER_TO_PIPELINE_ANALYZER_ID)
    return sorted(
        router_id for router_id in router_ids
        if router_benchmark.ROUTER_TO_PIPELINE_ANALYZER_ID.get(router_id, router_id) in registered
    )


def _status_counts(statuses) -> dict[str, int]:
    counts: dict[str, int] = {}
    for status in statuses:
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _strip_timings(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip_timings(item) for key, item in value.items() if key not in TIMING_KEYS}
    if isinstance(value, list):
        return [_strip_timings(item) for item in value]
    return value


def _git_state() -> dict[str, Any]:
    def git(*args: str) -> str | None:
        try:
            return subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    status = git("status", "--porcelain", "--untracked-files=no")
    return {
        "commit": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "commit_date": git("log", "-1", "--format=%cI"),
        "dirty": bool(status),
        "dirty_files": status.splitlines() if status else [],
    }


def _cpu_name() -> str:
    if sys.platform == "darwin":
        try:
            return subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            pass
    return platform.processor() or platform.machine()


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _config_paths() -> list[str]:
    paths = [path for path in CONFIG_FILES if (PROJECT_ROOT / path).exists()]
    for pattern in CONFIG_GLOBS:
        paths.extend(str(path.relative_to(PROJECT_ROOT)) for path in sorted(PROJECT_ROOT.glob(pattern)))
    return paths


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _point_latest(out_dir: Path) -> None:
    latest = RESULTS_ROOT / "latest"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(out_dir.resolve(), target_is_directory=True)
    except OSError:
        pass


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, set):
        return sorted(value)
    return str(value)


if __name__ == "__main__":
    main()
