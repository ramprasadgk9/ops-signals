"""Two questions, computed from a snapshot's results (nothing is rerun):

1. Router choices - did the router pick the right analyzers?
   - Right kind: an anomaly dataset (NAB, UCR, SMD) needs an anomaly detector among the router's
     picks, a change dataset (TCPD) needs a change detector. Extra picks are fine.
   - One that worked: among cases where some analyzer, on its own, found the problem, did the router
     pick one of those analyzers?
   Judged case by case: each NAB incident window, UCR series, TCPD series with a marked change, and
   SMD incident (for "right kind", each SMD metric involved in an incident).

2. Analyzer scorecard - is each analyzer good at what it's built for? Graded only on its own kind of
   problem, against bars fixed before any result was seen:
   - Anomaly detectors: catch at least as many as the static threshold, with no more false alerts.
   - Change detectors (TCPD): F1 above never predicting a change, and within 0.05 of the best
     published method.
   - Own-scenario checks: report the problem in every target case, nothing on healthy data.

Everything counts only what a user would see (findings), as the harnesses record it.
"""

from __future__ import annotations

import statistics
from typing import Any

ANOMALY_ANALYZERS = ("pyod_outlier", "anomaly_zscore", "seasonal_anomaly")
CHANGE_ANALYZERS = ("ruptures", "baseline_shift")
ROUTER_BAR = 0.8
PUBLISHED_MARGIN = 0.05
HEADLINE = "0.5"

KIND_ANALYZERS = {"anomaly": set(ANOMALY_ANALYZERS), "change": set(CHANGE_ANALYZERS)}
DATASETS = {
    "nab": ("NAB", "anomaly", "incident windows"),
    "ucr": ("UCR", "anomaly", "series"),
    "tcpd": ("TCPD", "change", "series with a marked change"),
    "smd": ("SMD", "anomaly", "incidents"),
}


def router_choices(suites: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for suite, builder in (("nab", _nab_cases), ("ucr", _ucr_cases), ("tcpd", _tcpd_cases), ("smd", _smd_cases)):
        data = suites.get(suite)
        if not data:
            continue
        cases = builder(data)
        if cases is None:
            continue
        name, kind, unit = DATASETS[suite]
        wanted = KIND_ANALYZERS[kind]
        right_kind = [c for c in cases["kind_cases"]]
        kind_hits = sum(1 for c in right_kind if set(c["ran"]) & wanted)
        solvable = [c for c in cases["cases"] if c["capable"]]
        worked = sum(1 for c in solvable if _hit(c))
        rows.append({
            "suite": suite,
            "dataset": name,
            "kind": kind,
            "unit": unit,
            "kind_unit": cases.get("kind_unit", unit),
            "right_kind": _rate(kind_hits, len(right_kind)),
            "worked": _rate(worked, len(solvable)),
            "nobody_could": len(cases["cases"]) - len(solvable),
            "cases": len(cases["cases"]),
            "misses": [c for c in solvable if not _hit(c)],
            "wrong_kind": [c for c in right_kind if not set(c["ran"]) & wanted],
        })
    return rows


def own_router_scenarios(suites: dict[str, Any]) -> dict[str, Any] | None:
    """The router scenario suite, counting only scenarios whose required analyzers can actually run."""
    router = suites.get("router")
    if not router:
        return None
    executable = set(router.get("executable_analyzers") or [])
    runnable = [
        s for s in router["scenarios"]
        if all(name in executable for name in (s["expected_router"].get("required_recommended") or []))
    ]
    return {
        "total": len(router["scenarios"]),
        "runnable": len(runnable),
        "runnable_passed": sum(1 for s in runnable if s["evaluation"]["status"] == "PASS"),
        "router_only": sorted(
            name
            for s in router["scenarios"]
            for name in (s["expected_router"].get("required_recommended") or [])
            if name not in executable
        ),
    }


def analyzer_scorecard(suites: dict[str, Any]) -> list[dict[str, Any]]:
    checks = (suites.get("analyzers") or {}).get("analyzers") or {}
    names = list(ANOMALY_ANALYZERS) + list(CHANGE_ANALYZERS) + [n for n in checks if n not in ANOMALY_ANALYZERS + CHANGE_ANALYZERS]
    rows = []
    for analyzer in names:
        cells: dict[str, dict[str, Any] | None] = {}
        if analyzer in ANOMALY_ANALYZERS:
            cells["nab"] = _nab_grade(suites.get("nab"), analyzer)
            cells["ucr"] = _ucr_grade(suites.get("ucr"), analyzer)
            cells["smd"] = _smd_grade(suites.get("smd"), analyzer)
        if analyzer in CHANGE_ANALYZERS:
            cells["tcpd"] = _tcpd_grade(suites.get("tcpd"), analyzer)
        check = checks.get(analyzer)
        if check:
            cells["own"] = {
                "text": f"{check['passed']} of {check['total']} checks",
                "good": check["passed"] == check["total"],
                "detail": "; ".join(
                    f"{c['description']}: {'✓' if c['passed'] else '✕'} ({c['signals']} seen, {c['raw_signals']} raw)" for c in check["checks"]
                ),
            }
        graded = [cell for cell in cells.values() if cell is not None]
        verdict = "not graded" if not graded else ("good" if all(c["good"] for c in graded) else "weak")
        rows.append({"analyzer": analyzer, "cells": cells, "verdict": verdict, "built_for": _built_for(analyzer)})
    return rows


# --- router cases per dataset -------------------------------------------------------------------


def _nab_cases(nab: dict[str, Any]) -> dict[str, Any] | None:
    cases = []
    for series in nab["series"]:
        for window in series.get("windows_detail") or []:
            cases.append({"id": f"{series['series']} rows {window['rows'][0]}-{window['rows'][1]}",
                          "ran": window["router_ran"], "capable": window["capable"]})
    if not cases and not any("windows_detail" in s for s in nab["series"]):
        return None
    return {"cases": cases, "kind_cases": cases}


def _ucr_cases(ucr: dict[str, Any]) -> dict[str, Any] | None:
    cases = []
    for series in ucr["series"]:
        product, everything = series["methods"].get("product") or {}, series["methods"].get("all_analyzers") or {}
        if not product.get("executed_analyzers"):
            continue
        capable = sorted(a for a, correct in (everything.get("per_analyzer_correct") or {}).items() if correct)
        cases.append({"id": f"#{series['number']} {series['name']}", "ran": product["executed_analyzers"], "capable": capable})
    return {"cases": cases, "kind_cases": cases} if cases else None


def _tcpd_cases(tcpd: dict[str, Any]) -> dict[str, Any] | None:
    cases = []
    for series in tcpd["series"]:
        counts = sorted(series["annotated_cp_counts"])
        if counts[len(counts) // 2] == 0:
            continue  # most annotators marked no change: any choice is fine
        per = series.get("per_analyzer_scores") or {}
        no_change = series["scores"].get("no_change", {}).get("f1")
        capable = sorted(a for a, s in per.items() if no_change is not None and s["f1"] > no_change)
        cases.append({"id": series["series"], "ran": series["executed_analyzers"], "capable": capable})
    return {"cases": cases, "kind_cases": cases} if cases else None


def _smd_cases(smd: dict[str, Any]) -> dict[str, Any] | None:
    cases, kind_cases = [], []
    for machine in smd["machines"]:
        by_metric = (machine["methods"].get("router_picks") or {}).get("analyzers_by_metric") or {}
        for choice in machine.get("router_choices") or []:
            # Whether the router ran a capable analyzer on a metric where it alarmed was decided by the
            # harness, which knows the metric each alarm came from.
            cases.append({"id": f"{machine['machine']} rows {choice['rows'][0]}-{choice['rows'][1]}",
                          "ran": sorted({a for analyzers in by_metric.values() for a in analyzers}),
                          "capable": choice["capable"], "hit": bool(choice["router_ran_capable"])})
        for start, end, metrics in machine["incidents"]:
            for metric in metrics:
                kind_cases.append({"id": f"{machine['machine']} metric {metric:02d} (incident at row {start})",
                                   "ran": by_metric.get(f"metric_{metric:02d}", [])})
    if not kind_cases:
        return None
    return {"cases": cases, "kind_cases": kind_cases, "kind_unit": "metrics involved in incidents"}


# --- analyzer grades -----------------------------------------------------------------------------


def _nab_grade(nab: dict[str, Any] | None, analyzer: str) -> dict[str, Any] | None:
    if not nab or not nab.get("analyzers") or analyzer not in nab["analyzers"]:
        return None
    own = nab["analyzers"][analyzer][HEADLINE]
    static = nab["comparison"].get("static_threshold", {}).get("overall", {}).get(HEADLINE)
    if not static:
        return None
    good = own["detected_windows"] >= static["detected_windows"] and own["false_alarms"] <= static["false_alarms"]
    return {"text": f"caught {own['detected_windows']}/{own['windows']} · {own['false_alarms']:,} false",
            "good": good,
            "detail": f"static threshold: caught {static['detected_windows']}/{static['windows']} · {static['false_alarms']:,} false"}


def _ucr_grade(ucr: dict[str, Any] | None, analyzer: str) -> dict[str, Any] | None:
    if not ucr:
        return None
    overall = ucr["summary"]["overall"]
    if analyzer not in overall or "static_threshold" not in overall:
        return None
    own, static, total = overall[analyzer]["correct"], overall["static_threshold"]["correct"], overall["series"]
    return {"text": f"{own} of {total} located", "good": own >= static, "detail": f"static threshold: {static} of {total}"}


def _smd_grade(smd: dict[str, Any] | None, analyzer: str) -> dict[str, Any] | None:
    if not smd or not smd.get("analyzers") or analyzer not in smd["analyzers"]:
        return None
    own = smd["analyzers"][analyzer][HEADLINE]
    static = smd["comparison"].get("static_threshold", {}).get("overall", {}).get(HEADLINE)
    if not static:
        return None
    good = own["caught"] >= static["caught"] and own["false_alerts"] <= static["false_alerts"]
    return {"text": f"caught {own['caught']}/{own['incidents']} · {own['false_alerts']:,} false",
            "good": good,
            "detail": f"static threshold: caught {static['caught']}/{static['incidents']} · {static['false_alerts']:,} false"}


def _tcpd_grade(tcpd: dict[str, Any] | None, analyzer: str) -> dict[str, Any] | None:
    if not tcpd or analyzer not in (tcpd.get("analyzers") or {}):
        return None
    own = tcpd["analyzers"][analyzer]["f1"]
    series = [s for s in tcpd["series"] if "no_change" in s["scores"]]
    if not series:
        return None
    no_change = statistics.mean(s["scores"]["no_change"]["f1"] for s in series)
    published = [row["f1"] for row in tcpd["leaderboard"] if not row["ours"] and row["method"] != "zero"]
    best = max(published) if published else None
    good = own > no_change and (best is None or own >= best - PUBLISHED_MARGIN)
    return {"text": f"F1 {own:.3f}", "good": good,
            "detail": f"never predicting a change: {no_change:.3f}" + (f" · best published: {best:.3f}" if best is not None else "")}


def _built_for(analyzer: str) -> str:
    return {
        "pyod_outlier": "Short spikes and outlier points",
        "anomaly_zscore": "Values far from the recent average",
        "seasonal_anomaly": "Values unusual for their time of day or week",
        "ruptures": "The moment a metric changes for good",
        "baseline_shift": "A metric settling at a new level",
        "trend": "A slow, steady drift up or down",
        "stumpy": "Repeating patterns",
        "data_health": "Gaps (no data) and flatlines (stuck values)",
    }.get(analyzer, "")


def _hit(case: dict[str, Any]) -> bool:
    return case["hit"] if "hit" in case else bool(set(case["ran"]) & set(case["capable"]))


def _rate(hits: int, total: int) -> dict[str, Any]:
    return {"hits": hits, "total": total, "share": hits / total if total else None,
            "meets_bar": (hits / total >= ROUTER_BAR) if total else None}
