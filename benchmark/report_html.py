"""Render a benchmark results snapshot (benchmark/run_all.py's results.json) as one self-contained
HTML evidence report - no external scripts, stylesheets or fonts, so it opens offline and can be
attached or archived as a single file.

Rebuild a report from an existing snapshot without rerunning anything:

    .venv/bin/python -m benchmark.report_html benchmark/results/latest/results.json
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import math
from html import escape
from pathlib import Path
from typing import Any

STATUS_META = {
    "PASS": ("good", "✓", "Pass"),
    "GAP": ("warning", "◐", "Known gap"),
    "FAIL": ("critical", "✕", "Fail"),
    "ERROR": ("critical", "!", "Error"),
}

# The published method behind each analyzer that actually executes - mirrors
# docs/26-analyzer-methodology.md, which is the source of truth for these citations.
ANALYZER_METHODS = [
    ("ruptures / baseline_shift", "Regime changes, sustained level shifts", "Offline change-point detection (binary segmentation)", "Truong, Oudre & Vayatis (2020), Signal Processing 167"),
    ("stumpy", "Repeating patterns, motifs", "Matrix Profile", "Yeh et al. (2016), IEEE ICDM; Law (2019), JOSS 4(39)"),
    ("prophet", "Trend + seasonal forecast deviation", "Additive regression forecasting", "Taylor & Letham (2018), The American Statistician 72(1)"),
    ("pyod_outlier", "Isolated outlier points", "KNN outlier scoring", "Zhao, Nasrullah & Li (2019), JMLR 20(96)"),
    ("anomaly_zscore", "Points far from the recent mean", "Sigma-threshold control", "Shewhart (1931)"),
    ("trend", "Sustained upward/downward slope", "Ordinary least squares", "Seabold & Perktold (2010), SciPy Proceedings"),
    ("seasonal_anomaly", "Values unusual for their time of day/week", "STL decomposition + MAD robust z-score", "Cleveland et al. (1990), J. Official Statistics 6(1); Iglewicz & Hoaglin (1993)"),
    ("data_health", "Gaps and flatlines", "Explicit cadence and rate-of-change rules", "Not a statistical method"),
]

PENDING_SECTIONS = [
    ("nab", "Numenta Anomaly Benchmark (all 58 series)", "Real labeled data scored with NAB's official scorer, comparable with the published leaderboard."),
    ("baselines", "Baselines and router ablation", "The same data run with a static threshold, z-score only, all analyzers and router-selected analyzers."),
    ("tcpd", "Turing Change Point Dataset (TCPD)", "Real series with change points marked by five annotators, compared with the 14 methods published alongside it."),
    ("ucr", "UCR Anomaly Archive", "A second, independent public dataset (250 series, one anomaly each)."),
]

PROFILE_FEATURES = [
    ("sample_count", "Samples"),
    ("sampling_interval_seconds", "Interval (s)"),
    ("regular_sampling", "Regular sampling"),
    ("shift_index", "Shift index"),
    ("spikiness", "Spikiness"),
    ("seasonality_strength", "Seasonality strength"),
    ("trend_strength", "Trend strength"),
    ("trend_fit_r2", "Trend fit R²"),
    ("persistent_jump_count", "Persistent jumps"),
    ("transient_spike_count", "Transient spikes"),
    ("missing_percentage", "Missing %"),
]


SUITE_TITLES = {
    "router": "Router scenario suite",
    "behavior": "Cross-metric behavior suite",
    "nab": "Numenta Anomaly Benchmark (NAB)",
    "tcpd": "Turing Change Point Dataset (TCPD)",
    "ucr": "UCR Time Series Anomaly Archive",
    "performance": "Performance and scale",
}


def render(results: dict[str, Any], official_nab: dict[str, Any] | None = None, *, suite: str | None = None) -> str:
    """The full report, or with `suite` set, a report for that one suite (same header, summary,
    method basis and reproduction details; no cross-suite scope or pending list)."""
    suites = results.get("suites", {})
    if suite is not None:
        suites = {suite: suites[suite]}
        results = {**results, "suites": suites}
    manifest = results.get("manifest", {})
    body = [_header(results, suite=suite), _at_a_glance(results, official_nab, suite), _summary(results)]
    if suite is None:
        body.append(_scope(suites, official_nab is not None))
    if "router" in suites:
        body.append(_router_section(suites["router"]))
    if "behavior" in suites:
        body.append(_behavior_section(suites["behavior"]))
    if "nab" in suites:
        body.append(_nab_section(suites["nab"], official_nab))
    if "tcpd" in suites:
        body.append(_tcpd_section(suites["tcpd"]))
    if "ucr" in suites:
        body.append(_ucr_section(suites["ucr"]))
    if "performance" in suites:
        body.append(_performance_section(suites["performance"]))
    if suite is None:
        body.append(_pending_section(suites))
    body.append(_method_section())
    body.append(_reproduce_section(results, manifest))
    title = f"{SUITE_TITLES.get(suite, suite)} · " if suite else ""
    return _document(f"Ops Signals Benchmark · {title}{results.get('run_id', '')}", "\n".join(body))


def write_report(results_path: Path, output_path: Path | None = None) -> Path:
    """Write report.html (every suite), report-<suite>.html for each suite in the snapshot, and
    index.html, the landing page linking to them."""
    results = json.loads(results_path.read_text(encoding="utf-8"))
    output_path = output_path or results_path.with_name("report.html")
    official = load_official_nab(results_path.parent / "raw" / "nab_official")
    output_path.write_text(render(results, official), encoding="utf-8")
    for suite in results.get("suites", {}):
        suite_path = output_path.with_name(f"{output_path.stem}-{suite}.html")
        suite_path.write_text(render(results, official, suite=suite), encoding="utf-8")
    output_path.with_name("index.html").write_text(render_index(results, official, stem=output_path.stem), encoding="utf-8")
    return output_path


def load_official_nab(official_dir: Path) -> dict[str, Any] | None:
    """NAB's own scorer output for this snapshot (benchmark/nab/official_score.py), if it was run."""
    final_path = official_dir / "final_results.json"
    published_path = official_dir / "published_final_results.json"
    if not final_path.exists() or not published_path.exists():
        return None
    totals: dict[str, dict[str, dict[str, Any]]] = {}
    for scores_path in sorted(official_dir.glob("*_scores.csv")):
        with scores_path.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            continue
        detector, profile = rows[0]["Detector"], scores_path.stem[len(rows[0]["Detector"]) + 1 : -len("_scores")]
        total = next((row for row in rows if row["Detector"] == "Totals"), None)
        if total:
            totals.setdefault(detector, {})[profile] = {
                "threshold": float(rows[0]["Threshold"]),
                **{key: float(total[key]) for key in ("TP", "FP", "FN", "Score")},
            }
    return {
        "final": json.loads(final_path.read_text(encoding="utf-8")),
        "published": json.loads(published_path.read_text(encoding="utf-8")),
        "totals": totals,
    }


# --- at a glance ----------------------------------------------------------------------------

SUITE_ORDER = ("router", "behavior", "performance", "nab", "tcpd", "ucr")
DATASET_SPANS = {"24h": "24 hours", "7d": "7 days", "30d": "30 days"}


def _at_a_glance(results: dict[str, Any], official_nab: dict[str, Any] | None, suite: str | None) -> str:
    """Plain-language summary that opens every report: what each suite tests, where its data and
    answer key come from, what we got, and what a good result looks like on that suite's scale."""
    suites = results.get("suites", {})
    briefs = [brief for name in SUITE_ORDER if name in suites for brief in [_brief(name, suites[name], official_nab)] if brief]
    if not briefs:
        return ""
    if suite is not None:
        b = briefs[0]
        rows = "".join(
            f"<div><dt>{label}</dt><dd>{value}</dd></div>"
            for label, value in (
                ("What it tests", b["tests"]),
                ("Data source", b["source"]),
                ("Ground truth", b["truth"][:1].upper() + b["truth"][1:]),
                ("Our result", f"<b>{b['result']}</b>"),
                ("What good looks like", b["good"]),
            )
        )
        return f"""
<section class="glance" aria-label="At a glance">
  <h2>At a glance</h2>
  <div class="card glance-card">
    <p class="glance-verdict">{_verdict_pill(b['verdict'])} {b['verdict'][1]}</p>
    <dl class="glance-list">{rows}</dl>
  </div>
</section>"""
    table_rows = "".join(
        f"<tr><td><a href='report-{escape(b['suite'])}.html'>{escape(b['title'])}</a><div class='small muted'>{b['tests']}</div></td>"
        f"<td class='small'>{escape(b['kind'])}</td>"
        f"<td class='small'>{b['source']}<div class='muted'>Answer key: {b['truth']}</div></td>"
        f"<td><b>{b['result']}</b></td><td class='small'>{b['good']}</td>"
        f"<td>{_verdict_pill(b['verdict'])}<div class='small'>{b['verdict'][1]}</div></td></tr>"
        for b in briefs
    )
    own = sum(1 for b in briefs if b["kind"] == "Own test")
    external = len(briefs) - own
    return f"""
<section class="glance" aria-label="At a glance">
  <h2>At a glance</h2>
  <p class="section-lede">This report measures how well Ops Signals finds real problems in metric data. It has {len(briefs)} parts:
  {own} own test{'s' if own != 1 else ''} with answer keys written by this project (they catch regressions but aren't independent evidence) and
  {external} public benchmark{'s' if external != 1 else ''} whose data and labels come from outside researchers, compared with published methods
  where they exist. Each row below says what was tested, who decided the right answers, what we got, and what a good score is on that scale.
  Details for each part follow further down and in its own report.</p>
  <div class="table-wrap"><table class="glance-table">
    <thead><tr><th>Part</th><th>Type</th><th>Data and answer key</th><th>Our result</th><th>What good looks like</th><th>Verdict</th></tr></thead>
    <tbody>{table_rows}</tbody>
  </table></div>
</section>"""


def _verdict_pill(verdict: tuple[str, str]) -> str:
    kind = verdict[0]
    icon, label = {"good": ("✓", "Good"), "warning": ("◐", "Mixed"), "critical": ("✕", "Weak")}[kind]
    return f"<span class='pill pill-{kind}'><span aria-hidden='true'>{icon}</span> {label}</span>"


def _brief(name: str, data: dict[str, Any], official_nab: dict[str, Any] | None) -> dict[str, Any] | None:
    builder = {
        "router": _brief_router,
        "behavior": _brief_behavior,
        "performance": _brief_performance,
        "nab": lambda d: _brief_nab(d, official_nab),
        "tcpd": _brief_tcpd,
        "ucr": _brief_ucr,
    }.get(name)
    brief = builder(data) if builder else None
    if brief:
        brief.update(suite=name, title=SUITE_TITLES.get(name, name))
    return brief


def _brief_router(router: dict[str, Any]) -> dict[str, Any]:
    counts = router["counts"]
    total = sum(counts.values())
    failed = counts.get("FAIL", 0) + counts.get("ERROR", 0)
    gaps = counts.get("GAP", 0)
    return {
        "kind": "Own test",
        "tests": "For each kind of problem (step change, trend, spikes, seasonality, ...), whether the router picks the right analyzer and the analyzer finds the injected event.",
        "source": f"{total} scenarios built by this project from real CPU metrics with problems injected on purpose.",
        "truth": "written by this project with each scenario, so it isn't independent.",
        "result": f"{counts.get('PASS', 0)} of {total} pass{f', {gaps} known gap' + ('s' if gaps != 1 else '') if gaps else ''}, {failed} fail",
        "good": "Every scenario passes. A failure means something that used to work broke. Known gaps are documented limits, not regressions.",
        "verdict": ("critical", "Something broke; see the failing scenarios.") if failed else
                   (("warning", f"No regressions; {gaps} documented gap{'s' if gaps != 1 else ''} remain.") if gaps else ("good", "No regressions.")),
    }


def _brief_behavior(behavior: dict[str, Any]) -> dict[str, Any]:
    counts = behavior["counts"]
    total = sum(counts.values())
    passed = counts.get("PASS", 0)
    return {
        "kind": "Own test",
        "tests": "Whether problems across several metrics at once (for example CPU and errors rising together) are recognized as the right named behavior.",
        "source": f"{total} multi-metric scenarios built by this project.",
        "truth": "written by this project with each scenario, so it isn't independent.",
        "result": f"{passed} of {total} pass",
        "good": "Every scenario passes. It's a regression check, not a measure of real-world accuracy.",
        "verdict": ("good", "No regressions.") if passed == total else ("critical", "Something broke; see the failing scenarios."),
    }


def _brief_performance(performance: dict[str, Any]) -> dict[str, Any] | None:
    datasets = performance.get("datasets") or []
    if not datasets:
        return None
    largest = max(datasets, key=lambda d: d["sample_count"])
    ceiling = performance.get("max_seconds_per_analyzer", 30)
    slowest = max((row["elapsed_seconds"] for d in datasets for row in d["analyzers"] if not row.get("error")), default=0.0)
    return {
        "kind": "Own test",
        "tests": "How long analysis takes as the data grows from one day to 30 days.",
        "source": "Healthy CPU metrics from the TSBS benchmark data set, at 24 hours, 7 days and 30 days.",
        "truth": "none needed; this measures time only.",
        "result": f"{DATASET_SPANS.get(largest['dataset_label'], largest['dataset_label'])} of data ({largest['sample_count']:,} points) analyzed in {largest['total_seconds']:.2f} s",
        "good": f"Seconds or less feels instant. The hard limit is {ceiling:.0f} s per analyzer, which only catches a catastrophic slowdown.",
        "verdict": ("good", f"Slowest analyzer {slowest:.2f} s, well under the limit.") if slowest < ceiling else ("critical", "An analyzer exceeded the time limit."),
    }


def _brief_nab(nab: dict[str, Any], official: dict[str, Any] | None) -> dict[str, Any]:
    headline = str(nab["settings"]["headline_threshold"])
    replay = nab["overall"]["replay"][headline]
    windows = f"caught {replay['detected_windows']} of {replay['windows']} labeled incidents; {_pct(replay['alarm_precision'])} of alarms were inside one"
    brief = {
        "kind": "Public benchmark",
        "tests": "Whether real incidents are flagged, early, without too many false alarms, using only data seen so far.",
        "source": f"Numenta Anomaly Benchmark: {len(nab['series'])} real and artificial series (server metrics, network traffic, ad clicks, sensor readings).",
        "truth": "incident windows labeled by Numenta, not by this project.",
    }
    if official:
        ours = official["final"].get(nab["detector_names"]["replay"], {})
        score = float(ours.get("standard", 0.0))
        published = {k: float(v.get("standard", 0.0)) for k, v in official["published"].items() if k not in ("null", "random")}
        random_score = float(official["published"].get("random", {}).get("standard", 0.0))
        best_name = max(published, key=published.get) if published else None
        low, high = (min(published.values()), max(published.values())) if published else (0.0, 0.0)
        brief["result"] = f"Official NAB score {score:.1f} of 100 <span class='muted'>({windows})</span>"
        brief["good"] = (
            f"100 is perfect; never raising an alarm scores 0; random alarms score {random_score:.1f}. Published detectors score "
            f"{low:.1f} to {high:.1f} (best: {escape(best_name or '-')})."
        )
        if score <= 0.0:
            brief["verdict"] = ("critical", "No better than never alarming: too many false alarms outweigh the incidents caught.")
        elif score < random_score:
            brief["verdict"] = ("critical", "Below random alarms.")
        elif score < low:
            brief["verdict"] = ("warning", "Above random, below every published detector.")
        else:
            brief["verdict"] = ("good", "Within the range of published detectors.")
    else:
        brief["result"] = windows.capitalize()
        brief["good"] = "Catching most incidents with most alarms inside an incident. NAB's official score isn't in this snapshot."
        brief["verdict"] = ("warning", "Official score not computed for this snapshot.")
    return brief


def _brief_tcpd(tcpd: dict[str, Any]) -> dict[str, Any] | None:
    board = tcpd.get("leaderboard") or []
    product = next((row for row in board if row["ours"] and "product" in row["method"]), None)
    published = [row for row in board if not row["ours"]]
    zero = next((row for row in published if row["method"] == "zero"), None)
    if not product or not published or not zero:
        return None
    best = max(published, key=lambda row: row["f1"])
    beaten = sum(1 for row in published if row["f1"] < product["f1"])
    if product["f1"] <= zero["f1"]:
        verdict = ("critical", "No better than never predicting a change.")
    elif product["f1"] >= best["f1"] - 0.02:
        verdict = ("good", f"On par with the best published method; ahead of {beaten} of {len(published)}.")
    else:
        verdict = ("warning", f"Better than never predicting a change; ahead of {beaten} of {len(published)} published methods.")
    return {
        "kind": "Public benchmark",
        "tests": "Whether the moments a series changes behavior (level, trend or variance) are found in the right place.",
        "source": f"Turing Change Point Dataset: {len(tcpd['evaluated'])} real series (economics, energy, transport, sensors), with results for 14 published methods.",
        "truth": "change points marked independently by five human annotators.",
        "result": f"F1 {product['f1']:.3f}",
        "good": f"1.0 is perfect. Never predicting a change scores {zero['f1']:.3f} (silence is rewarded on series with no change). "
                f"Best published method: {escape(best['method'])} {best['f1']:.3f}. Differences of a few hundredths are within noise.",
        "verdict": verdict,
    }


def _brief_ucr(ucr: dict[str, Any]) -> dict[str, Any]:
    overall = ucr["summary"]["overall"]
    total = overall["series"]
    product, discord, jump = overall["product"]["correct"], overall["discord"]["correct"], overall["max_jump"]["correct"]
    random_expected = overall["default_rate"] * total
    if product <= random_expected:
        verdict = ("critical", "No better than guessing at random.")
    elif product < jump:
        verdict = ("critical", "Below a one-line baseline (the largest single jump).")
    elif product < discord:
        verdict = ("warning", "Above the trivial baseline, below the textbook shape-based method.")
    else:
        verdict = ("good", "At or above the textbook shape-based method.")
    return {
        "kind": "Public benchmark",
        "tests": "Whether the one anomaly in each series is located, including anomalies that change a shape rather than a value.",
        "source": f"UCR Time Series Anomaly Archive: {total} series (heartbeats, blood pressure, gait, respiration, insect feeding, power demand, NASA telemetry).",
        "truth": "one anomaly per series, set by the archive's creators (Wu &amp; Keogh, 2021).",
        "result": f"{product} of {total} located ({_pct(product / total if total else None)})",
        "good": f"100% is perfect. Guessing at random gets about {random_expected:.1f} ({_pct(overall['default_rate'])}). "
                f"The largest single jump gets {jump} ({_pct(jump / total if total else None)}); "
                f"a textbook matrix-profile discord gets {discord} ({_pct(discord / total if total else None)}).",
        "verdict": verdict,
    }


# --- index page -----------------------------------------------------------------------------

SUITE_GUIDE = {
    "router": ("Does Ops Signals pick the right detector for each kind of problem?", ("Own test", "Injected problems", "Right detector?", "Regression check")),
    "behavior": ("Does it recognize a problem that shows up across several metrics at once?", ("Own test", "Several metrics", "Named problems", "Regression check")),
    "performance": ("Is it fast enough as the data grows to 30 days?", ("Own test", "Speed", "Scale")),
    "nab": ("Does it catch real incidents early without flooding you with false alarms?", ("Public benchmark", "Real data", "Incidents", "False alarms")),
    "tcpd": ("Does it find the moment a metric's behavior changed, compared with published methods?", ("Public benchmark", "Real data", "Change points", "Human labels")),
    "ucr": ("Can it pinpoint the one anomaly hidden in a long recording?", ("Public benchmark", "250 series", "Find the anomaly", "Shape changes")),
}

GLOSSARY = (
    ("Ground truth", "The right answers a result is checked against, and who decided them."),
    ("Own test", "Data and answers written by this project. Good for catching regressions, not independent proof."),
    ("Public benchmark", "Data and answers published by outside researchers, often with other methods' scores to compare against."),
    ("Anomaly", "A value or stretch of data that doesn't fit the usual pattern."),
    ("Change point", "The moment a metric's level, trend or variability changes for good."),
    ("False alarm", "An alert raised when nothing was actually wrong."),
    ("F1", "A 0 to 1 score that balances finding the right things against flagging wrong ones. Higher is better."),
    ("Router", "The part of Ops Signals that decides which detectors to run on a series."),
)


def render_index(results: dict[str, Any], official_nab: dict[str, Any] | None = None, *, stem: str = "report") -> str:
    """The landing page of a snapshot: one card per report, in plain words, so a reader can pick
    the report that answers their question."""
    suites = results.get("suites", {})
    manifest = results.get("manifest", {})
    git = manifest.get("git", {})
    cards = []
    for name in [n for n in SUITE_ORDER if n in suites] + [n for n in suites if n not in SUITE_ORDER]:
        brief = _brief(name, suites[name], official_nab)
        question, tags = SUITE_GUIDE.get(name, ("", ()))
        href = f"{stem}-{name}.html"
        result = f"<p class='index-result'>{brief['result']}</p><p class='small'>{_verdict_pill(brief['verdict'])} {brief['verdict'][1]}</p>" if brief else ""
        cards.append(f"""
<a class="card index-card" href="{escape(href)}">
  <div class="tags">{''.join(f"<span class='tag'>{escape(tag)}</span>" for tag in tags)}</div>
  <h3>{escape(SUITE_TITLES.get(name, name))}</h3>
  <p class="index-question">{escape(question)}</p>
  {result}
  <span class="index-open small">Open report →</span>
</a>""")
    glossary = "".join(f"<div><dt>{escape(term)}</dt><dd>{escape(text)}</dd></div>" for term, text in GLOSSARY)
    dirty = " · <span class='pill pill-warning'>uncommitted changes present</span>" if git.get("dirty") else ""
    body = f"""
<header class="hero">
  <p class="eyebrow">Ops Signals · Benchmark evidence</p>
  <h1>Benchmark reports: start here</h1>
  <p class="lede">These reports show how well Ops Signals finds problems in metric data. Pick the one that answers your question. Each card
  says in plain words what it checks and how we did; the report itself has the detail.</p>
  <p class="small muted">Run <span class="mono">{escape(results.get('run_id', ''))}</span> · {escape(_fmt_time(manifest.get('started_at')))} ·
  commit <span class="mono">{escape((git.get('commit') or 'unknown')[:12])}</span>{dirty}</p>
</header>
<section>
  <a class="card index-all" href="{escape(stem)}.html"><b>Everything on one page →</b>
  <span class="small muted">The full report: an at-a-glance table of every part, then all the detail.</span></a>
</section>
<section>
  <h2>Pick a report</h2>
  <div class="index-grid">{''.join(cards)}</div>
</section>
<section>
  <h2>Words used in these reports</h2>
  <dl class="card glance-list">{glossary}</dl>
</section>"""
    return _document(f"Ops Signals Benchmark · Start here · {results.get('run_id', '')}", body)


# --- sections -------------------------------------------------------------------------------


def _header(results: dict[str, Any], *, suite: str | None = None) -> str:
    manifest = results.get("manifest", {})
    git = manifest.get("git", {})
    commit = git.get("commit") or "unknown"
    dirty = (
        '<span class="pill pill-warning"><span aria-hidden="true">◐</span> Uncommitted changes present</span>'
        if git.get("dirty")
        else '<span class="pill pill-good"><span aria-hidden="true">✓</span> Clean working tree</span>'
    )
    return f"""
<header class="hero">
  <p class="eyebrow">Ops Signals · Benchmark evidence report{f" · {escape(SUITE_TITLES.get(suite, suite))}" if suite else ""}</p>
  <h1>{escape(SUITE_TITLES.get(suite, suite)) if suite else "Analyzer and router benchmark results"}</h1>
  {_suite_links(results, suite)}
  <p class="lede">Every number on this page was produced by one command against a known commit, with the
  environment and input hashes recorded below, so it can be checked by rerunning rather than taken on trust.</p>
  <dl class="provenance">
    <div><dt>Run</dt><dd class="mono">{escape(results.get("run_id", ""))}</dd></div>
    <div><dt>Started</dt><dd>{escape(_fmt_time(manifest.get("started_at")))}</dd></div>
    <div><dt>Commit</dt><dd class="mono">{escape(commit[:12])} <span class="muted">on {escape(git.get("branch") or "?")}</span></dd></div>
    <div><dt>Accuracy fingerprint</dt><dd class="mono">{escape(results.get("fingerprint", ""))}</dd></div>
    <div><dt>Tree</dt><dd>{dirty}</dd></div>
  </dl>
</header>"""


def _suite_links(results: dict[str, Any], suite: str | None) -> str:
    """Links between the full report and the per-suite reports written next to it."""
    names = list(results.get("suites", {})) if suite is None else [suite]
    start = "<a href='index.html'>← Start here (all reports)</a>"
    if suite is None and len(names) < 2:
        return f"<p class='suite-links small'>{start}</p>"
    if suite is None:
        links = " · ".join(f"<a href='report-{escape(name)}.html'>{escape(SUITE_TITLES.get(name, name))}</a>" for name in names)
        return f"<p class='suite-links small'>{start} · Per-suite reports: {links}</p>"
    return f"<p class='suite-links small'>{start} · <a href='report.html'>Full report (every suite in this run)</a></p>"


def _summary(results: dict[str, Any]) -> str:
    suites = results.get("suites", {})
    tiles = []
    router = suites.get("router")
    if router:
        counts = router["counts"]
        total = sum(counts.values())
        executable = set(router.get("executable_analyzers") or [])
        router_only_passes = sum(
            1
            for s in router["scenarios"]
            if s["evaluation"]["status"] == "PASS"
            and executable
            and any(name not in executable for name in s["expected_router"].get("required_recommended") or [])
        )
        router_only_note = f" · {router_only_passes} of the passes need a router-only analyzer †" if router_only_passes else ""
        tiles.append(
            _tile(
                "Router scenarios",
                f"{counts.get('PASS', 0)}<span class='of'>/{total}</span>",
                f"pass · {counts.get('GAP', 0)} documented gap · {counts.get('FAIL', 0) + counts.get('ERROR', 0)} fail{router_only_note}",
                "good" if not (counts.get("FAIL") or counts.get("ERROR")) else "critical",
            )
        )
        detection = [s for s in router["scenarios"] if s["evaluation"].get("detection_checks") and s.get("expected_event")]
        if detection:
            passed = sum(1 for s in detection if all(s["evaluation"]["detection_checks"].values()))
            tiles.append(_tile("Detection accuracy", f"{passed}<span class='of'>/{len(detection)}</span>", "injected events found with the right direction, size and timing", "good" if passed == len(detection) else "critical"))
        control = next((s for s in router["scenarios"] if s.get("expects_no_actionable_findings")), None)
        if control:
            details = control["evaluation"].get("detection_details") or {}
            actionable = len(details.get("actionable_findings") or [])
            tiles.append(_tile("False alarms on stable data", str(actionable), f"actionable findings from {details.get('total_raw_signals', 0)} raw statistical signals", "good" if actionable == 0 else "critical"))
    behavior = suites.get("behavior")
    if behavior:
        counts = behavior["counts"]
        tiles.append(_tile("Cross-metric behaviors", f"{counts.get('PASS', 0)}<span class='of'>/{sum(counts.values())}</span>", "correlated multi-metric scenarios matched", "good" if counts.get("PASS", 0) == sum(counts.values()) else "critical"))
    nab = suites.get("nab")
    if nab:
        headline = str(nab["settings"]["headline_threshold"])
        replay = nab["overall"]["replay"][headline]
        tiles.append(
            _tile(
                "NAB windows caught (causal)",
                f"{replay['detected_windows']}<span class='of'>/{replay['windows']}</span>",
                f"real labeled anomaly windows, {len(nab['series'])} series · {_pct(replay['alarm_precision'])} of alarms inside a window",
                None,
            )
        )
    tcpd = suites.get("tcpd")
    if tcpd and tcpd.get("leaderboard"):
        board = tcpd["leaderboard"]
        product = next((row for row in board if row["ours"] and "product" in row["method"]), None)
        best = next((row for row in board if not row["ours"]), None)
        if product and best:
            tiles.append(
                _tile(
                    "TCPD change points (F1)",
                    f"{product['f1']:.3f}",
                    f"product, {len(tcpd['evaluated'])} real series · best published method {best['method']} {best['f1']:.3f} · no prediction {next(r['f1'] for r in board if r['method'] == 'zero'):.3f}",
                    None,
                )
            )
    ucr = suites.get("ucr")
    if ucr:
        overall = ucr["summary"]["overall"]
        total = overall["series"]
        tiles.append(
            _tile(
                "UCR anomalies located",
                f"{overall['product']['correct']}<span class='of'>/{total}</span>",
                f"product, one answer per series · matrix-profile discord {overall['discord']['correct']} · random guess {overall['default_rate'] * total:.1f}",
                None,
            )
        )
    performance = suites.get("performance")
    if performance and performance["datasets"]:
        largest = max(performance["datasets"], key=lambda item: item["sample_count"])
        tiles.append(_tile("Speed at 30 days of data", f"{largest['total_seconds']:.2f}<span class='of'>s</span>", f"{largest['sample_count']:,} samples, normalization plus every analyzer", None))
    return f'<section aria-label="Summary"><div class="tiles">{"".join(tiles)}</div></section>'


def _scope(suites: dict[str, Any], has_official_nab: bool = False) -> str:
    if "nab" in suites and has_official_nab:
        real_world = (
            "<li><b>A baseline comparison on the same data.</b> NAB's published scoreboard is shown for reference, but "
            "simple baselines haven't been run through this harness yet.</li>"
        )
    elif "nab" in suites:
        real_world = (
            "<li><b>An official NAB score or a baseline comparison.</b> The NAB section reports this harness's window "
            "metrics on NAB's labeled data. NAB's own score, and how simple baselines do on the same data, are separate "
            "steps.</li>"
        )
    else:
        real_world = (
            "<li><b>Real-world accuracy at scale.</b> Public labeled datasets (NAB, UCR) and comparison against baselines "
            "are listed under \"Not included in this run\" until they are part of the snapshot.</li>"
        )
    return f"""
<section>
  <h2>What this report shows, and what it doesn't</h2>
  <div class="two-col">
    <div class="card">
      <h3>Shows</h3>
      <ul>
        <li><b>Routing correctness.</b> For each failure shape (step change, trend, spikes, seasonality,
        forecastable load, mixed behavior), the router recommends the analyzer built for it.</li>
        <li><b>Detection accuracy.</b> Where a scenario declares an injected event, the analyzer is actually run
        and its finding is checked for direction, magnitude and timing.</li>
        <li><b>Quiet on healthy data.</b> A negative control of stable data must produce no user-facing alert.</li>
        <li><b>Cross-metric reasoning.</b> Correlated multi-metric scenarios must match the right behavior and never a
        forbidden one.</li>
        <li><b>Cost.</b> Time for normalization and every analyzer as data grows from 24 hours to 30 days.</li>
      </ul>
    </div>
    <div class="card">
      <h3>Doesn't show (yet)</h3>
      <ul>
        <li><b>Independence.</b> The synthetic scenarios and their answer keys were written by this project. They
        are a regression suite with known answers, not an external benchmark.</li>
        {real_world}
        <li><b>Score calibration.</b> The router's suitability weights are hand-set heuristics. This suite checks that
        the right analyzer is picked, not that a score's size tracks severity.</li>
      </ul>
    </div>
  </div>
</section>"""


def _router_section(router: dict[str, Any]) -> str:
    executable = set(router.get("executable_analyzers") or [])
    rows = []
    for item in router["scenarios"]:
        scenario = item["scenario"]
        evaluation = item["evaluation"]
        expected = _analyzer_list(item["expected_router"].get("required_recommended") or [], executable)
        recommended = _analyzer_list(evaluation["actual"].get("recommended") or [], executable)
        rows.append(
            f"<tr><td><a href='#{escape(scenario['id'])}'>{escape(scenario['name'])}</a><div class='mono small muted'>{escape(scenario['id'])}</div></td>"
            f"<td class='mono small'>{expected}</td><td class='mono small'>{recommended}</td><td>{_status_pill(evaluation['status'])}</td></tr>"
        )
    cards = "".join(_router_card(item) for item in router["scenarios"])
    return f"""
<section id="router">
  <h2>Router scenario suite</h2>
  <p class="section-lede">Each scenario is a CPU series with one known behavior built in. The router profiles the
  series, scores every registered analyzer, and must recommend the one built for that behavior without recommending
  a forbidden one. "Known gap" scenarios record a capability the router does not have yet, not a hidden failure.
  Additional recommendations beyond the required one are allowed unless a scenario opts into strict precision.</p>
  <p class="section-lede small">Analyzers marked <span class="router-only">†</span> are registered with the router but have no
  pipeline implementation yet, so recommending one does not run anything. Those scenarios validate the router's
  profiling and scoring only; the executable analyzers recommended alongside are what actually produce findings.</p>
  <div class="table-wrap"><table>
    <thead><tr><th>Scenario</th><th>Must recommend</th><th>Actually recommended</th><th>Result</th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table></div>
  <h3 class="sub">Scenario details</h3>
  <div class="cards">{cards}</div>
</section>"""


def _router_card(item: dict[str, Any]) -> str:
    scenario = item["scenario"]
    evaluation = item["evaluation"]
    profile = evaluation.get("profile") or {}
    expected_event = item.get("expected_event") or {}
    detection = evaluation.get("detection_details") or {}
    markers = []
    if expected_event.get("timestamp"):
        markers.append({"t": expected_event["timestamp"], "label": "Injected event", "kind": "expected"})
    if detection.get("detected_timestamp"):
        markers.append({"t": detection["detected_timestamp"], "label": "Detected", "kind": "detected"})

    parts = [f"<p>{escape(scenario['description'])}</p>"] if scenario.get("description") else []
    for metric, points in (item.get("series") or {}).items():
        parts.append(_line_chart(points, markers, title=f"{metric} (bucket-averaged for display)"))
    if evaluation.get("documented_gap"):
        parts.append(f"<div class='callout callout-warning'><b>Documented gap.</b> {escape(evaluation['documented_gap'])}</div>")
    if evaluation.get("execution_error"):
        parts.append(f"<div class='callout callout-critical'><b>Execution error.</b> <span class='mono'>{escape(evaluation['execution_error'])}</span></div>")

    parts.append("<div class='two-col'>")
    parts.append(f"<div><h4>Checks</h4>{_checks_list(evaluation.get('checks') or {})}{_router_diagnostics(evaluation)}</div>")
    parts.append(f"<div><h4>Series profile the router saw</h4>{_profile_table(profile)}</div>")
    parts.append("</div>")
    if detection:
        parts.append(f"<h4>Detection result</h4>{_detection_table(detection, item)}")
    parts.append(f"<h4>Every analyzer's routing decision</h4>{_decisions_table(evaluation.get('actual_details') or {})}")
    if scenario.get("notes"):
        parts.append("<h4>Scenario notes</h4><ul class='notes'>" + "".join(f"<li>{escape(note)}</li>" for note in scenario["notes"]) + "</ul>")
    parts.append(f"<p class='small muted'>Source: <span class='mono'>{escape(scenario['path'])}/</span></p>")

    return f"""
<details class="card scenario" id="{escape(scenario['id'])}">
  <summary><span class="summary-title">{escape(scenario['name'])}</span>{_status_pill(evaluation['status'])}</summary>
  <div class="card-body">{"".join(parts)}</div>
</details>"""


def _router_diagnostics(evaluation: dict[str, Any]) -> str:
    lines = []
    labels = [
        ("missing_required", "Required but not recommended"),
        ("incorrectly_recommended", "Recommended but forbidden"),
        ("missing_detected_profiles", "Expected profile not detected"),
        ("forbidden_detected_profiles", "Forbidden profile detected"),
        ("unexpected_optional", "Unexpected optional (informational)"),
    ]
    for key, label in labels:
        values = evaluation.get(key) or []
        if values:
            lines.append(f"<li><b>{escape(label)}:</b> <span class='mono'>{escape(', '.join(map(str, values)))}</span></li>")
    return f"<ul class='notes'>{''.join(lines)}</ul>" if lines else ""


def _behavior_section(behavior: dict[str, Any]) -> str:
    cards = []
    for item in behavior["scenarios"]:
        scenario = item["scenario"]
        evaluation = item["evaluation"]
        expected = item.get("expected_behavior_findings") or {}
        findings = evaluation.get("matched_findings") or []
        finding_rows = "".join(
            f"<tr><td class='mono'>{escape(str(f.get('definition_id')))}</td><td>{escape(str(f.get('title')))}</td><td>{escape(str(f.get('severity')))}</td><td class='num'>{_num(f.get('confidence'))}</td></tr>"
            for f in findings
        ) or "<tr><td colspan='4' class='muted'>No behavior matched.</td></tr>"
        charts = "".join(_line_chart(points, [], title=metric) for metric, points in (item.get("series") or {}).items())
        cards.append(f"""
<details class="card scenario" id="{escape(scenario['id'])}">
  <summary><span class="summary-title">{escape(scenario['name'])}</span>{_status_pill(evaluation['status'])}</summary>
  <div class="card-body">
    <p>{escape(scenario.get('description') or '')}</p>
    <div class="chart-grid">{charts}</div>
    <div class="two-col">
      <div><h4>Checks</h4>{_checks_list(evaluation.get('checks') or {})}</div>
      <div><h4>Expected</h4><ul class="notes">
        <li><b>Must match:</b> <span class="mono">{escape(', '.join(expected.get('required_matched') or []) or 'nothing')}</span></li>
        <li><b>Must not match:</b> <span class="mono">{escape(', '.join(expected.get('forbidden_matched') or []) or 'nothing')}</span></li>
      </ul></div>
    </div>
    <h4>Behavior findings produced</h4>
    <div class="table-wrap"><table><thead><tr><th>Definition</th><th>Title</th><th>Severity</th><th class="num">Confidence</th></tr></thead><tbody>{finding_rows}</tbody></table></div>
    {"<h4>Scenario notes</h4><ul class='notes'>" + "".join(f"<li>{escape(n)}</li>" for n in scenario.get('notes') or []) + "</ul>" if scenario.get('notes') else ""}
    <p class="small muted">Source: <span class="mono">{escape(scenario['path'])}/</span></p>
  </div>
</details>""")
    return f"""
<section id="behavior">
  <h2>Cross-metric behavior suite</h2>
  <p class="section-lede">These scenarios put several correlated metrics in one analysis window. Behavior
  Intelligence must combine signals across the metrics into the right named behavior, and must not match a behavior
  whose required metric isn't even present.</p>
  <div class="cards">{"".join(cards)}</div>
</section>"""


def _nab_section(nab: dict[str, Any], official_nab: dict[str, Any] | None = None) -> str:
    settings = nab["settings"]
    headline = str(settings["headline_threshold"])
    overall = nab["overall"]
    replay, batch = overall["replay"][headline], overall["batch"][headline]
    commit = nab["nab"]["commit"]

    stats = "".join(
        _tile(label, value, caption, None)
        for label, value, caption in [
            ("Windows detected", f"{replay['detected_windows']}<span class='of'>/{replay['windows']}</span>", f"window recall {_pct(replay['window_recall'])}"),
            ("Alarm precision", _pct(replay["alarm_precision"]), f"{replay['alarms_in_windows']:,} of {replay['alarms']:,} alarms inside a labeled window"),
            ("False alarms", f"{replay['false_alarms']:,}", f"across {len(nab['series'])} series, after the probationary period"),
            ("Median detection point", _pct(replay["median_detection_position"]), "how far into a window its first alarm lands (0% = at the window's start)"),
        ]
    )

    sweep_rows = []
    for mode in ("replay", "batch"):
        for threshold, row in overall[mode].items():
            emphasis = " class='emph'" if threshold == headline else ""
            sweep_rows.append(
                f"<tr{emphasis}><td>{'Replay (causal)' if mode == 'replay' else 'Batch (sees whole series)'}</td><td class='num'>≥ {escape(threshold)}</td>"
                f"<td class='num'>{row['detected_windows']}/{row['windows']}</td><td class='num'>{_pct(row['window_recall'])}</td>"
                f"<td class='num'>{_pct(row['alarm_precision'])}</td><td class='num'>{_num(row['f1'])}</td>"
                f"<td class='num'>{row['alarms']:,}</td><td class='num'>{row['false_alarms']:,}</td></tr>"
            )

    category_rows = []
    for category, by_mode in nab["categories"].items():
        r, b = by_mode["replay"], by_mode["batch"]
        category_rows.append(
            f"<tr><td class='mono'>{escape(category)}</td><td class='num'>{r['windows']}</td>"
            f"<td class='num'>{r['detected_windows']}</td><td class='num'>{_pct(r['alarm_precision'])}</td><td class='num'>{r['false_alarms']:,}</td>"
            f"<td class='num'>{b['detected_windows']}</td><td class='num'>{_pct(b['alarm_precision'])}</td><td class='num'>{b['false_alarms']:,}</td></tr>"
        )

    series_rows = []
    series_cards = []
    for item in nab["series"]:
        r = item["modes"]["replay"]["headline"]
        b = item["modes"]["batch"]["headline"]
        flags = []
        if item.get("validation_warnings"):
            flags.append("<span class='pill pill-warning' title='Large timestamp gap kept under gap_policy=warn'>gap</span>")
        if item.get("batch_error") or item.get("replay_errors"):
            flags.append("<span class='pill pill-critical'>error</span>")
        anchor = "nab-" + item["series"].replace("/", "-").replace(".csv", "")
        windows_cell = lambda counts: f"{counts['detected_windows']}/{counts['windows']}" if counts["windows"] else "<span class='muted'>none labeled</span>"
        series_rows.append(
            f"<tr><td><a href='#{escape(anchor)}' class='mono small'>{escape(item['series'])}</a> {' '.join(flags)}</td>"
            f"<td class='num'>{item['rows']:,}</td><td class='num'>{item['interval_minutes']}m</td>"
            f"<td class='num'>{windows_cell(r)}</td><td class='num'>{r['false_alarms']}</td>"
            f"<td class='num'>{windows_cell(b)}</td><td class='num'>{b['false_alarms']}</td></tr>"
        )
        alarms = [a for a in item["modes"]["replay"]["alarm_times"] if a[1] >= float(headline)]
        batch_alarms = [a for a in item["modes"]["batch"]["alarm_times"] if a[1] >= float(headline)]
        chart = _line_chart(
            item["plot"],
            [],
            title=f"{item['series']} · replay alarms at confidence ≥ {headline}",
            bands=[(w[0].replace(" ", "T"), w[1].replace(" ", "T")) for w in item["windows"]],
            shade=(item["plot"][0][0], item["probation_end"]),
            ticks=alarms,
        )
        batch_chart = _line_chart(
            item["plot"],
            [],
            title=f"Batch alarms at confidence ≥ {headline}, for comparison",
            bands=[(w[0].replace(" ", "T"), w[1].replace(" ", "T")) for w in item["windows"]],
            shade=(item["plot"][0][0], item["probation_end"]),
            ticks=batch_alarms,
        )
        routing = "".join(
            f"<tr><td class='mono'>{escape(str(d['analyzer']))}</td><td>{escape(str(d['recommendation']).replace('_', ' ').lower())}</td><td class='num'>{_num(d['score'])}</td></tr>"
            for d in sorted(item["routing"], key=lambda d: -(d["score"] or 0))
        )
        notes = []
        for warning in item.get("validation_warnings") or []:
            notes.append(f"<li>Ingestion warning, series kept: <span class='mono'>{escape(warning)}</span></li>")
        if item.get("batch_error"):
            notes.append(f"<li>Batch run failed: <span class='mono'>{escape(item['batch_error'])}</span></li>")
        if item.get("replay_errors"):
            notes.append(f"<li>{item['replay_errors']} of {item['replay_runs']} replay runs failed; first: <span class='mono'>{escape(str(item['first_replay_error']))}</span></li>")
        series_cards.append(f"""
<details class="card scenario" id="{escape(anchor)}">
  <summary><span class="summary-title mono small">{escape(item['series'])}</span>
  <span class="small muted">replay {windows_cell(r)} windows · {r['false_alarms']} false alarms</span></summary>
  <div class="card-body">
    {chart}
    {batch_chart}
    <div class="two-col">
      <div><h4>This series</h4><div class="table-wrap"><table class="kv"><tbody>
        <tr><th scope="row">Rows</th><td class="num">{item['rows']:,}</td></tr>
        <tr><th scope="row">Sampling interval used</th><td class="num">{item['interval_minutes']} min</td></tr>
        <tr><th scope="row">Probationary rows (not scored)</th><td class="num">{item['probation_rows']:,}</td></tr>
        <tr><th scope="row">Labeled windows</th><td class="num">{len(item['windows'])}</td></tr>
        <tr><th scope="row">Analyzers run (whole-series routing)</th><td class="mono small">{escape(', '.join(item['executed_analyzers']) or 'none')}</td></tr>
        <tr><th scope="row">Replay runs</th><td class="num">{item['replay_runs']:,}</td></tr>
        <tr><th scope="row">Replay: alarms / false alarms</th><td class="num">{r['alarms']} / {r['false_alarms']}</td></tr>
        <tr><th scope="row">Batch: alarms / false alarms</th><td class="num">{b['alarms']} / {b['false_alarms']}</td></tr>
      </tbody></table></div>
      {"<ul class='notes'>" + "".join(notes) + "</ul>" if notes else ""}</div>
      <div><h4>Router decisions on the whole series</h4><div class="table-wrap scroll-y"><table><thead><tr><th>Analyzer</th><th>Decision</th><th class="num">Score</th></tr></thead><tbody>{routing}</tbody></table></div></div>
    </div>
  </div>
</details>""")

    official = _nab_official(nab, official_nab) if official_nab else f"""<div class="callout callout-warning"><b>Official NAB score: not computed in this snapshot.</b> The numbers in
this section are this harness's window metrics, not NAB's score, which also weights how early in a window a detection lands and
applies three cost profiles. NAB-format result files for both detectors
(<span class="mono">{escape(nab['detector_names']['replay'])}</span>, <span class="mono">{escape(nab['detector_names']['batch'])}</span>)
are written to <span class="mono">raw/nab_results/</span> in this snapshot, in the layout NAB's scorer reads. To score them with NAB's own
scorer, run <span class="mono">python -m benchmark.nab.official_score &lt;this snapshot&gt;</span>.</div>"""

    return f"""
<section id="nab">
  <h2>Numenta Anomaly Benchmark (NAB)</h2>
  <p class="section-lede">NAB is a public corpus of {len(nab['series'])} real and artificial time series (AWS CloudWatch metrics, ad
  exchange, sensors, traffic, taxi demand, Twitter volume) with {replay['windows'] if replay['windows'] else ''} labeled anomaly windows,
  published by Numenta in 2015. The labels were set by NAB's authors, not by this project. Pinned to commit
  <span class="mono">{escape(commit[:12])}</span> of <span class="mono">{escape(nab['nab']['repository'])}</span>. Every series goes through
  the same analysis path as a CSV upload with the <span class="mono">{escape(settings['provider'])}</span> provider: validation, routing,
  the analyzers the router selects, and scoring.</p>
  {official}
  <h3 class="sub">Headline: replay mode, alarms at confidence ≥ {escape(headline)}</h3>
  <div class="tiles">{stats}</div>
  <p class="small muted">The {escape(headline)} threshold was fixed before scoring and is not tuned per series or per dataset. The sweep
  below shows every threshold, so nothing depends on that choice being favorable.</p>

  <div class="two-col explain">
    <div class="card"><h3>Replay mode (causal, counts toward the headline)</h3><p>A trailing window of up to
    {settings['replay_window_rows']:,} rows is analyzed every {settings['replay_step_rows']} new rows, the way a scheduled production run
    would. An alarm lands on the row where that run happens, which is the first moment the event could have been known. Each event alarms
    once. This follows NAB's rule that a detector may only use data up to the point it's scoring.</p></div>
    <div class="card"><h3>Batch mode (shown for comparison only)</h3><p>The whole series is analyzed at once, and an alarm lands where
    the detected event starts. Detectors see data after the alarm, which NAB's rules don't allow, so batch results show the
    analyzers' offline ceiling and aren't comparable with NAB's published scores.</p></div>
  </div>

  <h3 class="sub">Every threshold</h3>
  <div class="table-wrap"><table>
    <thead><tr><th>Mode</th><th class="num">Confidence</th><th class="num">Windows</th><th class="num">Window recall</th>
    <th class="num">Alarm precision</th><th class="num">F1</th><th class="num">Alarms</th><th class="num">False alarms</th></tr></thead>
    <tbody>{"".join(sweep_rows)}</tbody>
  </table></div>

  <h3 class="sub">By NAB category, at confidence ≥ {escape(headline)}</h3>
  <div class="table-wrap"><table>
    <thead><tr><th rowspan="2">Category</th><th rowspan="2" class="num">Windows</th><th colspan="3" class="num">Replay (causal)</th><th colspan="3" class="num">Batch</th></tr>
    <tr><th class="num">Detected</th><th class="num">Precision</th><th class="num">False alarms</th><th class="num">Detected</th><th class="num">Precision</th><th class="num">False alarms</th></tr></thead>
    <tbody>{"".join(category_rows)}</tbody>
  </table></div>

  {_nab_undetected(nab)}
  <h3 class="sub">Every series</h3>
  <p class="small muted">"gap" marks a series with a timestamp gap over the provider's limit; it is analyzed anyway under
  <span class="mono">gap_policy: warn</span>. Series in <span class="mono">artificialNoAnomaly</span> have no labeled windows, so any alarm there is false.</p>
  <div class="table-wrap scroll-y tall-scroll"><table>
    <thead><tr><th>Series</th><th class="num">Rows</th><th class="num">Interval</th><th class="num">Replay windows</th>
    <th class="num">Replay false alarms</th><th class="num">Batch windows</th><th class="num">Batch false alarms</th></tr></thead>
    <tbody>{"".join(series_rows)}</tbody>
  </table></div>

  <h3 class="sub">Series details</h3>
  <div class="cards">{"".join(series_cards)}</div>

  <h3 class="sub">Method notes</h3>
  <ul class="notes">
    <li>A signal becomes an alarm scored with the signal's own confidence. Signals that span a whole analysis window, such as a trend or
    forecast fit, never alarm in replay mode and fall in the unscored probationary period in batch mode.</li>
    <li>The first min(15% of rows, 750) rows of each series are NAB's probationary period, and alarms there are ignored, as in NAB.</li>
    <li>A window counts as detected when any alarm falls inside it. Later alarms in the same window are neither rewarded nor
    penalized. Every alarm outside all windows counts as a false alarm.</li>
    <li>Per-series inputs a user would set on upload: the resampling interval is the series' median sampling interval, and negative
    values are allowed (one artificial series has them). Everything else is the provider's default configuration.</li>
    <li>Harness code: <span class="mono">benchmark/nab/</span>. Only NAB's data and labels are used; none of NAB's code is run.</li>
  </ul>
</section>"""


NAB_PROFILES = [("standard", "Standard"), ("reward_low_FP_rate", "Fewer false alarms"), ("reward_low_FN_rate", "Fewer misses")]
NAB_REFERENCE_DETECTOR = "numenta"
EMPHASIS_CLASS = ' class="emph"'


def _nab_official(nab: dict[str, Any], official: dict[str, Any]) -> str:
    final, published, totals = official["final"], official["published"], official["totals"]
    ours = {nab["detector_names"]["replay"]: "Ops Signals, replay (causal)", nab["detector_names"]["batch"]: "Ops Signals, batch (sees whole series)"}

    board = [(name, scores, False) for name, scores in published.items()]
    board += [(name, final[name], True) for name in ours if name in final]
    board.sort(key=lambda item: -float(item[1].get("standard", 0)))
    rows = "".join(
        f"<tr{EMPHASIS_CLASS if is_ours else ''}><td>{escape(ours.get(name, name))}</td>"
        + "".join(f"<td class='num'>{float(scores.get(key, 0)):.1f}</td>" for key, _ in NAB_PROFILES)
        + "</tr>"
        for name, scores, is_ours in board
    )

    check = ""
    reference, published_reference = final.get(NAB_REFERENCE_DETECTOR), published.get(NAB_REFERENCE_DETECTOR)
    if reference and published_reference:
        deltas = [abs(float(reference[key]) - float(published_reference[key])) for key, _ in NAB_PROFILES]
        cells = " · ".join(
            f"{label}: {float(reference[key]):.2f} re-scored vs {float(published_reference[key]):.2f} published"
            for key, label in NAB_PROFILES
        )
        verdict = "matches" if max(deltas) < 0.5 else "does NOT match"
        check = f"""<p class="small"><b>Scorer check:</b> Numenta's published detector was re-scored in the same run and
{verdict} its published result ({escape(cells)}), so this environment scores the way NAB's published scoreboard was scored.</p>"""

    count_rows = []
    for name, label in ours.items():
        for key, profile_label in NAB_PROFILES:
            row = (totals.get(name) or {}).get(key)
            if not row:
                continue
            no_alarms = row["threshold"] > 1.0
            threshold = "none - raising no alarm scored best" if no_alarms else f"{row['threshold']:.3f}"
            count_rows.append(
                f"<tr><td>{escape(label)}</td><td>{escape(profile_label)}</td><td class='num'>{escape(threshold)}</td>"
                f"<td class='num'>{int(row['TP']):,}</td><td class='num'>{int(row['FP']):,}</td><td class='num'>{float(final.get(name, {}).get(key, 0)):.1f}</td></tr>"
            )
    counts = ""
    if count_rows:
        counts = f"""<h4>What NAB's optimizer chose for each profile</h4>
<p class="small muted">NAB picks each detector's alert threshold to maximize its score, separately per profile. When no threshold beats
raising no alarm at all, the best choice is to alarm on nothing, and the normalized score is 0 - the same as NAB's "null" detector. TP and FP
are NAB's own row counts at that threshold (only the first detection in a window earns credit).</p>
<div class="table-wrap"><table><thead><tr><th>Detector</th><th>Profile</th><th class="num">Chosen threshold</th><th class="num">TP rows</th>
<th class="num">FP rows</th><th class="num">Score</th></tr></thead><tbody>{''.join(count_rows)}</tbody></table></div>"""

    return f"""<div class="card">
<h3>Official NAB score</h3>
<p class="small muted">Scored by NAB's own, unmodified scorer (<span class="mono">run.py --optimize --score --normalize</span>) at the pinned
commit, in a separate environment. 100 is perfect detection; 0 is the score of never raising an alarm. The published rows come from NAB's
scoreboard at the pinned commit.</p>
<div class="table-wrap"><table><thead><tr><th>Detector</th>{''.join(f"<th class='num'>{escape(label)}</th>" for _, label in NAB_PROFILES)}</tr></thead>
<tbody>{rows}</tbody></table></div>
{check}
{counts}
</div>
<p class="small muted">Everything below this point is this harness's own window metrics, which count caught windows and false alarms directly
without NAB's early-detection weighting.</p>"""

def _nab_undetected(nab: dict[str, Any]) -> str:
    """Series where the router ran no detector at all - only data_health, or nothing. Their zero
    alarms mean nothing was looked at, not that nothing was wrong, so they're named explicitly."""
    unanalyzed = [item for item in nab["series"] if not set(item["executed_analyzers"]) - {"data_health"}]
    if not unanalyzed:
        return ""
    rows = []
    for item in unanalyzed:
        reasons = sorted({str(d.get("reason")) for d in item["routing"] if d.get("recommendation") == "REJECTED" and d.get("reason")})
        windows = len(item["windows"])
        rows.append(
            f"<tr><td class='mono small'>{escape(item['series'])}</td><td class='num'>{windows}</td>"
            f"<td class='small'>{escape('; '.join(reasons) or 'No detector scored high enough to run.')}</td></tr>"
        )
    missed = sum(len(item["windows"]) for item in unanalyzed)
    return f"""<div class="callout callout-critical"><b>{len(unanalyzed)} series got no anomaly detector at all</b>, so their
{missed} labeled windows count as missed. Their silence is a coverage gap, not a clean bill of health.</div>
<div class="table-wrap"><table><thead><tr><th>Series</th><th class="num">Windows</th><th>Router's reason for rejecting the detectors</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>"""


def _pct(value: Any) -> str:
    return "-" if value is None else f"{float(value) * 100:.1f}%"


def _tcpd_section(tcpd: dict[str, Any]) -> str:
    validation = tcpd["validation"]
    series = tcpd["series"]
    evaluated = len(tcpd["evaluated"])
    full_published = tcpd.get("leaderboard_full_published") or {}

    board_rows = []
    for row in tcpd["leaderboard"]:
        full = full_published.get(row["method"]) if not row["ours"] else None
        reference = f"{full['f1']:.3f} / {full['cover']:.3f}" if full else "-"
        board_rows.append(
            f"<tr{EMPHASIS_CLASS if row['ours'] else ''}><td>{escape(row['method'])}</td>"
            f"<td class='num'>{row['f1']:.3f}</td><td class='num'>{row['cover']:.3f}</td><td class='num muted'>{reference}</td></tr>"
        )

    ran_change = [s for s in series if set(s["executed_analyzers"]) & set(tcpd["settings"]["change_signal_types"])]
    reported = [s for s in series if s["product_cps"]]
    multi = [s for s in series if sorted(s["annotated_cp_counts"])[len(s["annotated_cp_counts"]) // 2] > 1]
    direct_silent_agreed = [
        s["series"] for s in series
        if not s["direct_cps"] and sum(1 for count in s["annotated_cp_counts"] if count > 0) >= 3
    ]
    findings = [
        f"<li><b>The router ran a change-point analyzer on {len(ran_change)} of {evaluated} series</b>, and the product reported a change point on "
        f"{len(reported)}. On the rest it reported none, which TCPD scores the same as the \"zero\" method.</li>",
        f"<li><b>At most one change point per series.</b> <span class='mono'>ruptures</span> and <span class='mono'>baseline_shift</span> report the primary shift only. "
        f"On {len(multi)} of {evaluated} series the median annotator marked more than one, so recall there is capped by design.</li>",
    ]
    if direct_silent_agreed:
        findings.append(
            "<li><b>Clear shifts can fall under the detection threshold.</b> A change point is kept only when the shift in means, divided by the whole "
            "series' standard deviation, reaches 1.5. That standard deviation includes the shift itself, so even a noise-free step can't score above 2.0, "
            "and only when it sits mid-series. Series where the detector reported nothing although at least three of five annotators marked a change: "
            f"<span class='mono'>{escape(', '.join(direct_silent_agreed))}</span>.</li>"
        )
    if tcpd["unavailable"]:
        findings.append(
            f"<li><b>{len(tcpd['unavailable'])} of the paper's {tcpd['evaluation_set_size']} series aren't included</b>: "
            f"<span class='mono'>{escape(', '.join(tcpd['unavailable']))}</span>. TCPD builds them with download scripts, which this harness "
            "doesn't run. Every method in the table is averaged over the same "
            f"{evaluated} series, so the comparison is like for like; the last column gives the paper's own averages over all "
            f"{tcpd['evaluation_set_size']} for reference.</li>"
        )

    detail_rows = []
    cards = []
    for item in series:
        product, direct = item["scores"]["product"], item["scores"]["direct"]
        published_f1 = {k: v for k, v in (item["published"].get("f1") or {}).items() if v is not None}
        best_method = max(published_f1, key=published_f1.get) if published_f1 else None
        counts = item["annotated_cp_counts"]
        anchor = f"tcpd-{item['series']}"
        detail_rows.append(
            f"<tr><td><a href='#{escape(anchor)}' class='mono small'>{escape(item['series'])}</a></td><td class='num'>{item['n_obs']}</td>"
            f"<td class='num'>{min(counts)}-{max(counts)}</td>"
            f"<td class='num mono small'>{escape(', '.join(map(str, item['product_cps'])) or '-')}</td><td class='num'>{product['f1']:.2f}</td>"
            f"<td class='num mono small'>{escape(', '.join(map(str, item['direct_cps'])) or '-')}</td><td class='num'>{direct['f1']:.2f}</td>"
            f"<td class='num'>{_num(published_f1.get('zero'))}</td>"
            f"<td class='num'>{f'{published_f1[best_method]:.2f} <span class=muted>{escape(best_method)}</span>' if best_method else '-'}</td></tr>"
        )
        plot = item["plot"]
        by_row = {int(point[2].split()[1]): point[0] for point in plot}
        rows_sorted = sorted(by_row)

        def at(row: int) -> str:
            nearest = min(rows_sorted, key=lambda r: abs(r - row))
            return by_row[nearest]

        markers = [
            {"t": at(cp), "kind": "expected", "label": "", "text": "Annotator change point"}
            for cp in sorted({cp for cps in item["annotations"].values() for cp in cps})
        ]
        markers += [{"t": at(cp), "kind": "detected", "label": "", "text": f"Ops Signals (product): row {cp}"} for cp in item["product_cps"]]
        markers += [
            {"t": at(cp), "kind": "direct", "label": "", "text": f"ruptures direct: row {cp}"}
            for cp in item["direct_cps"] if cp not in item["product_cps"]
        ]
        chart = _line_chart(plot, markers, title=f"{item['long_name']} ({item['n_obs']} observations)", x_labels=("row 0", f"row {item['n_obs'] - 1}"))
        annotator_rows = "".join(
            f"<tr><td class='mono small'>annotator {escape(str(uid))}</td><td class='mono small'>{escape(', '.join(map(str, cps)) or 'no change')}</td></tr>"
            for uid, cps in item["annotations"].items()
        )
        routing = "".join(
            f"<tr><td class='mono'>{escape(str(d['analyzer']))}</td><td>{escape(str(d['recommendation']).replace('_', ' ').lower())}</td><td class='num'>{_num(d['score'])}</td>"
            f"<td class='small'>{escape(str(d.get('reason') or ''))}</td></tr>"
            for d in sorted(item["routing"], key=lambda d: -(d["score"] or 0))
        )
        errors = "".join(
            f"<li>{label} failed: <span class='mono'>{escape(error)}</span></li>"
            for label, error in (("Product run", item.get("product_error")), ("Direct run", item.get("direct_error"))) if error
        )
        cards.append(f"""
<details class="card scenario" id="{escape(anchor)}">
  <summary><span class="summary-title mono small">{escape(item['series'])}</span>
  <span class="small muted">product F1 {product['f1']:.2f} · direct {direct['f1']:.2f} · zero {_num(published_f1.get('zero'))}</span></summary>
  <div class="card-body">
    {chart}
    {f"<ul class='notes'>{errors}</ul>" if errors else ""}
    <div class="two-col">
      <div><h4>Scores</h4><div class="table-wrap"><table><thead><tr><th></th><th class="num">F1</th><th class="num">Precision</th><th class="num">Recall</th><th class="num">Cover</th></tr></thead><tbody>
        <tr><td>Product</td><td class="num">{product['f1']:.3f}</td><td class="num">{_num(product['precision'])}</td><td class="num">{_num(product['recall'])}</td><td class="num">{product['cover']:.3f}</td></tr>
        <tr><td>ruptures direct</td><td class="num">{direct['f1']:.3f}</td><td class="num">{_num(direct['precision'])}</td><td class="num">{_num(direct['recall'])}</td><td class="num">{direct['cover']:.3f}</td></tr>
      </tbody></table></div>
      <h4>Annotators' change points (row)</h4><div class="table-wrap"><table><tbody>{annotator_rows}</tbody></table></div></div>
      <div><h4>Router decisions</h4><div class="table-wrap scroll-y"><table><thead><tr><th>Analyzer</th><th>Decision</th><th class="num">Score</th><th>Reason</th></tr></thead><tbody>{routing}</tbody></table></div></div>
    </div>
  </div>
</details>""")

    averages = validation["published_averages_recomputed"]
    return f"""
<section id="tcpd">
  <h2>Turing Change Point Dataset (TCPD)</h2>
  <p class="section-lede">TCPD is a set of real-world series (economics, energy, transport, population, sensor data) where five annotators
  independently marked the change points, published with an evaluation of 14 change-point methods (van den Burg &amp; Williams, 2020). The
  labels and the other methods' results are theirs, not this project's. Scored with the paper's F1 (a predicted change point counts when it is
  within {tcpd['settings']['margin']} rows of an annotated one) and covering (how well the predicted segments line up with each annotator's).
  Both reward a method for staying silent on series with no change, which is why "zero", which never predicts a change, scores well. Pinned to
  TCPD <span class="mono">{escape(tcpd['tcpd']['commit'][:12])}</span> and TCPDBench <span class="mono">{escape(tcpd['tcpdbench']['commit'][:12])}</span>.</p>

  <div class="callout callout-good"><b>Scoring verified before use.</b> TCPD's metrics were ported from TCPDBench, and every published score in its
  summaries was recomputed from the published change points: {validation['scores_checked']:,} scores, {validation['mismatches']} mismatches (largest
  difference {validation['worst_difference']:.1e}). The paper's published averages were reproduced from its per-series scores (binseg F1
  {averages['binseg']['f1']:.3f}, cover {averages['binseg']['cover']:.3f}; zero F1 {averages['zero']['f1']:.3f}, cover {averages['zero']['cover']:.3f}).</div>

  <h3 class="sub">All methods on the same {evaluated} series</h3>
  <p class="small muted">Published methods use their default parameters (the paper's "default" experiment, no per-series tuning), the fair
  comparison for Ops Signals' default configuration. "Product" is what a user gets: the router decides whether a change-point analyzer runs.
  "Direct" runs <span class="mono">{escape(tcpd['settings']['direct_analyzer'])}</span> on every series. Differences of a few hundredths
  across {evaluated} series are within noise.</p>
  <div class="table-wrap"><table>
    <thead><tr><th>Method</th><th class="num">F1</th><th class="num">Cover</th><th class="num">Paper's average over all {tcpd['evaluation_set_size']} (F1 / cover)</th></tr></thead>
    <tbody>{''.join(board_rows)}</tbody>
  </table></div>

  <h3 class="sub">What the results show</h3>
  <ul class="notes findings">{''.join(findings)}</ul>

  <h3 class="sub">Every series</h3>
  <div class="table-wrap scroll-y tall-scroll"><table>
    <thead><tr><th>Series</th><th class="num">Rows</th><th class="num">Annotated CPs</th><th class="num">Product CPs</th><th class="num">Product F1</th>
    <th class="num">Direct CPs</th><th class="num">Direct F1</th><th class="num">Zero F1</th><th class="num">Best published F1</th></tr></thead>
    <tbody>{''.join(detail_rows)}</tbody>
  </table></div>

  <h3 class="sub">Series details</h3>
  <div class="cards">{''.join(cards)}</div>

  <h3 class="sub">Method notes</h3>
  <ul class="notes">
    <li>Change points are read from <span class="mono">{escape(', '.join(tcpd['settings']['change_signal_types']))}</span> signals. Other analyzers'
    signals (trends, forecasts, anomalies) aren't change points and aren't scored here.</li>
    <li>Each series gets a synthetic daily timestamp so every row maps to one resampled bucket; TCPD scores by row, so the dates don't matter.</li>
    <li>A run that fails scores 0 on that series, as in the paper. Harness code: <span class="mono">benchmark/tcpd/</span>. Only data files are read
    from TCPD and TCPDBench; none of their code is run.</li>
  </ul>
</section>"""


UCR_METHOD_LABELS = {
    "product": ("Ops Signals (product)", "What a user gets: the router picks the analyzers, the top-ranked finding is the answer."),
    "anomaly_zscore": ("anomaly_zscore, direct", "One production analyzer on every series, most confident signal."),
    "pyod_outlier": ("pyod_outlier, direct", "One production analyzer on every series, most confident signal."),
    "seasonal_anomaly": ("seasonal_anomaly, direct", "One production analyzer on every series, most confident signal."),
    "discord": ("Matrix-profile discord (reference)", "Textbook subsequence method, not an Ops Signals analyzer."),
    "max_jump": ("Largest single jump (trivial baseline)", "A one-liner: the biggest point-to-point change in the test part."),
}


def _ucr_section(ucr: dict[str, Any]) -> str:
    summary = ucr["summary"]
    overall = summary["overall"]
    series = ucr["series"]
    total = overall["series"]
    methods = ucr["settings"]["methods"]
    ranked = sorted(methods, key=lambda m: -overall[m]["correct"])

    board_rows = []
    for method in ranked:
        stats = overall[method]
        label, note = UCR_METHOD_LABELS.get(method, (method, ""))
        found = f"{stats['found_anywhere']}" if method not in ("discord", "max_jump") else "-"
        board_rows.append(
            f"<tr{EMPHASIS_CLASS if method == 'product' else ''}><td>{escape(label)}<div class='small muted'>{escape(note)}</div></td>"
            f"<td class='num'>{stats['correct']}<span class='muted'>/{total}</span></td><td class='num'>{_pct(stats['correct'] / total if total else None)}</td>"
            f"<td class='num'>{stats['answered']}</td><td class='num'>{found}</td>"
            f"<td class='num'>{stats['timeouts'] or '-'}</td><td class='num'>{stats['errors'] or '-'}</td></tr>"
        )
    expected_dart = overall["default_rate"] * total
    board_rows.append(
        f"<tr><td>Random guess in the test part (expected)<div class='small muted'>The archive's \"random dart\" default rate, computed from each series' labels.</div></td>"
        f"<td class='num'>{expected_dart:.1f}<span class='muted'>/{total}</span></td><td class='num'>{_pct(overall['default_rate'])}</td>"
        "<td class='num'>-</td><td class='num'>-</td><td class='num'>-</td><td class='num'>-</td></tr>"
    )
    bars = _bar_chart(
        [(UCR_METHOD_LABELS.get(m, (m,))[0], overall[m]["correct"] / total * 100 if total else 0.0) for m in methods]
        + [("Random guess (expected)", overall["default_rate"] * 100)],
        unit="%",
        title=f"Share of the {total} series where the answer was in the correct region",
    )

    product = overall["product"]
    product_rows = [s["methods"]["product"] for s in series]
    ranked_lower = product["found_anywhere"] - product["correct"]
    silent = sum(1 for m in product_rows if m["status"] == "no_answer")
    point_analyzers = {"anomaly_zscore", "pyod_outlier", "seasonal_anomaly"}
    ran_point = sum(1 for m in product_rows if point_analyzers & set(m.get("executed_analyzers") or []))
    executed_counts: dict[str, int] = {}
    for m in product_rows:
        for analyzer in m.get("executed_analyzers") or []:
            executed_counts[analyzer] = executed_counts.get(analyzer, 0) + 1
    executed_text = ", ".join(f"<span class='mono'>{escape(a)}</span> {n}" for a, n in sorted(executed_counts.items(), key=lambda kv: -kv[1]))
    discord = overall["discord"]
    both = sum(1 for s in series if s["methods"]["product"]["correct"] and s["methods"]["discord"]["correct"])
    discord_only = sum(1 for s in series if s["methods"]["discord"]["correct"] and not s["methods"]["product"]["correct"])
    product_only = sum(1 for s in series if s["methods"]["product"]["correct"] and not s["methods"]["discord"]["correct"])
    findings = [
        f"<li><b>The product answered {product['correct']} of {total} correctly ({_pct(product['correct'] / total if total else None)})</b>; the matrix-profile "
        f"discord reference answered {discord['correct']}. Both were right on {both}; the discord only on {discord_only}; the product only on {product_only}.</li>",
        f"<li><b>Right place, wrong rank on {ranked_lower} series.</b> The product listed a finding inside the correct region but ranked another one first. "
        "UCR scores only the top answer.</li>",
        f"<li><b>No localized finding after the training part on {silent} series.</b> The router ran a point-anomaly analyzer "
        f"(<span class='mono'>anomaly_zscore</span>, <span class='mono'>pyod_outlier</span> or <span class='mono'>seasonal_anomaly</span>) on {ran_point} of {total}. "
        f"Analyzers run, by number of series: {executed_text or 'none'}.</li>",
        "<li><b>Most UCR anomalies are shapes, not values.</b> A reversed heartbeat, a slowed gait cycle or a smoothed stretch stays inside the normal "
        "value range, so point detectors can't see it. Finding it needs a subsequence method such as a discord. The product's "
        "<span class='mono'>stumpy</span> analyzer computes a matrix profile but reports repeated patterns (motifs), not unusual ones, so it gives no location here.</li>",
        f"<li><b>{overall['max_jump']['correct']} of {total} series are solved by the largest single jump.</b> Wu &amp; Keogh designed the archive to avoid "
        "one-liner solutions, and this shows how much of it still yields to one.</li>",
    ]
    timeouts = [(s, m) for s in series for m, o in s["methods"].items() if o["status"] == "timeout"]
    if timeouts:
        by_method: dict[str, list[int]] = {}
        for s, m in timeouts:
            by_method.setdefault(m, []).append(s["n_points"])
        detail = "; ".join(f"<span class='mono'>{escape(m)}</span> on {len(sizes)} (from {min(sizes):,} points)" for m, sizes in sorted(by_method.items()))
        findings.append(
            f"<li><b>Some runs didn't finish within {ucr['settings']['task_timeout_seconds']:.0f} seconds</b> and score as no answer: {detail}. "
            "Most UCR series are far longer than a typical metric window.</li>"
        )

    def group_table(title: str, groups: dict[str, Any]) -> str:
        head = "".join(f"<th class='num'>{escape(UCR_METHOD_LABELS.get(m, (m,))[0].split(' (')[0].split(',')[0])}</th>" for m in methods)
        body = "".join(
            f"<tr><td>{escape(name)}</td><td class='num'>{g['series']}</td>"
            + "".join(f"<td class='num'>{g[m]['correct']}</td>" for m in methods)
            + f"<td class='num muted'>{g['default_rate'] * g['series']:.1f}</td></tr>"
            for name, g in sorted(groups.items(), key=lambda kv: -kv[1]["series"])
        )
        return (
            f"<h3 class='sub'>{escape(title)}</h3><div class='table-wrap'><table><thead><tr><th></th><th class='num'>Series</th>{head}"
            f"<th class='num'>Random (expected)</th></tr></thead><tbody>{body}</tbody></table></div>"
        )

    def mark(o: dict[str, Any]) -> str:
        if o["status"] == "timeout":
            return "<span class='muted' title='did not finish in time'>timeout</span>"
        if o["status"] == "error":
            return f"<span class='muted' title='{escape(o.get('error') or '')}'>error</span>"
        if o["position"] is None:
            return "<span class='muted'>-</span>"
        icon = "<span class='ok-mark'>✓</span>" if o["correct"] else "<span class='bad-mark'>✕</span>"
        return f"{icon} <span class='mono small'>{o['position']:,}</span>"

    detail_rows = []
    cards = []
    for s in series:
        anchor = f"ucr-{s['number']}"
        detail_rows.append(
            f"<tr><td class='num'><a href='#{anchor}'>{s['number']}</a></td><td class='mono small'>{escape(s['name'])}</td><td class='small'>{escape(s['domain'])}</td>"
            f"<td class='num'>{s['n_points']:,}</td><td class='num mono small'>{s['begin']:,}-{s['end']:,}</td>"
            + "".join(f"<td class='num nowrap'>{mark(s['methods'][m])}</td>" for m in methods)
            + "</tr>"
        )
        cards.append(_ucr_card(s, methods))

    archive = ucr["archive"]
    return f"""
<section id="ucr">
  <h2>UCR Time Series Anomaly Archive</h2>
  <p class="section-lede">{archive['series']} real and semi-synthetic series (ECG, blood pressure, gait, respiration, insect feeding, power demand,
  NASA telemetry and more), each with exactly one anomaly, built by Wu &amp; Keogh (2021) to fix the flaws they found in earlier benchmarks,
  including NAB: trivial anomalies, wrong labels, and anomalies clustered at the end. The first part of each series is guaranteed normal; every
  method is told there is one anomaly after it and gives one location. Scored with the archive's own rule: with L the anomaly's length, an answer
  is correct if it falls between min(begin&minus;L, begin&minus;{ucr['settings']['min_slack']}) and max(end+L, end+{ucr['settings']['min_slack']}).
  The labels are the archive's, not this project's. Archive pinned by SHA-256 <span class="mono">{escape(archive['sha256'][:16])}…</span>.</p>

  <h3 class="sub">All methods on the same {total} series</h3>
  {bars}
  <div class="table-wrap"><table>
    <thead><tr><th>Method</th><th class="num">Correct</th><th class="num">Accuracy</th><th class="num">Answered</th>
    <th class="num">In its list</th><th class="num">Timeouts</th><th class="num">Errors</th></tr></thead>
    <tbody>{''.join(board_rows)}</tbody>
  </table></div>
  <p class="small muted">"In its list" counts series where any of the method's findings after the training part was in the correct region, not
  only the top one. It shows what ranking costs; it is not the UCR score.</p>

  <h3 class="sub">What the results show</h3>
  <ul class="notes findings">{''.join(findings)}</ul>

  {group_table("By domain (correct answers)", summary['by_domain'])}
  {group_table("By variant (correct answers)", summary['by_variant'])}
  <p class="small muted">"distorted" and "noise" series are copies of other series in the archive with smoothed noise or extra noise added, so they
  aren't independent of the originals.</p>

  <h3 class="sub">Every series</h3>
  <div class="table-wrap scroll-y tall-scroll"><table>
    <thead><tr><th class="num">#</th><th>Series</th><th>Domain</th><th class="num">Points</th><th class="num">Anomaly</th>
    {''.join(f"<th class='num'>{escape(UCR_METHOD_LABELS.get(m, (m,))[0].split(' (')[0].split(',')[0])}</th>" for m in methods)}</tr></thead>
    <tbody>{''.join(detail_rows)}</tbody>
  </table></div>

  <h3 class="sub">Series details</h3>
  <div class="cards">{''.join(cards)}</div>

  <h3 class="sub">Method notes</h3>
  <ul class="notes">
    <li>Product answer: the highest-importance localized finding after the training part, the order a user sees findings in. A finding's location
    is its change point when it reports one, otherwise its first row. Findings covering {ucr['settings']['whole_series_fraction']:.0%} or more of the
    series (trends, forecast fits, motif summaries) don't point at a location and are skipped.</li>
    <li>Direct answers: the analyzer's most confident localized signal after the training part, with its production configuration.</li>
    <li>Discord reference: every test subsequence compared with every training subsequence (z-normalized distance, <span class="mono">stumpy</span>),
    window one period estimated from the training part's autocorrelation; the answer is the centre of the most distant test subsequence.</li>
    <li>Each series gets a synthetic one-minute timestamp, one row per resampled bucket; UCR scores by position, so the times don't matter. It does mean
    <span class="mono">seasonal_anomaly</span> checks for a daily cycle every 1,440 points, which has no meaning for these recordings.</li>
    <li>Each run has {ucr['settings']['task_timeout_seconds']:.0f} seconds; a run that times out or fails scores as no answer. Timeouts depend on the
    machine, so a slower machine can score lower. Harness code: <span class="mono">benchmark/ucr/</span>. The archive's data files are read; none
    of its code is run.</li>
  </ul>
</section>"""


def _ucr_card(s: dict[str, Any], methods: list[str]) -> str:
    begin0, end0 = s["begin"] - 1, s["end"] - 1
    low, high = s["correct_region"]
    region = (low, high - 2)
    markers = []
    for method, kind in (("product", "detected"), ("discord", "expected")):
        o = s["methods"][method]
        if o["position"] is not None:
            markers.append((o["position"] - 1, kind, f"{UCR_METHOD_LABELS[method][0]}: {o['position']:,}"))
    overview = _ucr_chart(s["plot"], 0, s["n_points"] - 1, s["train_end"], (begin0, end0), region, markers, f"Whole series ({s['n_points']:,} points)")
    zoom = s["zoom"]
    zoomed = _ucr_chart(zoom["points"], zoom["first_row"], zoom["last_row"], s["train_end"], (begin0, end0), region, markers, "Around the labeled anomaly")
    rows = []
    for method in methods:
        o = s["methods"][method]
        extra = []
        if o.get("hit_rank"):
            extra.append(f"correct finding at rank {o['hit_rank']}")
        if o.get("window"):
            extra.append(f"window {o['window']}")
        if o.get("error"):
            extra.append(escape(o["error"]))
        top = o.get("top_candidates") or []
        top_text = ", ".join(f"{escape(c['analyzer'])} @ {c['row'] + 1:,}" for c in top[:3])
        position = "-" if o["position"] is None else f"{o['position']:,}"
        rows.append(
            f"<tr><td>{escape(UCR_METHOD_LABELS.get(method, (method,))[0])}</td><td class='num'>{position}</td>"
            f"<td>{'✓' if o['correct'] else ('✕' if o['position'] is not None else '-')}</td><td class='num'>{_num(o.get('seconds'))}</td>"
            f"<td class='small'>{'; '.join(extra)}{'<br>' if extra and top_text else ''}{f'<span class=muted>top: {top_text}</span>' if top_text else ''}</td></tr>"
        )
    routing = "".join(
        f"<tr><td class='mono'>{escape(str(d['analyzer']))}</td><td>{escape(str(d['recommendation']).replace('_', ' ').lower())}</td><td class='num'>{_num(d['score'])}</td>"
        f"<td class='small'>{escape(str(d.get('reason') or ''))}</td></tr>"
        for d in sorted(s["methods"]["product"].get("routing") or [], key=lambda d: -(d["score"] or 0))
    )
    product = s["methods"]["product"]
    return f"""
<details class="card scenario" id="ucr-{s['number']}">
  <summary><span class="summary-title mono small">{s['number']:03d} {escape(s['name'])}</span>
  <span class="small muted">{escape(s['domain'])} · product {'✓' if product['correct'] else '✕'} · discord {'✓' if s['methods']['discord']['correct'] else '✕'}</span></summary>
  <div class="card-body">
    <p class="small muted">Training part 1-{s['train_end']:,} · labeled anomaly {s['begin']:,}-{s['end']:,} · counted correct strictly between {low:,} and {high:,} ·
    random-guess chance {_pct(s['default_rate'])}</p>
    <div class="chart-grid">{overview}{zoomed}</div>
    <div class="two-col">
      <div><h4>Answers (1-based position)</h4><div class="table-wrap"><table><thead><tr><th>Method</th><th class="num">Position</th><th></th><th class="num">Seconds</th><th>Notes</th></tr></thead>
      <tbody>{''.join(rows)}</tbody></table></div></div>
      <div><h4>Router decisions</h4><div class="table-wrap scroll-y"><table><thead><tr><th>Analyzer</th><th>Decision</th><th class="num">Score</th><th>Reason</th></tr></thead><tbody>{routing}</tbody></table></div></div>
    </div>
  </div>
</details>"""


def _ucr_chart(points, first_row: int, last_row: int, train_end: int, label: tuple[int, int], region: tuple[int, int],
               markers: list[tuple[int, str, str]], title: str) -> str:
    """Row-indexed chart of bucketed [row, mean, min, max] points: min-max envelope, mean line, the
    training part shaded, the correct region banded and method answers as vertical markers."""
    if len(points) < 2:
        return ""
    width, height, pad_l, pad_r, pad_t, pad_b = 720, 180, 44, 12, 12, 26
    lows = [p[2] for p in points]
    highs = [p[3] for p in points]
    y0, y1 = min(lows), max(highs)
    if y1 == y0:
        y0, y1 = y0 - 1, y1 + 1
    span = y1 - y0
    y0, y1 = y0 - span * 0.08, y1 + span * 0.08

    def sx(row: float) -> float:
        return pad_l + (row - first_row) / ((last_row - first_row) or 1) * (width - pad_l - pad_r)

    def sy(value: float) -> float:
        return pad_t + (1 - (value - y0) / (y1 - y0)) * (height - pad_t - pad_b)

    def clip(x: float) -> float:
        return min(max(x, pad_l), width - pad_r)

    bottom = height - pad_b
    envelope = "M" + " L".join(f"{sx(p[0]):.1f},{sy(p[3]):.1f}" for p in points) + " L" + " L".join(f"{sx(p[0]):.1f},{sy(p[2]):.1f}" for p in reversed(points)) + " Z"
    line = "M" + " L".join(f"{sx(p[0]):.1f},{sy(p[1]):.1f}" for p in points)
    parts = []
    if train_end > first_row:
        a, b = clip(sx(first_row)), clip(sx(train_end))
        if b > a:
            parts.append(f"<rect class='shade' x='{a:.1f}' y='{pad_t}' width='{b - a:.1f}' height='{bottom - pad_t}'/>")
    a, b = clip(sx(region[0])), clip(sx(region[1]))
    if b >= a:
        parts.append(f"<rect class='band' x='{a:.1f}' y='{pad_t}' width='{max(b - a, 1.5):.1f}' height='{bottom - pad_t}'/>")
    a, b = clip(sx(label[0])), clip(sx(label[1]))
    parts.append(f"<rect class='band-core' x='{a:.1f}' y='{pad_t}' width='{max(b - a, 1.5):.1f}' height='{bottom - pad_t}'/>")
    decimals = min(6, max(0, 1 - math.floor(math.log10(y1 - y0))))
    grid = "".join(
        f"<line class='grid' x1='{pad_l}' x2='{width - pad_r}' y1='{sy(y0 + (y1 - y0) * i / 3):.1f}' y2='{sy(y0 + (y1 - y0) * i / 3):.1f}'/>"
        f"<text class='axis' x='{pad_l - 6}' y='{sy(y0 + (y1 - y0) * i / 3) + 3:.1f}' text-anchor='end'>{y0 + (y1 - y0) * i / 3:.{decimals}f}</text>"
        for i in range(4)
    )
    grid += (f"<text class='axis' x='{pad_l}' y='{height - 6}'>{first_row + 1:,}</text>"
             f"<text class='axis' x='{width - pad_r}' y='{height - 6}' text-anchor='end'>{last_row + 1:,}</text>")
    marks = []
    legend = [
        "<span class='legend-item'><span class='swatch-box swatch-shade'></span>Training part (normal)</span>",
        "<span class='legend-item'><span class='swatch-box swatch-band'></span>Counted correct (darker: labeled anomaly)</span>",
    ]
    for row, kind, text in markers:
        x = sx(row)
        if pad_l <= x <= width - pad_r:
            marks.append(f"<line class='marker marker-{kind}' x1='{x:.1f}' x2='{x:.1f}' y1='{pad_t}' y2='{bottom}'/>")
            legend.append(f"<span class='legend-item'><span class='swatch swatch-{kind}'></span>{escape(text)}</span>")
    return f"""
<figure class="chart">
  <figcaption>{escape(title)}</figcaption>
  <svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}" preserveAspectRatio="none">
    {''.join(parts)}{grid}
    <path class="envelope" d="{envelope}"/><path class="series" d="{line}"/>
    {''.join(marks)}
  </svg>
  <div class='legend'>{''.join(legend)}</div>
</figure>"""

def _performance_section(performance: dict[str, Any]) -> str:
    datasets = sorted(performance["datasets"], key=lambda item: item["sample_count"])
    if not datasets:
        return ""
    analyzer_ids = [row["analyzer_id"] for row in datasets[-1]["analyzers"]]
    head = "".join(f"<th class='num'>{escape(d['dataset_label'])}<div class='small muted'>{d['sample_count']:,} pts</div></th>" for d in datasets)
    rows = []
    for analyzer_id in analyzer_ids:
        cells = []
        for dataset in datasets:
            row = next((r for r in dataset["analyzers"] if r["analyzer_id"] == analyzer_id), None)
            if row is None:
                cells.append("<td class='num muted'>-</td>")
            elif row.get("error"):
                cells.append(f"<td class='num'><span class='pill pill-critical' title='{escape(row['error'])}'>error</span></td>")
            else:
                cells.append(f"<td class='num'>{row['elapsed_seconds'] * 1000:.1f} ms<div class='small muted'>{row['signal_count']} signals</div></td>")
        rows.append(f"<tr><td class='mono'>{escape(analyzer_id)}</td>{''.join(cells)}</tr>")
    rows.append("<tr class='subtotal'><td>Normalization</td>" + "".join(f"<td class='num'>{d['normalization_seconds'] * 1000:.1f} ms</td>" for d in datasets) + "</tr>")
    rows.append("<tr class='total'><td>Total</td>" + "".join(f"<td class='num'>{d['total_seconds']:.3f} s</td>" for d in datasets) + "</tr>")

    largest = datasets[-1]
    bars = _bar_chart(
        [(row["analyzer_id"], row["elapsed_seconds"] * 1000) for row in largest["analyzers"] if not row.get("error")],
        unit="ms",
        title=f"Time per analyzer on {largest['dataset_label']} ({largest['sample_count']:,} samples)",
    )
    return f"""
<section id="performance">
  <h2>Performance and scale</h2>
  <p class="section-lede">Every registered analyzer runs directly (bypassing routing) on healthy TSBS CPU data at three
  sizes. A warm-up pass absorbs one-time JIT compilation first, so the numbers reflect data scaling. Timings are only
  comparable on the same machine (see the environment below). The only pass/fail rule is a deliberately generous
  {performance.get('max_seconds_per_analyzer', 30):.0f}-second ceiling per analyzer, which exists to catch a catastrophic regression,
  not to enforce a service level.</p>
  {bars}
  <div class="table-wrap"><table>
    <thead><tr><th>Analyzer</th>{head}</tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table></div>
</section>"""


def _pending_section(suites: dict[str, Any]) -> str:
    pending = [item for item in PENDING_SECTIONS if item[0] not in suites]
    if not pending:
        return ""
    items = "".join(f"<li><b>{escape(title)}.</b> {escape(text)}</li>" for _, title, text in pending)
    return f"""
<section id="pending">
  <h2>Not included in this run</h2>
  <div class="card"><p>These evaluations are planned. They are listed here so their absence is visible rather than
  implied away. A snapshot that includes them shows their results in place of this list.</p><ul>{items}</ul>
  <p class="small muted">An earlier, smaller real-data run on four NAB series is written up separately in
  <span class="mono">docs/27-nab-real-world-benchmark.html</span>.</p></div>
</section>"""


def _method_section() -> str:
    rows = "".join(
        f"<tr><td class='mono'>{escape(a)}</td><td>{escape(b)}</td><td>{escape(c)}</td><td class='small'>{escape(d)}</td></tr>"
        for a, b, c, d in ANALYZER_METHODS
    )
    return f"""
<section id="method">
  <h2>Method basis</h2>
  <p class="section-lede">Each analyzer applies an established, published method; none of the detection statistics
  were invented for this project. What is hand-authored is the router's suitability scoring (a base score plus
  additive threshold rules over series features), which decides which analyzers run. Full detail:
  <span class="mono">docs/26-analyzer-methodology.md</span>.</p>
  <div class="table-wrap"><table>
    <thead><tr><th>Analyzer</th><th>Detects</th><th>Method</th><th>Reference</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
  <p class="small muted">Retired scenarios, with the reason each was removed, are kept in
  <span class="mono">benchmark/scenarios/_retired/</span> and are not run.</p>
</section>"""


def _reproduce_section(results: dict[str, Any], manifest: dict[str, Any]) -> str:
    git = manifest.get("git", {})
    env_rows = [
        ("Commit", f"<span class='mono'>{escape(git.get('commit') or 'unknown')}</span>"),
        ("Commit date", escape(_fmt_time(git.get("commit_date")))),
        ("Branch", f"<span class='mono'>{escape(git.get('branch') or '?')}</span>"),
        ("Python", escape(manifest.get("python", ""))),
        ("Platform", escape(manifest.get("platform", ""))),
        ("CPU", escape(manifest.get("cpu", ""))),
        ("Wall time for this run", f"{manifest.get('duration_seconds_wall', 0):.1f} s"),
    ]
    env = "".join(f"<tr><th scope='row'>{k}</th><td>{v}</td></tr>" for k, v in env_rows)
    packages = "".join(
        f"<tr><td class='mono'>{escape(name)}</td><td class='mono'>{escape(version or 'not installed')}</td></tr>"
        for name, version in (manifest.get("packages") or {}).items()
    )
    hashes = "".join(
        f"<tr><td class='mono small'>{escape(path)}</td><td class='mono small'>{escape(digest[:16])}…</td></tr>"
        for path, digest in {**(manifest.get("config_sha256") or {}), **(manifest.get("dataset_sha256") or {})}.items()
    )
    dirty = ""
    if git.get("dirty"):
        files = "".join(f"<li class='mono small'>{escape(line)}</li>" for line in git.get("dirty_files") or [])
        dirty = f"<div class='callout callout-warning'><b>The working tree had uncommitted changes when this ran.</b> Results may not match the commit exactly:<ul>{files}</ul></div>"
    return f"""
<section id="reproduce">
  <h2>Reproduce this report</h2>
  {dirty}
  <pre class="code"><code>git checkout {escape((git.get('commit') or 'COMMIT')[:12])}
.venv/bin/python -m benchmark.run_all</code></pre>
  <p>A rerun on the same commit and data should print the same accuracy fingerprint,
  <span class="mono">{escape(results.get('fingerprint', ''))}</span>. The fingerprint covers every result except wall-clock
  timings.</p>
  <div class="three-col">
    <div><h4>Environment</h4><div class="table-wrap"><table class="kv"><tbody>{env}</tbody></table></div></div>
    <div><h4>Library versions</h4><div class="table-wrap"><table><tbody>{packages}</tbody></table></div></div>
    <div><h4>Input hashes (SHA-256)</h4><div class="table-wrap scroll-y"><table><tbody>{hashes}</tbody></table></div></div>
  </div>
</section>"""


# --- building blocks ------------------------------------------------------------------------


def _tile(label: str, value: str, caption: str, status: str | None) -> str:
    marker = ""
    if status:
        kind, icon, _ = next(meta for meta in STATUS_META.values() if meta[0] == status)
        marker = f"<span class='tile-status tile-{kind}' aria-hidden='true'>{icon}</span>"
    return f"<div class='tile'><div class='tile-label'>{marker}{escape(label)}</div><div class='tile-value'>{value}</div><div class='tile-caption'>{escape(caption)}</div></div>"


def _status_pill(status: str) -> str:
    kind, icon, label = STATUS_META.get(status, ("warning", "?", status))
    return f"<span class='pill pill-{kind}'><span aria-hidden='true'>{icon}</span> {escape(label)}</span>"


def _checks_list(checks: dict[str, bool]) -> str:
    if not checks:
        return "<p class='muted'>No checks recorded.</p>"
    items = "".join(
        f"<li class='{'ok' if passed else 'bad'}'><span aria-hidden='true'>{'✓' if passed else '✕'}</span> <span class='sr'>{'passed' if passed else 'failed'}:</span> {escape(name.replace('_', ' '))}</li>"
        for name, passed in checks.items()
    )
    return f"<ul class='checks'>{items}</ul>"


def _profile_table(profile: dict[str, Any]) -> str:
    rows = []
    for key, label in PROFILE_FEATURES:
        if key in profile:
            rows.append(f"<tr><th scope='row'>{escape(label)}</th><td class='num mono'>{_num(profile[key])}</td></tr>")
    detected = ", ".join(profile.get("detected_profiles") or []) or "none"
    rows.append(f"<tr><th scope='row'>Detected profiles</th><td class='mono'>{escape(detected)}</td></tr>")
    return f"<div class='table-wrap'><table class='kv'><tbody>{''.join(rows)}</tbody></table></div>"


def _detection_table(detection: dict[str, Any], item: dict[str, Any]) -> str:
    if "actionable_findings" in detection:
        counts = detection.get("raw_signal_counts") or {}
        rows = "".join(f"<tr><td class='mono'>{escape(k)}</td><td class='num'>{v}</td></tr>" for k, v in counts.items())
        return f"""<p>Every real analyzer ran on this stable series. Raw statistical signals are expected; what must not happen is any
of them surviving finding aggregation as a critical or significant alert.
<b>{detection.get('total_raw_signals', 0)}</b> raw signals became <b>{detection.get('total_findings', 0)}</b> findings, of which
<b>{len(detection.get('actionable_findings') or [])}</b> were actionable.</p>
<div class="table-wrap narrow"><table><thead><tr><th>Analyzer</th><th class="num">Raw signals</th></tr></thead><tbody>{rows}</tbody></table></div>"""
    rows = [
        ("Direction", detection.get("expected_direction"), detection.get("actual_direction")),
        ("Timing", _fmt_time(detection.get("expected_timestamp")), _fmt_time(detection.get("detected_timestamp"))),
        ("Magnitude", f"≥ {detection.get('minimum_magnitude')}%" if detection.get("minimum_magnitude") is not None else "-", f"{_num(detection.get('percent_change'))}%"),
    ]
    event = item.get("expected_event") or {}
    tolerance = f"Timing tolerance: {event.get('tolerance_before', '?')} before, {event.get('tolerance_after', '?')} after." if event else ""
    body = "".join(f"<tr><th scope='row'>{escape(a)}</th><td>{escape(str(b))}</td><td>{escape(str(c))}</td></tr>" for a, b, c in rows)
    return f"<div class='table-wrap narrow'><table><thead><tr><th></th><th>Expected</th><th>Found</th></tr></thead><tbody>{body}</tbody></table></div><p class='small muted'>{escape(tolerance)}</p>"


def _decisions_table(details: dict[str, list[dict[str, Any]]]) -> str:
    rows = []
    for bucket in ("recommended", "optional", "not_recommended"):
        for decision in sorted(details.get(bucket) or [], key=lambda d: -(d.get("score") or 0)):
            evidence = decision.get("feature_evidence") or {}
            rules = evidence.get("matched_scoring_rules") or []
            rule_text = "; ".join(_rule_text(rule) for rule in rules) or "-"
            base = (evidence.get("scoring_rules") or {}).get("base")
            score = decision.get("score")
            bar = f"<span class='scorebar' style='--w:{max(0.0, min(1.0, float(score or 0))) * 100:.0f}%'></span>" if score is not None else ""
            rows.append(
                f"<tr><td class='mono'>{escape(str(decision.get('analyzer')))}</td>"
                f"<td>{escape(bucket.replace('_', ' '))}</td>"
                f"<td class='num'>{_num(score)}{bar}</td>"
                f"<td class='small'>{'base ' + _num(base) + ' · ' if base is not None else ''}{escape(rule_text)}</td>"
                f"<td class='small'>{escape(str(decision.get('reason') or ''))}</td></tr>"
            )
    if not rows:
        return "<p class='muted'>No routing decisions recorded.</p>"
    return f"""<div class='table-wrap'><table class="decisions"><thead><tr><th>Analyzer</th><th>Decision</th><th class="num">Score</th>
<th>Score built from</th><th>Router's reason</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"""


def _analyzer_list(names: list[str], executable: set[str]) -> str:
    if not names:
        return "nothing"
    if not executable:
        return escape(", ".join(names))
    return ", ".join(
        escape(name) if name in executable else f"<span class='router-only' title='Router-only: no pipeline implementation'>{escape(name)}†</span>"
        for name in names
    )


def _rule_text(rule: dict[str, Any]) -> str:
    metric = rule.get("metric", "?")
    for op, symbol in (("gte", "≥"), ("gt", ">"), ("lte", "≤"), ("lt", "<"), ("equals", "=")):
        if op in rule:
            return f"{metric} {symbol} {rule[op]} → +{rule.get('add')}"
    return f"{metric} → +{rule.get('add')}"


def _line_chart(
    points: list[list[Any]],
    markers: list[dict[str, str]],
    *,
    title: str,
    bands: list[tuple[str, str]] | None = None,
    shade: tuple[str, str] | None = None,
    ticks: list[list[Any]] | None = None,
    x_labels: tuple[str, str] | None = None,
) -> str:
    """Line chart with optional vertical markers, shaded bands (labeled windows), one muted shaded
    span (the unscored probationary period) and a strip of alarm ticks under the plot."""
    if len(points) < 2:
        return ""
    width, pad_l, pad_r, pad_t = 720, 44, 12, 12
    pad_b = 40 if ticks is not None else 26
    height = 180 + (pad_b - 26)

    def ts(value: str) -> float:
        return _dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()

    points = [p for p in points if p[1] is not None]
    if len(points) < 2:
        return ""
    xs = [ts(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    if y1 == y0:
        y0, y1 = y0 - 1, y1 + 1
    span = y1 - y0
    y0, y1 = y0 - span * 0.08, y1 + span * 0.08

    def sx(x: float) -> float:
        return pad_l + (x - x0) / (x1 - x0 or 1) * (width - pad_l - pad_r)

    def sy(y: float) -> float:
        return pad_t + (1 - (y - y0) / (y1 - y0)) * (height - pad_t - pad_b)

    path = "M" + " L".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in zip(xs, ys))
    decimals = min(6, max(0, 1 - math.floor(math.log10(y1 - y0))))
    grid = []
    for i in range(4):
        value = y0 + (y1 - y0) * i / 3
        y = sy(value)
        grid.append(f"<line class='grid' x1='{pad_l}' x2='{width - pad_r}' y1='{y:.1f}' y2='{y:.1f}'/><text class='axis' x='{pad_l - 6}' y='{y + 3:.1f}' text-anchor='end'>{value:.{decimals}f}</text>")
    start = _dt.datetime.fromtimestamp(x0, tz=_dt.timezone.utc)
    end = _dt.datetime.fromtimestamp(x1, tz=_dt.timezone.utc)
    left_label, right_label = x_labels or (f"{start:%b %d %H:%M}", f"{end:%b %d %H:%M} UTC")
    grid.append(f"<text class='axis' x='{pad_l}' y='{height - 6}'>{escape(left_label)}</text><text class='axis' x='{width - pad_r}' y='{height - 6}' text-anchor='end'>{escape(right_label)}</text>")
    plot_bottom = height - pad_b
    marks = []
    legend = []
    underlay = []
    if shade:
        a, b = max(sx(ts(shade[0])), pad_l), min(sx(ts(shade[1])), width - pad_r)
        if b > a:
            underlay.append(f"<rect class='shade' x='{a:.1f}' y='{pad_t}' width='{b - a:.1f}' height='{plot_bottom - pad_t}'/>")
            legend.append("<span class='legend-item'><span class='swatch-box swatch-shade'></span>Probationary period (not scored)</span>")
    for band_start, band_end in bands or []:
        a, b = max(sx(ts(band_start)), pad_l), min(sx(ts(band_end)), width - pad_r)
        if b > a:
            underlay.append(f"<rect class='band' x='{a:.1f}' y='{pad_t}' width='{max(b - a, 1.5):.1f}' height='{plot_bottom - pad_t}'/>")
    if bands:
        legend.append("<span class='legend-item'><span class='swatch-box swatch-band'></span>Labeled anomaly window</span>")
    if ticks is not None:
        tick_y = plot_bottom + 4
        for moment, _ in ticks:
            x = sx(ts(moment))
            if pad_l <= x <= width - pad_r:
                marks.append(f"<line class='tick' x1='{x:.1f}' x2='{x:.1f}' y1='{tick_y}' y2='{tick_y + 8}'/>")
        legend.append(f"<span class='legend-item'><span class='swatch swatch-detected'></span>Alarm ({len(ticks)})</span>")
    legend_labels: set[str] = set()
    for marker in markers:
        try:
            x = sx(ts(marker["t"]))
        except ValueError:
            continue
        if not pad_l <= x <= width - pad_r:
            continue
        marks.append(f"<line class='marker marker-{marker['kind']}' x1='{x:.1f}' x2='{x:.1f}' y1='{pad_t}' y2='{plot_bottom}'/>")
        text = marker.get("text") or f"{marker['label']} · {_fmt_time(marker['t'])}"
        if text not in legend_labels:
            legend_labels.add(text)
            legend.append(f"<span class='legend-item'><span class='swatch swatch-{marker['kind']}'></span>{escape(text)}</span>")
    data = json.dumps([list(p[:3]) for p in points])
    return f"""
<figure class="chart">
  <figcaption>{escape(title)}</figcaption>
  <div class="chart-frame" data-points='{escape(data)}' data-x0="{x0}" data-x1="{x1}" data-padl="{pad_l}" data-padr="{pad_r}" data-w="{width}">
    <svg viewBox="0 0 {width} {height}"{" class='tall'" if ticks is not None else ""} role="img" aria-label="{escape(title)}" preserveAspectRatio="none">
      {''.join(underlay)}
      {''.join(grid)}
      <path class="series" d="{path}"/>
      {''.join(marks)}
      <line class="crosshair" x1="0" x2="0" y1="{pad_t}" y2="{plot_bottom}"/>
    </svg>
    <div class="tooltip" role="status"></div>
  </div>
  {f"<div class='legend'>{''.join(legend)}</div>" if legend else ""}
</figure>"""


def _bar_chart(items: list[tuple[str, float]], *, unit: str, title: str) -> str:
    if not items:
        return ""
    top = max(value for _, value in items) or 1
    rows = "".join(
        f"<div class='bar-row' title='{escape(label)}: {value:.1f} {unit}'><span class='bar-label mono'>{escape(label)}</span>"
        f"<span class='bar-track'><span class='bar' style='--w:{max(value / top * 100, 0.8):.1f}%'></span></span>"
        f"<span class='bar-value num'>{value:.1f} {unit}</span></div>"
        for label, value in sorted(items, key=lambda item: -item[1])
    )
    return f"<figure class='chart bars'><figcaption>{escape(title)}</figcaption>{rows}</figure>"


def _num(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.3f}".rstrip("0").rstrip(".") if abs(value) < 1000 else f"{value:,.0f}"
    return escape(str(value))


def _fmt_time(value: Any) -> str:
    if not value:
        return "-"
    text = str(value)
    return text.replace("T", " ").replace("+00:00", " UTC").replace("Z", " UTC")


def _document(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<main class="page">
{body}
<footer class="small muted">Generated by <span class="mono">benchmark/report_html.py</span> from this run's
<span class="mono">results.json</span>.</footer>
</main>
<script>{_JS}</script>
</body>
</html>
"""


_CSS = """
:root{color-scheme:light;--paper:#f4f4f2;--surface:#fcfcfb;--surface-2:#ecebe7;--ink:#0b0b0b;--ink-2:#52514e;--ink-3:#7d7c77;
--line:#dedcd6;--accent:#2a78d6;--series:#2a78d6;--grid:#e6e4df;--good:#0ca30c;--good-ink:#006300;--warning:#fab219;--warning-ink:#8a5a00;
--critical:#d03b3b;--critical-ink:#a32222;--detected:#eb6834;
--band:rgba(208,59,59,.13);--band-solid:rgba(208,59,59,.35);--shade:rgba(125,124,119,.12);--shade-solid:rgba(125,124,119,.35)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--paper:#121211;--surface:#1a1a19;--surface-2:#262624;
--ink:#ffffff;--ink-2:#c3c2b7;--ink-3:#8f8e86;--line:#34332f;--accent:#3987e5;--series:#3987e5;--grid:#2c2b28;--good:#0ca30c;--good-ink:#5fd35f;
--warning:#fab219;--warning-ink:#fab219;--critical:#d03b3b;--critical-ink:#f08585;--detected:#d95926;
--band:rgba(230,103,103,.17);--band-solid:rgba(230,103,103,.45);--shade:rgba(143,142,134,.12);--shade-solid:rgba(143,142,134,.4)}}
:root[data-theme="dark"]{color-scheme:dark;--paper:#121211;--surface:#1a1a19;--surface-2:#262624;--ink:#ffffff;--ink-2:#c3c2b7;--ink-3:#8f8e86;
--line:#34332f;--accent:#3987e5;--series:#3987e5;--grid:#2c2b28;--good-ink:#5fd35f;--warning-ink:#fab219;--critical-ink:#f08585;--detected:#d95926;
--band:rgba(230,103,103,.17);--band-solid:rgba(230,103,103,.45);--shade:rgba(143,142,134,.12);--shade-solid:rgba(143,142,134,.4)}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}
.page{max-width:1080px;margin:0 auto;padding:48px 24px 80px;display:flex;flex-direction:column;gap:44px}
h1,h2,h3,h4{line-height:1.25;margin:0;text-wrap:balance}
h1{font-size:32px;letter-spacing:-.01em}h2{font-size:22px;margin-bottom:10px}h3{font-size:16px}h3.sub{margin:28px 0 12px}
h4{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--ink-2);margin:20px 0 8px}
p{margin:0 0 10px}ul{margin:0;padding-left:20px}
.mono{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-size:.92em}
.small{font-size:12.5px}.muted{color:var(--ink-3)}.num{text-align:right;font-variant-numeric:tabular-nums}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.eyebrow{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);font-weight:600;margin-bottom:8px}
.suite-links{margin-top:10px}.suite-links a{color:var(--accent);text-decoration:none}.suite-links a:hover{text-decoration:underline}\n.hero .lede{color:var(--ink-2);max-width:70ch;font-size:16px;margin-top:10px}
.provenance{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:22px 0 0;padding:16px;
background:var(--surface);border:1px solid var(--line);border-radius:10px}
.provenance dt{font-size:11.5px;text-transform:uppercase;letter-spacing:.07em;color:var(--ink-3)}.provenance dd{margin:2px 0 0}
.section-lede{color:var(--ink-2);max-width:78ch}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px 18px}
.tile-label{font-size:13px;color:var(--ink-2);display:flex;gap:6px;align-items:center}
.tile-value{font-size:34px;font-weight:650;letter-spacing:-.02em;font-variant-numeric:tabular-nums;margin:4px 0}
.tile-value .of{font-size:18px;color:var(--ink-3);font-weight:500}
.tile-caption{font-size:12.5px;color:var(--ink-3)}
.tile-status{font-weight:700}.tile-good{color:var(--good-ink)}.tile-critical{color:var(--critical-ink)}.tile-warning{color:var(--warning-ink)}
.pill{display:inline-flex;gap:5px;align-items:center;font-size:12.5px;font-weight:600;padding:2px 10px;border-radius:999px;border:1px solid;white-space:nowrap}
.pill-good{color:var(--good-ink);border-color:var(--good)}.pill-warning{color:var(--warning-ink);border-color:var(--warning)}
.pill-critical{color:var(--critical-ink);border-color:var(--critical)}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:18px 20px}
.cards{display:flex;flex-direction:column;gap:10px}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:16px 28px}
.three-col{display:grid;grid-template-columns:1.2fr 1fr 1.3fr;gap:20px}
details.scenario{padding:0}details.scenario>summary{cursor:pointer;list-style:none;display:flex;justify-content:space-between;
align-items:center;gap:12px;padding:14px 20px}
details.scenario>summary::-webkit-details-marker{display:none}
details.scenario>summary::before{content:"▸";color:var(--ink-3);margin-right:4px;transition:transform .15s}
details.scenario[open]>summary::before{transform:rotate(90deg)}
.summary-title{font-weight:600;flex:1}
.card-body{padding:4px 20px 20px;border-top:1px solid var(--line)}
.table-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--surface)}
.table-wrap.narrow{max-width:560px}.scroll-y{max-height:320px;overflow-y:auto}.tall-scroll{max-height:560px}
tr.emph td{font-weight:650;background:var(--surface-2)}
.explain{margin-top:20px}.explain h3{margin-bottom:6px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}
thead th{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--ink-2);background:var(--surface-2);font-weight:600}
tbody tr:last-child td,tbody tr:last-child th{border-bottom:0}
table.kv th{font-weight:500;color:var(--ink-2);width:48%}
tr.total td{font-weight:650}tr.subtotal td{color:var(--ink-2)}
td a{color:var(--ink);text-decoration:none;border-bottom:1px solid var(--line)}td a:hover{border-color:var(--accent)}
.decisions td:nth-child(3){min-width:92px}
.router-only{color:var(--ink-3)}
.scorebar{display:block;height:4px;margin-top:5px;border-radius:2px;background:linear-gradient(90deg,var(--series) var(--w),var(--grid) var(--w))}
.checks{list-style:none;padding:0;display:flex;flex-direction:column;gap:3px;font-size:13.5px}
.checks .ok span:first-child{color:var(--good-ink);font-weight:700}.checks .bad span:first-child{color:var(--critical-ink);font-weight:700}
.checks .bad{color:var(--critical-ink)}
.notes{font-size:13.5px;color:var(--ink-2);display:flex;flex-direction:column;gap:4px;margin-top:8px}
.callout{border-left:3px solid;padding:10px 14px;border-radius:0 8px 8px 0;margin:14px 0;background:var(--surface-2);font-size:14px}
.callout-warning{border-color:var(--warning)}.callout-good{border-color:var(--good)}.callout-critical{border-color:var(--critical)}
.chart{margin:14px 0 6px}.chart figcaption{font-size:12.5px;color:var(--ink-2);margin-bottom:6px}
.chart-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.chart-frame{position:relative}.chart svg{width:100%;height:auto;aspect-ratio:720/180;display:block;overflow:visible}
.chart svg.tall{aspect-ratio:720/194}
.chart .band{fill:var(--band)}.chart .shade{fill:var(--shade)}
.chart .band-core{fill:var(--band-solid)}.chart .envelope{fill:var(--series);opacity:.2;stroke:none}
.nowrap{white-space:nowrap}.ok-mark{color:var(--good-ink);font-weight:700}
.glance-list{display:grid;gap:10px;margin:0}.glance-list div{display:grid;grid-template-columns:190px 1fr;gap:12px}
.glance-list dt{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--ink-3);padding-top:2px}.glance-list dd{margin:0}
.glance-verdict{margin:0 0 14px;font-size:15px}
.index-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
.index-card,.index-all{display:flex;flex-direction:column;gap:6px;color:var(--ink);text-decoration:none;transition:border-color .15s}
.index-card:hover,.index-all:hover{border-color:var(--accent)}.index-card h3{margin:4px 0 0}
.index-question{color:var(--ink-2);margin:0}.index-result{margin:6px 0 0;font-weight:600}.index-open{color:var(--accent);margin-top:auto;padding-top:6px}
.tags{display:flex;flex-wrap:wrap;gap:6px}.tag{font-size:11.5px;padding:1px 8px;border-radius:999px;background:var(--surface-2);color:var(--ink-2)}.glance-table td{min-width:120px}
@media (max-width:640px){.glance-list div{grid-template-columns:1fr;gap:2px}}.bad-mark{color:var(--critical-ink);font-weight:700}
.chart .tick{stroke:var(--detected);stroke-width:1.5;vector-effect:non-scaling-stroke}
.swatch-box{display:inline-block;width:14px;height:10px;border-radius:2px}.swatch-band{background:var(--band-solid)}
.swatch-shade{background:var(--shade-solid)}
.chart .grid{stroke:var(--grid);stroke-width:1}.chart .axis{fill:var(--ink-3);font-size:11px}
.chart .series{fill:none;stroke:var(--series);stroke-width:2;vector-effect:non-scaling-stroke;stroke-linejoin:round}
.chart .marker{stroke-width:2;vector-effect:non-scaling-stroke}
.chart .marker-expected{stroke:var(--ink-2);stroke-dasharray:4 4}.chart .marker-detected{stroke:var(--detected)}
.chart .marker-direct{stroke:var(--detected);stroke-dasharray:2 3}.swatch-direct{border-color:var(--detected);border-top-style:dotted}
.chart .crosshair{stroke:var(--ink-3);stroke-width:1;vector-effect:non-scaling-stroke;opacity:0}
.chart-frame:hover .crosshair{opacity:1}
.tooltip{position:absolute;top:4px;pointer-events:none;background:var(--ink);color:var(--paper);font-size:12px;padding:4px 8px;
border-radius:6px;white-space:nowrap;opacity:0;transform:translateX(-50%)}
.chart-frame:hover .tooltip{opacity:1}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12px;color:var(--ink-2);margin-top:4px}
.legend-item{display:inline-flex;align-items:center;gap:6px}
.swatch{display:inline-block;width:16px;height:0;border-top:2px solid}.swatch-expected{border-color:var(--ink-2);border-top-style:dashed}
.swatch-detected{border-color:var(--detected)}
.bars{display:flex;flex-direction:column;gap:6px;max-width:760px}
.bar-row{display:grid;grid-template-columns:140px 1fr 80px;gap:10px;align-items:center;font-size:13px}
.bar-track{height:12px}.bar{display:block;height:100%;width:var(--w);background:var(--series);border-radius:0 4px 4px 0}
.code{background:var(--surface-2);border:1px solid var(--line);border-radius:8px;padding:14px 16px;overflow-x:auto;font-size:13px;margin:0 0 12px}
footer{border-top:1px solid var(--line);padding-top:16px}
@media (max-width:760px){.page{padding:28px 16px 56px}.two-col,.three-col,.chart-grid{grid-template-columns:1fr}
.bar-row{grid-template-columns:110px 1fr 70px}h1{font-size:26px}}
@media print{details.scenario{break-inside:avoid}details.scenario .card-body{display:block}}
"""

_JS = """
document.querySelectorAll('.chart-frame').forEach(function(frame){
  var pts; try{pts=JSON.parse(frame.dataset.points)}catch(e){return}
  var x0=+frame.dataset.x0,x1=+frame.dataset.x1,pl=+frame.dataset.padl,pr=+frame.dataset.padr,w=+frame.dataset.w;
  var times=pts.map(function(p){return Date.parse(p[0])/1000});
  var tip=frame.querySelector('.tooltip'),cross=frame.querySelector('.crosshair');
  frame.addEventListener('mousemove',function(ev){
    var r=frame.getBoundingClientRect(),vx=(ev.clientX-r.left)/r.width*w;
    var t=x0+(vx-pl)/(w-pl-pr)*(x1-x0),best=0;
    for(var i=1;i<times.length;i++){if(Math.abs(times[i]-t)<Math.abs(times[best]-t))best=i}
    var sx=pl+(times[best]-x0)/((x1-x0)||1)*(w-pl-pr);
    cross.setAttribute('x1',sx);cross.setAttribute('x2',sx);
    tip.style.left=Math.min(Math.max(sx/w*100,8),92)+'%';
    var label=pts[best].length>2?pts[best][2]:pts[best][0].replace('T',' ').slice(0,16)+' UTC';
    tip.textContent=label+'  ·  '+(+pts[best][1]).toFixed(2);
  });
});
window.addEventListener('beforeprint',function(){document.querySelectorAll('details').forEach(function(d){d.open=true})});
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a benchmark results.json as an HTML evidence report")
    parser.add_argument("results", type=Path, help="Path to a results.json written by benchmark.run_all")
    parser.add_argument("--output", type=Path, help="Where to write the HTML (default: report.html next to results.json)")
    args = parser.parse_args()
    print(write_report(args.results, args.output))


if __name__ == "__main__":
    main()
