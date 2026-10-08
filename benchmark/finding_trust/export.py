"""Write the tested numbers a finding-trust run measured into config/finding_trust.yaml, the file the
backend reads (backend/app/services/finding_trust.py). Numbers shown to users always come from a
recorded run, never typed by hand.

    .venv/bin/python -m benchmark.finding_trust.export benchmark/results/<run>/results.json

Benchmark groups map onto the product's trust groups:

| Benchmark group (type, agreement) | Trust group |
| --- | --- |
| New level or steady trend, 2+ analyzers | level_change_agree |
| New level or steady trend, 1 analyzer | level_change_single |
| Short spike or dip (any agreement) | spike |

RCAEval (microservice faults) is the primary source; NAB is kept alongside for transparency.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from benchmark.finding_trust import events as ev
from benchmark.router_benchmark import PROJECT_ROOT

TARGET = PROJECT_ROOT / "config" / "finding_trust.yaml"

_GROUPS = {
    "level_change_agree": [("behavior_change", "2+ analyzers")],
    "level_change_single": [("behavior_change", "1 analyzer")],
    "spike": [("unusual_activity", "1 analyzer"), ("unusual_activity", "2+ analyzers")],
}

_HEADER = """\
# Tested numbers behind the trust shown on each finding (backend/app/services/finding_trust.py).
# Generated from a benchmark run - don't edit by hand; rerun:
#   .venv/bin/python -m benchmark.finding_trust.run --nab-category realAWSCloudwatch \\
#       --rcaeval-systems RE1-OB,RE1-SS,RE1-TT --rcaeval-repeats all
#   .venv/bin/python -m benchmark.finding_trust.export benchmark/results/<run>/results.json
# real: share of findings that fell inside a real, marked problem. random: what an alert at a
# random moment would score on the same data. checked: how many findings it's based on.
"""


def build(payload: dict[str, Any], run_name: str) -> dict[str, Any]:
    primary = payload.get("step3")
    secondary = payload.get("step2")
    groups: dict[str, Any] = {}
    for group, keys in _GROUPS.items():
        entry: dict[str, Any] = {}
        tested = _combined(primary, keys)
        if tested:
            entry["tested"] = {**tested, "dataset": "RCAEval RE1", "data_kind": "microservice"}
        also = _combined(secondary, keys)
        if also:
            entry["also_tested"] = [{**also, "dataset": "NAB cloud servers", "data_kind": "cloud server"}]
        groups[group] = entry
    return {
        "source": {"run": run_name, "measured_at": str(payload.get("started_at", ""))[:10], "commit": payload.get("commit")},
        "min_checked": ev.MIN_GROUP,
        "groups": groups,
    }


def _combined(step: dict[str, Any] | None, keys: list[tuple[str, str]]) -> dict[str, Any] | None:
    if not step:
        return None
    rows = [
        row for row in step["tables"]["type, agreement"]
        if (row["group"]["finding_type"], row["group"]["agreement"]) in keys
    ]
    checked = sum(row["n"] for row in rows)
    if not checked:
        return None
    real = sum(row["real"] for row in rows)
    chance = sum((row.get("chance") or 0) * row["n"] for row in rows) / checked
    return {"real": round(real / checked, 3), "checked": checked, "random": round(chance, 3)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Write config/finding_trust.yaml from a finding-trust run")
    parser.add_argument("results", type=Path)
    parser.add_argument("--target", type=Path, default=TARGET)
    args = parser.parse_args()
    payload = json.loads(args.results.read_text(encoding="utf-8"))
    content = build(payload, args.results.parent.name)
    args.target.write_text(_HEADER + yaml.safe_dump(content, sort_keys=False), encoding="utf-8")
    print(args.target)


if __name__ == "__main__":
    main()
