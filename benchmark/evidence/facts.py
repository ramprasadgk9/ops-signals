"""Every number the evidence reports use, computed from one benchmark snapshot.

The reports read only what build_facts returns, so every figure and every
claim traces back to the snapshot's results.json, its raw NAB result files and, when present, NAB's
official scores. A section whose suite didn't run, or ran without the methods it compares, is None,
and the reports leave it out rather than fill it from somewhere else.

Confidence intervals are percentile bootstraps over series (machines for SMD), BOOTSTRAP_SAMPLES
resamples with a fixed seed, so the same snapshot always gives the same intervals. Paired intervals
resample the same series for both methods, which is what says whether a gap between two methods on
the same data is larger than the series-to-series variation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from benchmark.methods import ALL_ANALYZERS, LABELS, ROUTER_PICKS, STATIC_THRESHOLD, ZSCORE_ONLY
from benchmark.nab import metrics
from benchmark.nab.alert_budget import alert_gap, best_under, group_alerts
from benchmark.report_html import load_official_nab, routing_comparison
from benchmark.scorecard import ROUTER_BAR, analyzer_scorecard, router_choices

BOOTSTRAP_SAMPLES = 2000
SEED = 2026
HEADLINE = str(metrics.HEADLINE_THRESHOLD)
NAB_BASELINES = (ALL_ANALYZERS, ZSCORE_ONLY, STATIC_THRESHOLD)
# NAB-format result folders, as benchmark/nab/run.py writes them.
NAB_FOLDERS = {"live": "opsSignalsReplay", "batch": "opsSignalsBatch", ALL_ANALYZERS: "opsSignalsAllAnalyzers",
               ZSCORE_ONLY: "zscoreOnly", STATIC_THRESHOLD: "staticThreshold"}


def build_facts(snapshot: Path) -> dict[str, Any]:
    snapshot = snapshot.resolve()
    results = json.loads((snapshot / "results.json").read_text(encoding="utf-8"))
    suites = results.get("suites", {})
    official = load_official_nab(snapshot / "raw" / "nab_official")
    return {
        "run": _run(results),
        "nab": _nab(suites.get("nab"), official, snapshot / "raw" / "nab_results"),
        "ucr": _ucr(suites.get("ucr")),
        "tcpd": _tcpd(suites.get("tcpd")),
        "smd": _smd(suites.get("smd")),
        "behavior": _behavior(suites.get("behavior")),
        "router": _router(suites.get("router")),
        "analyzers": analyzer_scorecard(suites) if suites.get("analyzers") else [],
        "choices": [{**c, "bar": ROUTER_BAR} for c in router_choices(suites)],
        "routing": [_routing_row(row) for row in routing_comparison(suites, official)],
    }


# --- statistics -------------------------------------------------------------------------------


def _bootstrap(counts: np.ndarray, statistic, samples: int = BOOTSTRAP_SAMPLES) -> tuple[float, float] | None:
    """95% percentile interval of statistic(counts[resampled rows]); counts has one row per series."""
    if len(counts) < 2:
        return None
    rng = np.random.default_rng(SEED)
    picks = rng.integers(0, len(counts), size=(samples, len(counts)))
    values = np.array([statistic(counts[p]) for p in picks])
    low, high = np.percentile(values, [2.5, 97.5])
    return float(low), float(high)


def _f1_from(detected, windows, in_windows, alarms) -> float:
    recall = detected / windows if windows else 0.0
    precision = in_windows / alarms if alarms else 0.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _nab_f1(rows: np.ndarray) -> float:
    detected, windows, in_windows, alarms = rows.sum(axis=0)
    return _f1_from(detected, windows, in_windows, alarms)


# --- run --------------------------------------------------------------------------------------


def _run(results: dict[str, Any]) -> dict[str, Any]:
    manifest = results.get("manifest", {})
    git = manifest.get("git", {})
    return {
        "run_id": results.get("run_id"),
        "fingerprint": results.get("fingerprint"),
        "commit": git.get("commit"),
        "commit_date": git.get("commit_date"),
        "dirty_files": git.get("dirty_files") or [],
        "started_at": manifest.get("started_at"),
        "finished_at": manifest.get("finished_at"),
        "hours": (manifest.get("duration_seconds_wall") or 0) / 3600,
        "command": manifest.get("command"),
        "sample": manifest.get("sample"),
        "skipped_methods": manifest.get("skipped_methods") or [],
        "python": manifest.get("python"),
        "platform": manifest.get("platform"),
        "cpu": manifest.get("cpu"),
        "packages": manifest.get("packages") or {},
        "config_sha256": manifest.get("config_sha256") or {},
        "dataset_sha256": manifest.get("dataset_sha256") or {},
        "suites": sorted(results.get("suites", {})),
    }


# --- NAB --------------------------------------------------------------------------------------


def _nab(nab: dict[str, Any] | None, official: dict[str, Any] | None, raw: Path) -> dict[str, Any] | None:
    if not nab:
        return None
    windows = sum(len(s["windows"]) for s in nab["series"])
    methods: dict[str, dict[str, Any]] = {}
    per_series: dict[str, np.ndarray] = {}
    for method in ("live", "batch", *NAB_BASELINES):
        if method in ("live", "batch"):
            overall = nab["overall"]["replay" if method == "live" else "batch"][HEADLINE]
            rows = [s["modes"]["replay" if method == "live" else "batch"]["headline"] for s in nab["series"]]
        elif method in nab["comparison"]:
            overall = nab["comparison"][method]["overall"][HEADLINE]
            rows = [s["baselines"][method]["headline"] for s in nab["series"]]
        else:
            continue
        per_series[method] = np.array([[r["detected_windows"], r["windows"], r["alarms_in_windows"], r["alarms"]] for r in rows], dtype=float)
        methods[method] = {
            "label": _nab_label(method),
            "caught": overall["detected_windows"],
            "windows": overall["windows"],
            "flags": overall["alarms"],
            "false_flags": overall["false_alarms"],
            "precision": overall["alarm_precision"],
            "recall": overall["window_recall"],
            "f1": overall["f1"],
            "f1_ci": _bootstrap(per_series[method], _nab_f1),
            "alerts": _nab_alerts(raw / NAB_FOLDERS[method]),
            "cost": (nab["comparison"].get(ROUTER_PICKS if method == "live" else method) or {}).get("cost"),
        }
    paired = {}
    for baseline in NAB_BASELINES:
        if baseline in per_series:
            both = np.hstack([per_series["live"], per_series[baseline]])
            paired[baseline] = _bootstrap(both, lambda r: _nab_f1(r[:, :4]) - _nab_f1(r[:, 4:]))
    budget = nab.get("alert_budget")
    return {
        "settings": nab["settings"],
        "series": len(nab["series"]),
        "windows": windows,
        "categories": sorted({s["series"].split("/")[0] for s in nab["series"]}),
        "methods": methods,
        "paired_f1_vs": paired,
        "official": _nab_official(nab, official),
        "budget": _budget_facts(budget) if budget else None,
        "category_gaps": _category_gaps(nab),
    }


def _nab_label(method: str) -> str:
    return {"live": "Ops Signals, live alerts", "batch": "Ops Signals, batch review"}.get(method) or LABELS[method]


def _nab_alerts(folder: Path) -> dict[str, int] | None:
    """Alerts at the usual setting counted as a person sees them (benchmark/nab/alert_budget.py's
    grouping), split into real (touching a labelled window) and false."""
    files = sorted(folder.glob("*/*.csv"))
    if not files:
        return None
    alerts = real = 0
    for path in files:
        frame = pd.read_csv(path, parse_dates=["timestamp"])
        timestamps = frame["timestamp"].to_numpy()
        rows = np.nonzero(frame["anomaly_score"].to_numpy() >= metrics.HEADLINE_THRESHOLD)[0]
        rows = rows[rows >= metrics.probation_rows(len(frame))]
        labels = frame["label"].to_numpy()
        for group in group_alerts(timestamps, rows, alert_gap(timestamps)):
            alerts += 1
            real += bool(labels[group].any())
    return {"alerts": alerts, "real": real, "false": alerts - real}


def _nab_official(nab: dict[str, Any], official: dict[str, Any] | None) -> dict[str, Any] | None:
    if not official or not official.get("final"):
        return None
    ours = {nab["detector_names"]["replay"]: "Ops Signals, live alerts", nab["detector_names"]["batch"]: "Ops Signals, batch review"}
    ours.update({name: LABELS[method] for method, name in nab["baseline_detector_names"].items()})
    board = []
    for detector, scores in official["final"].items():
        board.append({"detector": detector, "label": ours.get(detector, detector), "ours": detector in ours,
                      "standard": scores.get("standard"), "low_fp": scores.get("reward_low_FP_rate"), "low_fn": scores.get("reward_low_FN_rate")})
    board.sort(key=lambda row: -(row["standard"] or 0))
    return {"board": board, "published": [row for row in board if not row["ours"]]}


def _budget_facts(budget: dict[str, Any]) -> dict[str, Any]:
    """The equal-alert-budget curves plus the two comparisons the reports state: how often each Ops
    Signals mode beats the best threshold at the same budget, and each mode's usual setting against
    the best threshold allowed no more alerts ("no tuning needed")."""
    threshold = budget["curves"].get("static_threshold")
    tallies, untuned = {}, {}
    for mode in ("live", "batch"):
        if mode not in budget["curves"] or not threshold:
            continue
        pairs = [(r["caught"][mode], r["caught"]["static_threshold"]) for r in budget["budgets"]
                 if r["caught"][mode] is not None and r["caught"]["static_threshold"] is not None]
        tallies[mode] = {"more": sum(a > b for a, b in pairs), "same": sum(a == b for a, b in pairs),
                         "fewer": sum(a < b for a, b in pairs), "budgets": len(pairs)}
        usual = budget["usual"][mode]
        fits = [p for p in threshold if p["alerts"] <= usual["alerts"]]
        best = max(fits, key=lambda p: p["caught"]) if fits else None
        untuned[mode] = {"usual": usual, "best_threshold": best}
    return {**budget, "tallies": tallies, "untuned": untuned}


def _category_gaps(nab: dict[str, Any]) -> list[dict[str, Any]]:
    """Per NAB category, windows the threshold catches that live Ops Signals misses and the reverse."""
    if STATIC_THRESHOLD not in nab["comparison"]:
        return []
    gaps: dict[str, list[int]] = {}
    for s in nab["series"]:
        ours = s["modes"]["replay"]["headline"]["detected_windows"]
        theirs = s["baselines"][STATIC_THRESHOLD]["headline"]["detected_windows"]
        entry = gaps.setdefault(s["series"].split("/")[0], [0, 0, 0])
        entry[0] += max(0, theirs - ours)
        entry[1] += max(0, ours - theirs)
        entry[2] += s["modes"]["replay"]["headline"]["windows"]
    return [{"category": c, "threshold_only": a, "ours_only": b, "windows": w} for c, (a, b, w) in sorted(gaps.items())]


# --- UCR --------------------------------------------------------------------------------------


def _ucr(ucr: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ucr:
        return None
    overall = ucr["summary"]["overall"]
    series = ucr["series"]
    correct = {m: np.array([bool((s["methods"].get(m) or {}).get("correct")) for s in series])
               for m in ("product", "static_threshold", "anomaly_zscore", "all_analyzers", "pyod_outlier", "discord", "max_jump")
               if all(m in s["methods"] for s in series)}
    product = correct["product"]
    facts: dict[str, Any] = {
        "settings": ucr.get("settings") or {},
        "series": overall["series"],
        "random": overall["default_rate"] * overall["series"],
        "correct": {m: int(v.sum()) for m, v in correct.items()},
        "product_ci": _bootstrap(product.astype(float)[:, None], lambda r: r.sum() / len(r) * len(series)),
        "found_anywhere": overall["product"].get("found_anywhere"),
        "timeouts": overall["product"].get("timeouts"),
        "found_by": _count(
            (s["methods"]["product"].get("top_candidates") or [{}])[0].get("analyzer") for s in series if s["methods"]["product"].get("correct")),
    }
    if "static_threshold" in correct:
        static = correct["static_threshold"]
        zscore = correct.get("anomaly_zscore", np.zeros_like(static))
        facts.update({
            "only_ours": int((product & ~static & ~zscore).sum()),
            "both": int((product & static).sum()),
            "only_threshold": int((~product & static).sum()),
            "paired_vs_threshold": _bootstrap(np.column_stack([product, static]).astype(float),
                                              lambda r: r[:, 0].sum() - r[:, 1].sum()),
        })
    return facts


def _count(items) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item or "?"] = counts.get(item or "?", 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


# --- TCPD -------------------------------------------------------------------------------------


def _tcpd(tcpd: dict[str, Any] | None) -> dict[str, Any] | None:
    if not tcpd:
        return None
    series = [s for s in tcpd["series"] if s.get("scores")]
    f1 = {m: np.array([s["scores"][m]["f1"] for s in series if m in s["scores"]]) for m in ("product", "all_analyzers", "no_change")}
    published = [row for row in tcpd["leaderboard"] if not row["ours"] and row["method"] != "zero"]
    best = max(published, key=lambda row: row["f1"]) if published else None
    both = np.column_stack([f1["product"], f1["all_analyzers"]]) if len(f1["all_analyzers"]) == len(f1["product"]) else None
    return {
        "settings": tcpd.get("settings") or {},
        "series": len(series),
        "evaluation_set": tcpd.get("evaluation_set_size"),
        "leaderboard": tcpd["leaderboard"],
        "product_f1": float(f1["product"].mean()),
        "product_ci": _bootstrap(f1["product"][:, None], lambda r: float(r.mean())),
        "all_f1": float(f1["all_analyzers"].mean()) if len(f1["all_analyzers"]) else None,
        "no_change_f1": float(f1["no_change"].mean()) if len(f1["no_change"]) else None,
        "best_published": best,
        "rank": 1 + sum(1 for row in published if row["f1"] > f1["product"].mean()),
        "published_count": len(published),
        "paired_vs_all": _bootstrap(both, lambda r: float(r[:, 0].mean() - r[:, 1].mean())) if both is not None else None,
        "cost": tcpd.get("cost"),
        "change_detector_ran": sum(bool(s.get("change_analyzers_run")) for s in series),
    }


# --- SMD --------------------------------------------------------------------------------------


def _smd(smd: dict[str, Any] | None) -> dict[str, Any] | None:
    if not smd:
        return None
    head = str(smd["settings"]["headline_threshold"])
    methods = {}
    per_machine = {}
    for method, data in smd["comparison"].items():
        o = data["overall"][head]
        methods[method] = {"label": LABELS.get(method, method), "caught": o["caught"], "incidents": o["incidents"],
                           "alerts": o["alerts"], "false_alerts": o["false_alerts"], "precision": o["precision"],
                           "f1": o["f1"], "false_per_day": o.get("false_alerts_per_machine_day"),
                           "hit_rate": (o.get("hit_rate") or {}).get("100")}
        rows = [m["methods"][method]["headline"] for m in smd["machines"] if method in m["methods"]]
        per_machine[method] = np.array([[r["caught"], r["incidents"], r["alerts_in_incidents"], r["alerts"]] for r in rows], dtype=float)
        methods[method]["f1_ci"] = _bootstrap(per_machine[method], _nab_f1)
    paired = None
    if ROUTER_PICKS in per_machine and STATIC_THRESHOLD in per_machine and len(per_machine[ROUTER_PICKS]) == len(per_machine[STATIC_THRESHOLD]):
        both = np.hstack([per_machine[ROUTER_PICKS], per_machine[STATIC_THRESHOLD]])
        paired = _bootstrap(both, lambda r: _nab_f1(r[:, :4]) - _nab_f1(r[:, 4:]))
    return {"settings": smd["settings"], "machines": len(smd["machines"]), "metrics_per_machine": smd["smd"].get("metrics_per_machine"),
            "methods": methods, "paired_f1_vs_threshold": paired, "gap_minutes": smd["settings"].get("alert_gap_minutes")}


# --- own scenarios ----------------------------------------------------------------------------


def _behavior(behavior: dict[str, Any] | None) -> dict[str, Any] | None:
    if not behavior:
        return None
    scenarios = []
    for s in behavior["scenarios"]:
        default = s.get("default_mode_evaluation") or {}
        scenarios.append({"name": s["scenario"].get("name") or s["scenario"]["id"], "default": default.get("status"),
                          "all": (s.get("evaluation") or {}).get("status"),
                          "findings": [f["title"] for f in default.get("matched_findings") or []],
                          "metrics": sorted((default.get("analyzers_by_metric") or {}).keys())})
    return {"scenarios": scenarios, "passed": sum(s["default"] == "PASS" for s in scenarios)}


def _router(router: dict[str, Any] | None) -> dict[str, Any] | None:
    return {"counts": router["counts"], "total": len(router["scenarios"])} if router else None


def _routing_row(row: dict[str, Any]) -> dict[str, Any]:
    cells = row["cells"]
    ours, everything = cells.get(ROUTER_PICKS), cells.get(ALL_ANALYZERS)
    saving = 1 - ours["analyzer_runs"] / everything["analyzer_runs"] if ours and everything and everything.get("analyzer_runs") else None
    return {"suite": row["suite"], "dataset": row["dataset"], "measure": row["measure"],
            "ours": ours, "everything": everything, "saving": saving, "verdict": row["verdict"]}


def best_threshold_under(budget: dict[str, Any], alerts: int) -> int | None:
    return best_under(budget["curves"]["static_threshold"], alerts)
