"""Measure how often each kind of finding was real, and write a local report.

    .venv/bin/python -m benchmark.finding_trust.run                 # steps 1-3 on the small samples
    .venv/bin/python -m benchmark.finding_trust.run --steps 1       # only re-read a saved full run
    .venv/bin/python -m benchmark.finding_trust.run --nab-category realAWSCloudwatch \
        --rcaeval-systems RE1-OB,RE1-SS,RE1-TT --rcaeval-repeats all  # cloud servers + all of RE1

Step 1 reads a saved full benchmark run (nothing reruns): each analyzer's alert precision, and
where the product's live alerts fell against NAB's marked incidents.
Step 2 replays NAB series - the dev and check samples in benchmark/samples.py, or every series of
one NAB category - and labels every finding event with its type, agreeing analyzers and importance
(events.py).
Step 3 replays RCAEval RE1 cases (rcaeval.py): faults injected into microservice demos at a known
moment, so it measures how fast a finding follows a real fault and how
often findings appear while nothing is wrong.

Output: benchmark/results/<UTC timestamp>-<sha>-finding-trust/{results.json,report.html},
gitignored like every benchmark snapshot.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from benchmark import harness
from benchmark.finding_trust import events as ev
from benchmark.finding_trust import rcaeval
from benchmark.nab import detector, metrics
from benchmark.nab.fetch import ensure_nab
from benchmark.router_benchmark import PROJECT_ROOT
from benchmark.samples import SAMPLES

RESULTS_DIR = PROJECT_ROOT / "benchmark" / "results"
# RCAEval: a finding within this long after the injection counts as caught; later ones aren't scored.
RCAEVAL_INCIDENT_MINUTES = 10


# ---------------------------------------------------------------- step 1: a saved full run


def latest_full_run(results_dir: Path = RESULTS_DIR) -> Path | None:
    runs = sorted(p for p in results_dir.glob("*-full") if (p / "results.json").exists())
    return runs[-1] if runs else None


def step1_saved(run_dir: Path, category: str | None = None) -> dict[str, Any]:
    nab = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))["suites"]["nab"]
    labels = json.loads((ensure_nab() / "labels" / "combined_labels.json").read_text(encoding="utf-8"))
    threshold = str(metrics.HEADLINE_THRESHOLD)

    analyzers = []
    for analyzer, by_threshold in sorted(nab.get("analyzers", {}).items()):
        counts = by_threshold[threshold]
        analyzers.append(
            {
                "analyzer": analyzer,
                "alerts": counts["alarms"],
                "real": counts["alarms_in_windows"],
                "real_rate": counts["alarm_precision"],
                "real_rate_low": ev.wilson_low(counts["alarms_in_windows"], counts["alarms"]),
                "incidents_caught": counts["detected_windows"],
                "incidents": counts["windows"],
            }
        )

    alerts: list[ev.FindingEvent] = []
    for series in nab["series"]:
        if category and series["category"] != category:
            continue
        windows = [(_epoch(start), _epoch(end)) for start, end in series["windows"]]
        marks = [_epoch(mark) for mark in labels.get(series["series"], [])]
        for moment, score in series["modes"]["replay"]["alarm_times"]:
            if score < metrics.HEADLINE_THRESHOLD:
                continue
            alert = ev.FindingEvent(row=0, finding_type="any", analyzers=(), importance=0.0, confidence=score, source={"series": series["series"]})
            alert.outcome, lead = ev.label(_epoch(moment), windows, marks, scored_from=_epoch(series["probation_end"]))
            alert.lead = lead / 60 if lead is not None else None
            alerts.append(alert)
    return {
        "run": run_dir.name,
        "category": category,
        "series_count": sum(1 for series in nab["series"] if not category or series["category"] == category),
        "commit": nab.get("nab", {}).get("commit"),
        "threshold": metrics.HEADLINE_THRESHOLD,
        "analyzers": analyzers,
        "live_alerts": ev.overall(alerts),
    }


def _epoch(value: str) -> float:
    stamp = pd.Timestamp(value)
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    return stamp.timestamp()


# ---------------------------------------------------------------- step 2: NAB sample, by finding


def nab_sample(category: str | None = None) -> list[str]:
    if category:
        windows = json.loads((ensure_nab() / "labels" / "combined_windows.json").read_text(encoding="utf-8"))
        return sorted(name for name in windows if name.split("/")[0] == category)
    return sorted({*SAMPLES["dev"]["nab"], *SAMPLES["check"]["nab"]})


def nab_series_events(name: str) -> dict[str, Any]:
    logging.disable(logging.WARNING)
    harness.warm_up()
    nab_dir = ensure_nab()
    windows = json.loads((nab_dir / "labels" / "combined_windows.json").read_text(encoding="utf-8"))[name]
    labels = json.loads((nab_dir / "labels" / "combined_labels.json").read_text(encoding="utf-8")).get(name, [])
    frame = detector.load_series(nab_dir / "data" / name)
    interval = detector.median_interval_minutes(frame)
    started = time.perf_counter()
    found, runs, errors = ev.replay_events(
        detector.build_pipeline(interval),
        frame,
        step=detector.REPLAY_STEP,
        window=detector.REPLAY_WINDOW,
        horizon=detector.REPLAY_NEW_EVENT_HORIZON,
        min_history=detector.REPLAY_MIN_HISTORY,
    )
    times = frame["timestamp"].dt.tz_convert(None).to_numpy()
    rows = metrics.window_rows(times, windows)
    marks = [row for row in (ev.row_at_or_after(times, pd.Timestamp(mark)) for mark in labels) if row is not None]
    scored_from = max(metrics.probation_rows(len(frame)), min(detector.REPLAY_MIN_HISTORY, len(frame) - 1))
    chance = ev.chance_rate([(start, end + 1) for start, end in rows], scored_from, len(frame))
    for event in found:
        event.outcome, lead = ev.label(event.row, rows, marks, scored_from=metrics.probation_rows(len(frame)))
        event.lead = lead * interval if lead is not None else None
        event.source = {"dataset": "nab", "series": name, "chance": chance}
    return {
        "series": name,
        "rows": len(frame),
        "interval_minutes": interval,
        "incidents": len(rows),
        "runs": runs,
        "errors": errors,
        "seconds": round(time.perf_counter() - started, 1),
        "events": [event.to_record() for event in found],
    }


# ---------------------------------------------------------------- step 3: RCAEval injected faults


def rcaeval_metric_events(case_dir: str, kind: str) -> dict[str, Any]:
    logging.disable(logging.WARNING)
    harness.warm_up()
    case = Path(case_dir)
    system, service, fault = rcaeval.describe(case)
    column = rcaeval.column_for(system, service, kind)
    record: dict[str, Any] = {
        "case": f"{system}/{case.parent.name}/{case.name}", "system": system, "service": service, "fault": fault, "kind": kind, "metric": column,
    }
    loaded = rcaeval.load_metric(case, column)
    if loaded is None:
        return {**record, "missing": True, "events": []}
    frame, injected = loaded
    pipeline = harness.build_pipeline(1, column)
    pipeline.config.input.interval = f"{rcaeval.INTERVAL_SECONDS}s"
    found, runs, errors = ev.replay_events(
        pipeline,
        frame,
        step=rcaeval.REPLAY_STEP,
        window=rcaeval.REPLAY_WINDOW,
        horizon=rcaeval.REPLAY_NEW_EVENT_HORIZON,
        min_history=rcaeval.REPLAY_MIN_HISTORY,
    )
    times = frame["timestamp"].dt.tz_convert(None).to_numpy()
    inject_row = ev.row_at_or_after(times, injected)
    incident_rows = RCAEVAL_INCIDENT_MINUTES * 60 // rcaeval.INTERVAL_SECONDS
    minutes_per_row = rcaeval.INTERVAL_SECONDS / 60
    first_scored = min(rcaeval.REPLAY_MIN_HISTORY, len(frame) - 1)
    scored_until = min(inject_row + incident_rows, len(frame) - 1)
    chance = ev.chance_rate([(inject_row, scored_until)], first_scored, scored_until)
    for event in found:
        # Nothing precedes an injected fault, so nothing before it can be an early warning.
        event.outcome, lead = ev.label(
            event.row, [(inject_row, inject_row + incident_rows)], [inject_row], scored_until=inject_row + incident_rows, before=0
        )
        event.lead = lead * minutes_per_row if lead is not None else None
        event.source = {"dataset": "rcaeval", "case": record["case"], "metric": column, "chance": chance}
    return {
        **record,
        "runs": runs,
        "errors": errors,
        "normal_minutes": max(0, inject_row - first_scored) * minutes_per_row,
        "incident_minutes": max(0, scored_until - inject_row) * minutes_per_row,
        "events": [event.to_record() for event in found],
    }


def summarize_rcaeval(per_metric: list[dict[str, Any]]) -> dict[str, Any]:
    by_case: dict[str, list[dict[str, Any]]] = {}
    for item in per_metric:
        by_case.setdefault(item["case"], []).append(item)
    case_rows = []
    for case, items in sorted(by_case.items()):
        caught = [e for item in items for e in item["events"] if e["outcome"] == ev.IN_INCIDENT]
        first = min(caught, key=lambda e: e["row"]) if caught else None
        case_rows.append(
            {
                "case": case,
                "system": items[0]["system"],
                "service": items[0]["service"],
                "fault": items[0]["fault"],
                "caught": bool(caught),
                "delay_minutes": -first["lead"] if first and first["lead"] is not None else None,
                "caught_on": next((item["metric"] for item in items if first in item["events"]), None),
                "false_alarms": sum(1 for item in items for e in item["events"] if e["outcome"] == ev.FALSE_ALARM),
            }
        )
    by_fault: dict[str, list[dict[str, Any]]] = {}
    for row in case_rows:
        by_fault.setdefault(row["fault"], []).append(row)
    fault_rows = [
        {
            "fault": fault,
            "cases": len(rows),
            "caught": sum(row["caught"] for row in rows),
            "median_delay_minutes": _median([row["delay_minutes"] for row in rows if row["delay_minutes"] is not None]),
        }
        for fault, rows in sorted(by_fault.items())
    ]
    normal_hours = sum(item.get("normal_minutes", 0) for item in per_metric) / 60
    false_alarms = sum(row["false_alarms"] for row in case_rows)
    system_rows = []
    for system in sorted({row["system"] for row in case_rows}):
        rows = [row for row in case_rows if row["system"] == system]
        hours = sum(item.get("normal_minutes", 0) for item in per_metric if item["system"] == system) / 60
        alarms = sum(row["false_alarms"] for row in rows)
        system_rows.append(
            {
                "system": system,
                "cases": len(rows),
                "caught": sum(row["caught"] for row in rows),
                "median_delay_minutes": _median([row["delay_minutes"] for row in rows if row["delay_minutes"] is not None]),
                "false_alarms": alarms,
                "metric_hours_normal": round(hours, 2),
                "false_alarms_per_metric_hour": round(alarms / hours, 2) if hours else None,
            }
        )
    return {
        "cases": case_rows,
        "faults": fault_rows,
        "systems": system_rows,
        "missing_metrics": sorted({item["metric"] for item in per_metric if item.get("missing")}),
        "metric_hours_normal": round(normal_hours, 2),
        "false_alarms": false_alarms,
        "false_alarms_per_metric_hour": round(false_alarms / normal_hours, 2) if normal_hours else None,
    }


def _median(values: list[float]) -> float | None:
    values = sorted(values)
    if not values:
        return None
    middle = len(values) // 2
    return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2


# ---------------------------------------------------------------- shared


def _events(items: list[dict[str, Any]]) -> list[ev.FindingEvent]:
    found = []
    for item in items:
        for record in item["events"]:
            event = ev.FindingEvent(
                row=record["row"],
                finding_type=record["finding_type"],
                analyzers=tuple(record["analyzers"]),
                importance=record["importance"],
                confidence=record["confidence"],
                outcome=record["outcome"],
                lead=record["lead"],
                source=record["source"],
            )
            found.append(event)
    return found


def _rates(found: list[ev.FindingEvent]) -> dict[str, Any]:
    return {"overall": ev.overall(found), "tables": ev.rate_tables(found)}


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "nogit"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--steps", default="1,2,3", help="comma-separated: 1 saved run, 2 NAB sample, 3 RCAEval")
    parser.add_argument("--saved", type=Path, help="saved full run folder for step 1 (default: newest *-full)")
    parser.add_argument("--nab-category", help="step 1 and 2 on every series of one NAB category, e.g. realAWSCloudwatch")
    parser.add_argument("--rcaeval-systems", default="RE1-OB", help="comma-separated: RE1-OB, RE1-SS, RE1-TT")
    parser.add_argument("--rcaeval-repeats", default="1", help="which repeats per service and fault: e.g. 1, or 1,2,3,4,5, or all")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = parser.parse_args()
    steps = {step.strip() for step in args.steps.split(",")}

    started = time.perf_counter()
    payload: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": _git_sha(),
        "min_group": ev.MIN_GROUP,
    }
    if "1" in steps:
        saved = args.saved or latest_full_run()
        payload["step1"] = step1_saved(saved, args.nab_category) if saved else {"missing": "no saved *-full run found"}
        print("step 1 done")
    if "2" in steps:
        series = nab_sample(args.nab_category)
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            items = list(pool.map(nab_series_events, series))
        payload["step2"] = {"category": args.nab_category, "series": [{k: v for k, v in item.items() if k != "events"} for item in items], **_rates(_events(items)), "events": [e for item in items for e in item["events"]]}
        print(f"step 2 done: {len(series)} NAB series")
    if "3" in steps:
        systems = [system.strip() for system in args.rcaeval_systems.split(",")]
        repeats = None if args.rcaeval_repeats == "all" else tuple(args.rcaeval_repeats.split(","))
        case_dirs = [case for system in systems for case in rcaeval.cases(rcaeval.ensure_rcaeval(system), repeats)]
        jobs = [(str(case), kind) for case in case_dirs for kind in rcaeval.METRIC_KINDS]
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            items = list(pool.map(rcaeval_metric_events, *zip(*jobs)))
        payload["step3"] = {
            "system": ", ".join(systems),
            "settings": {
                "interval_seconds": rcaeval.INTERVAL_SECONDS,
                "run_every_seconds": rcaeval.REPLAY_STEP * rcaeval.INTERVAL_SECONDS,
                "history_minutes": rcaeval.REPLAY_MIN_HISTORY * rcaeval.INTERVAL_SECONDS / 60,
            },
            "incident_minutes": RCAEVAL_INCIDENT_MINUTES,
            **summarize_rcaeval(items),
            **_rates(_events(items)),
            "events": [e for item in items for e in item["events"]],
        }
        print(f"step 3 done: {len(case_dirs)} RCAEval cases")
    payload["wall_seconds"] = round(time.perf_counter() - started, 1)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS_DIR / f"{stamp}-{payload['commit']}-finding-trust"
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    from benchmark.finding_trust.report import write_report

    print(write_report(payload, out / "report.html"))


if __name__ == "__main__":
    main()
