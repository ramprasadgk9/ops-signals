"""Fetch the NAB corpus at a pinned commit into a gitignored cache.

Only NAB's data and label files are used by the suite; NAB's code runs only in the separate,
explicit official-score step (benchmark/nab/official_score.py). NAB is MIT-licensed as of the
pinned commit (numenta/NAB#408).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from benchmark.fetch import CACHE_DIR, ensure_checkout

NAB_REPOSITORY = "https://github.com/numenta/NAB.git"
NAB_COMMIT = "ea702d75cc2258d9d7dd35ca8e5e2539d71f3140"
NAB_CACHE_DIR = CACHE_DIR / "nab"


def ensure_nab(cache_dir: Path = NAB_CACHE_DIR, commit: str = NAB_COMMIT) -> Path:
    return ensure_checkout(NAB_REPOSITORY, commit, cache_dir, required=("data", "labels/combined_windows.json"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch the NAB corpus at the pinned commit")
    parser.add_argument("--cache-dir", type=Path, default=NAB_CACHE_DIR)
    args = parser.parse_args()
    print(ensure_nab(args.cache_dir))


if __name__ == "__main__":
    main()
