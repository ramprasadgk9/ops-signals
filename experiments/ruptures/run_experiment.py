from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.config import load_config  # noqa: E402
from src.experiment import run_experiment  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a Ruptures experiment against a CSV time-series dataset.")
    parser.add_argument("--config", required=True, help="Path to the YAML experiment configuration.")
    args = parser.parse_args()
    config = load_config(Path(args.config))
    run_experiment(config)


if __name__ == "__main__":
    main()
