"""Fetch the NAB corpus at a pinned commit into a gitignored cache.

Only NAB's data and label files are used; none of NAB's code is imported or run by this harness.
NAB is MIT-licensed as of the pinned commit (numenta/NAB#408). The corpus is fetched rather than
vendored so this repository doesn't carry ~40 MB of third-party data.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from benchmark.router_benchmark import PROJECT_ROOT

NAB_REPOSITORY = "https://github.com/numenta/NAB.git"
NAB_COMMIT = "ea702d75cc2258d9d7dd35ca8e5e2539d71f3140"
NAB_CACHE_DIR = PROJECT_ROOT / "benchmark" / ".cache" / "nab"


class NabFetchError(RuntimeError):
    """Raised when the NAB corpus can't be fetched or checked out at the pinned commit."""


def ensure_nab(cache_dir: Path = NAB_CACHE_DIR, commit: str = NAB_COMMIT) -> Path:
    """Return a NAB checkout at exactly `commit`, cloning or updating the cache as needed."""
    if not (cache_dir / ".git").exists():
        cache_dir.parent.mkdir(parents=True, exist_ok=True)
        _git(cache_dir.parent, "clone", "--quiet", NAB_REPOSITORY, cache_dir.name)
    if _head(cache_dir) != commit:
        try:
            _git(cache_dir, "checkout", "--quiet", commit)
        except NabFetchError:
            _git(cache_dir, "fetch", "--quiet", "origin")
            _git(cache_dir, "checkout", "--quiet", commit)
    head = _head(cache_dir)
    if head != commit:
        raise NabFetchError(f"NAB checkout is at {head}, expected pinned commit {commit}")
    for required in ("data", "labels/combined_windows.json"):
        if not (cache_dir / required).exists():
            raise NabFetchError(f"NAB checkout is missing {required}")
    return cache_dir


def _head(cache_dir: Path) -> str:
    return _git(cache_dir, "rev-parse", "HEAD").strip()


def _git(cwd: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise NabFetchError(f"git {' '.join(args)} failed: {detail.strip()}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch the NAB corpus at the pinned commit")
    parser.add_argument("--cache-dir", type=Path, default=NAB_CACHE_DIR)
    args = parser.parse_args()
    print(ensure_nab(args.cache_dir))


if __name__ == "__main__":
    main()
