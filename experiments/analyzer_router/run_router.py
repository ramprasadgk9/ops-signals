from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
import sys

import pandas as pd

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
    from experiments.analyzer_router.config_loader import build_request, load_experiment_config
    from experiments.analyzer_router.router import UniversalTimeSeriesRouter
else:
    from .config_loader import build_request, load_experiment_config
    from .router import UniversalTimeSeriesRouter


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the experimental Universal Time-Series Analyzer Router.")
    parser.add_argument("--config", default="experiments/analyzer_router/experiment_config.yaml")
    args = parser.parse_args()
    config = load_experiment_config(args.config)
    request = build_request(config)
    router = UniversalTimeSeriesRouter(
        registry_path=config.get("registry_path"),
        config={"data_validation": config.get("data_validation", {})},
    )
    result = router.route(request)
    print(result.summary)
    print(f"Validation status: {result.validation.status}")
    print(f"Exported JSON: {result.export_path}")
    print(json.dumps({
        "analyzers": [asdict(decision) for decision in result.analyzers],
        "profile": asdict(result.profile),
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
