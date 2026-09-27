"""Score a snapshot's NAB results with NAB's own, unmodified scorer and add them to its report.

    .venv/bin/python -m benchmark.nab.official_score benchmark/results/latest

This is a separate, explicit step because it runs NAB's code (run.py --optimize --score
--normalize), which this project otherwise never executes. NAB's scorer was written for pandas
0.23 and fails on pandas 3, so it runs in its own environment, never the project's:

    /usr/bin/python3 -m venv benchmark/.cache/nab-venv
    benchmark/.cache/nab-venv/bin/pip install "pandas==1.5.3" "numpy==1.26.4" "python-dateutil==2.9.0.post0" simplejson

(macOS's /usr/bin/python3 is used because Homebrew's 3.11 and 3.12 can fail to load pyexpat, which
pip needs. Any Python 3.9-3.11 with those packages works; pass it with --python.)

Numenta's own published detector is re-scored in the same run as a check that the environment
reproduces NAB's published numbers. The outputs land in <snapshot>/raw/nab_official/:
final_results.json, the per-profile score CSVs, NAB's published scoreboard at the pinned commit,
and the scorer's console output. The report is then rebuilt. The NAB checkout is restored to the
pinned commit afterwards, because the scorer rewrites files inside it.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from benchmark.nab.fetch import NAB_COMMIT, ensure_nab
from benchmark.nab.run import DETECTOR_NAMES
from benchmark.router_benchmark import PROJECT_ROOT
from benchmark.report_html import write_report

NAB_VENV_PYTHON = PROJECT_ROOT / "benchmark" / ".cache" / "nab-venv" / "bin" / "python"
REFERENCE_DETECTOR = "numenta"
OFFICIAL_DIR = Path("raw") / "nab_official"


class OfficialScoreError(RuntimeError):
    """Raised when NAB's scorer can't be run on a snapshot."""


def score_snapshot(snapshot: Path, python: Path = NAB_VENV_PYTHON) -> Path:
    snapshot = snapshot.resolve()
    staged = snapshot / "raw" / "nab_results"
    if not staged.is_dir():
        raise OfficialScoreError(f"{staged} not found - run the nab suite into this snapshot first")
    if not python.exists():
        raise OfficialScoreError(f"No scorer environment at {python}; see this module's docstring for setup")

    nab_dir = ensure_nab()
    detectors = list(DETECTOR_NAMES.values())
    out_dir = snapshot / OFFICIAL_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "published_final_results.json").write_text(
        _git(nab_dir, "show", f"{NAB_COMMIT}:results/final_results.json"), encoding="utf-8"
    )
    try:
        for detector in detectors:
            target = nab_dir / "results" / detector
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(staged / detector, target)
        completed = subprocess.run(
            [str(python), "run.py", "-d", REFERENCE_DETECTOR, *detectors, "--optimize", "--score", "--normalize", "--skipConfirmation"],
            cwd=nab_dir,
            capture_output=True,
            text=True,
        )
        (out_dir / "scorer_output.txt").write_text(completed.stdout + completed.stderr, encoding="utf-8")
        if completed.returncode != 0 or "Final scores have been written" not in completed.stdout:
            raise OfficialScoreError(f"NAB's scorer failed; see {out_dir / 'scorer_output.txt'}")
        shutil.copy2(nab_dir / "results" / "final_results.json", out_dir / "final_results.json")
        for detector in [REFERENCE_DETECTOR, *detectors]:
            for scores in (nab_dir / "results" / detector).glob(f"{detector}_*_scores.csv"):
                shutil.copy2(scores, out_dir / scores.name)
    finally:
        _restore(nab_dir, detectors)

    return write_report(snapshot / "results.json")


def _restore(nab_dir: Path, detectors: list[str]) -> None:
    _git(nab_dir, "checkout", "--quiet", "--", ".")
    for detector in detectors:
        shutil.rmtree(nab_dir / "results" / detector, ignore_errors=True)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def main() -> None:
    parser = argparse.ArgumentParser(description="Score a snapshot's NAB results with NAB's own scorer")
    parser.add_argument("snapshot", type=Path, help="A benchmark/results/<run>/ folder that includes the nab suite")
    parser.add_argument("--python", type=Path, default=NAB_VENV_PYTHON, help="Python with NAB's scorer dependencies")
    args = parser.parse_args()
    print(score_snapshot(args.snapshot, args.python))


if __name__ == "__main__":
    main()
