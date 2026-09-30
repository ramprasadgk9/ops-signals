"""The publication report: the results section a reviewer checks, laid out like a paper.

Setup (system, protocol, datasets, compared methods, metrics, statistics), then results per dataset
with 95% bootstrap intervals, the official NAB scoreboard with published detectors, the
equal-alert-budget curves, the routing ablation, threats to validity and the full reproducibility
record. Every value comes from build_facts; nothing is stated that the run did not measure.
"""

from __future__ import annotations

import re
from html import escape
from typing import Any

from benchmark.evidence.facts import BOOTSTRAP_SAMPLES, SEED
from benchmark.evidence.html import ci, interval_says, n, page, pct
from benchmark.methods import DESCRIPTIONS, LABELS
from benchmark.report_html import _budget_chart

CSS = """
body{font:16.5px/1.65 "Source Serif 4",Georgia,"Times New Roman",serif}
h1,h2,h3{font-family:"IBM Plex Sans",-apple-system,"Segoe UI",sans-serif;line-height:1.25;text-wrap:balance;margin:0}
h1{font-size:clamp(26px,4vw,34px);font-weight:600}h2{font-size:21px;font-weight:600;margin-top:8px}h3{font-size:16.5px;font-weight:600}
p{margin:0;max-width:760px}.meta{font:14px "IBM Plex Sans",sans-serif;color:var(--muted)}
header{padding-block:40px 20px;display:grid;gap:12px;border-bottom:1px solid var(--line)}
.abstract{background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:16px 20px;max-width:none}
section{padding-block:30px 0;display:grid;gap:14px}
table{font-family:"IBM Plex Sans",sans-serif;font-size:14px}caption{caption-side:top;text-align:left;font:14px "IBM Plex Sans",sans-serif;
color:var(--muted);padding-bottom:6px}
ul{margin:0;padding-left:22px;display:grid;gap:6px;max-width:780px}
footer{margin-top:40px;padding-top:12px;border-top:1px solid var(--line);font:13px "IBM Plex Sans",sans-serif;color:var(--muted)}
"""


def _markup(text: str) -> str:
    """Routing cell text from benchmark.report_html carries its own tags; show it as plain text."""
    return escape(" ".join(re.sub(r"<[^>]+>", " ", text).split()))


def render(facts: dict[str, Any]) -> str:
    counter = iter(range(1, 50))
    body = "".join(part for part in [
        _header(facts),
        _setup(facts, counter),
        _nab(facts, counter),
        _ucr(facts, counter),
        _tcpd(facts, counter),
        _smd(facts, counter),
        _own(facts, counter),
        _ablation(facts, counter),
        _threats(facts),
        _reproducibility(facts, counter),
    ] if part)
    return page("Ops Signals Benchmark Results", CSS, body)


def _header(facts: dict[str, Any]) -> str:
    run, nab, ucr, tcpd = facts["run"], facts["nab"], facts["ucr"], facts["tcpd"]
    claims = []
    if nab and "live" in nab["methods"]:
        live = nab["methods"]["live"]
        claims.append(f"on NAB ({nab['series']} series, {nab['windows']} labelled windows) the routed system reaches window F1 {live['f1']:.3f} "
                      f"{ci(live['f1_ci'])} in causal replay")
        if "static_threshold" in nab["paired_f1_vs"]:
            claims.append(f"against a static threshold the paired F1 difference is {ci(nab['paired_f1_vs']['static_threshold'])}, "
                          f"{interval_says(nab['paired_f1_vs']['static_threshold'])}")
    if ucr:
        claims.append(f"on the UCR Anomaly Archive it locates {ucr['correct']['product']} of {ucr['series']} anomalies {ci(ucr['product_ci'], 0)}")
    if tcpd:
        claims.append(f"on TCPD its change-point F1 is {tcpd['product_f1']:.3f} {ci(tcpd['product_ci'])}, rank {tcpd['rank']} among "
                      f"{tcpd['published_count'] + 1} with the published default-setting methods")
    summary = "; ".join(claims)
    return f"""
<header>
  <p class="meta">Benchmark results · run {escape(run['run_id'] or '')} · commit {escape((run['commit'] or '')[:12])}</p>
  <h1>Profile-based routing of time-series detectors: results on public anomaly and change-point benchmarks</h1>
  <p class="abstract"><b>Summary.</b> Ops Signals profiles each metric and routes it to a small set of specialised detectors (spikes, level
  shifts, unusual subsequences, drift, data quality) instead of running every detector. We evaluate the routed system as shipped, without
  per-dataset tuning, against running every detector, a z-score rule, a static threshold and published methods. {escape(summary[:1].upper() + summary[1:])}.
  Intervals are 95% bootstrap intervals over series.</p>
</header>"""


def _setup(facts: dict[str, Any], counter) -> str:
    nab, ucr, tcpd, smd = facts["nab"], facts["ucr"], facts["tcpd"], facts["smd"]
    datasets = []
    if nab:
        s = nab["settings"]
        datasets.append(("NAB (Numenta Anomaly Benchmark)", f"{nab['series']} series, {nab['windows']} labelled windows",
                         "Numenta (published labels)", f"Causal replay: window {s.get('replay_window_rows')} rows, step {s.get('replay_step_rows')}; "
                         f"batch over the whole series. First {pct(s.get('probationary_percent'))} of each series (max 750 rows) unscored."))
    if ucr:
        datasets.append(("UCR Anomaly Archive", f"{ucr['series']} series, one anomaly each", "Wu & Keogh (published labels)",
                         "One answer per series: the top-ranked finding after the training part must overlap the anomaly (with slack)."))
    if tcpd:
        datasets.append(("TCPD (Turing Change Point Dataset)", f"{tcpd['series']} of {tcpd['evaluation_set']} series available",
                         "van den Burg & Williams (five annotators)", f"F1 and cover against all annotators, margin {tcpd['settings'].get('margin')} points."))
    if smd:
        datasets.append(("SMD (Server Machine Dataset)", f"{smd['machines']} machines × {smd['metrics_per_machine']} metrics", "OmniAnomaly (published labels)",
                         f"Batch over the test part; alerts {smd['gap_minutes']} minutes apart are separate; no point adjustment."))
    rows = "".join(f"<tr><td>{escape(a)}</td><td>{escape(b)}</td><td>{escape(c)}</td><td class='small'>{escape(d)}</td></tr>" for a, b, c, d in datasets)
    methods = "".join(f"<tr><td>{escape(LABELS[m])}</td><td class='small'>{escape(DESCRIPTIONS[m])}</td></tr>" for m in LABELS)
    table = next(counter)
    return f"""
<section><h2>1. Setup</h2>
<p><b>System under test.</b> For each series the router computes a profile (spikiness, level-shift index, seasonality and trend
strength, sampling regularity, gaps) and selects, per detected profile, the best eligible analyzer, then fills up to three places by
score; a data-quality analyzer always runs. Findings are reported with a confidence; a finding counts when its confidence is at least
0.5, fixed before scoring.</p>
<div class="table-wrap"><table><caption>Table {table}. Datasets and protocol.</caption>
<thead><tr><th>Dataset</th><th>Size in this run</th><th>Ground truth</th><th>Protocol</th></tr></thead><tbody>{rows}</tbody></table></div>
<div class="table-wrap"><table><caption>Compared methods (same data, same scoring). Published methods are added per dataset where available.</caption>
<thead><tr><th>Method</th><th>Definition</th></tr></thead><tbody>{methods}</tbody></table></div>
<p><b>Statistics.</b> 95% percentile bootstrap intervals, {BOOTSTRAP_SAMPLES:,} resamples of series (machines for SMD), seed {SEED}.
Differences between two methods are paired: the same resampled series score both, so the interval reflects the gap on shared data.</p>
</section>"""


def _nab(facts: dict[str, Any], counter) -> str:
    nab = facts["nab"]
    if not nab:
        return ""
    rows = []
    for key, m in nab["methods"].items():
        alerts = m["alerts"] or {}
        rows.append(f"<tr class='{'ours' if key in ('live', 'batch') else ''}'><td>{escape(m['label'])}</td><td class='n'>{m['caught']}/{m['windows']}</td>"
                    f"<td class='n'>{pct(m['precision'], 1)}</td><td class='n'>{m['f1']:.3f} <span class='muted'>{ci(m['f1_ci'])}</span></td>"
                    f"<td class='n'>{n(alerts.get('alerts'))}</td><td class='n'>{n(alerts.get('false'))}</td></tr>")
    paired = "".join(f"<li>Live routed system minus {escape(LABELS[b])}: F1 difference {ci(v)}, {interval_says(v)}.</li>"
                     for b, v in nab["paired_f1_vs"].items())
    t1 = next(counter)
    parts = [f"""
<section><h2>2. NAB</h2>
<div class="table-wrap"><table><caption>Table {t1}. Window metrics at confidence ≥ 0.5 (flags in the probationary period ignored).
Precision and F1 count flags; the alert columns merge flags less than 15 minutes (or one sampling interval) apart.</caption>
<thead><tr><th>Method</th><th class="n">Windows caught</th><th class="n">Flag precision</th><th class="n">F1 [95% CI]</th>
<th class="n">Alerts</th><th class="n">False alerts</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<ul class="small">{paired}</ul>"""]
    official = nab["official"]
    if official:
        t2 = next(counter)
        board = "".join(f"<tr class='{'ours' if r['ours'] else ''}'><td>{escape(r['label'])}</td><td class='n'>{n(r['standard'], 1)}</td>"
                        f"<td class='n'>{n(r['low_fp'], 1)}</td><td class='n'>{n(r['low_fn'], 1)}</td></tr>" for r in official["board"])
        parts.append(f"""
<div class="table-wrap"><table><caption>Table {t2}. Official NAB scores (NAB's own scorer, unmodified; 0 = null detector, 100 = perfect),
with the published detectors re-scored in the same environment.</caption>
<thead><tr><th>Detector</th><th class="n">Standard</th><th class="n">Low FP</th><th class="n">Low FN</th></tr></thead><tbody>{board}</tbody></table></div>""")
    budget = nab["budget"]
    if budget and "static_threshold" in budget["curves"]:
        methods = [m for m in ("batch", "live", "static_threshold", "zscore_only") if m in budget["curves"]]
        head = "".join(f"<th class='n'>{escape(budget['labels'][m])}</th>" for m in methods)
        body = "".join(f"<tr><td class='n'>{n(r['alerts'])}</td>" + "".join(
            f"<td class='n'>{'–' if r['caught'][m] is None else r['caught'][m]}</td>" for m in methods) + "</tr>" for r in budget["budgets"])
        t3 = next(counter)
        parts.append(f"""
<h3>Equal alert budget</h3>
<p>Fewer false alerts can come from alerting less. Each method's sensitivity (confidence cutoff; for the threshold, limits widened by
a fraction of the probationary range) is swept with one setting for all series; the figure plots windows caught against alerts sent,
and Table {t3} gives the best each method achieves within fixed budgets. Selecting the threshold's best margin uses the labels, so its
curve is an upper bound for a static threshold.</p>
{_budget_chart(budget, methods)}
<div class="table-wrap"><table><caption>Table {t3}. Windows caught (of {budget['windows']}) at most at each alert budget; – = the method cannot be that quiet.</caption>
<thead><tr><th class="n">Alerts</th>{head}</tr></thead><tbody>{body}</tbody></table></div>""")
    return "".join(parts) + "</section>"


def _ucr(facts: dict[str, Any], counter) -> str:
    ucr = facts["ucr"]
    if not ucr:
        return ""
    names = {"product": "Ops Signals, router picks", "all_analyzers": LABELS["all_analyzers"], "static_threshold": LABELS["static_threshold"],
             "anomaly_zscore": "Z-score (anomaly_zscore alone)", "pyod_outlier": "pyod_outlier alone", "discord": "Matrix-profile discord (reference)",
             "max_jump": "Largest jump (reference)"}
    rows = "".join(f"<tr class='{'ours' if m == 'product' else ''}'><td>{escape(names.get(m, m))}</td><td class='n'>{v}</td><td class='n'>{pct(v / ucr['series'], 1)}</td></tr>"
                   for m, v in sorted(ucr["correct"].items(), key=lambda kv: -kv[1]))
    extra = ""
    if "only_ours" in ucr:
        extra = (f"<p>Ops Signals locates {ucr['only_ours']} anomalies that neither the threshold nor the z-score locates; the threshold locates "
                 f"{ucr['only_threshold']} that Ops Signals misses. Paired difference with the threshold: {ci(ucr['paired_vs_threshold'], 0)} series, "
                 f"{interval_says(ucr['paired_vs_threshold'])}.</p>")
    found = ", ".join(f"{k} {v}" for k, v in ucr["found_by"].items())
    t = next(counter)
    return f"""
<section><h2>3. UCR Anomaly Archive</h2>
<div class="table-wrap"><table><caption>Table {t}. Series whose single anomaly was located (of {ucr['series']}). Random: {ucr['random']:.1f}.
Ops Signals {ci(ucr['product_ci'], 0)}.</caption>
<thead><tr><th>Method</th><th class="n">Located</th><th class="n">Share</th></tr></thead><tbody>{rows}</tbody></table></div>
{extra}<p class="small">Analyzer behind each correct Ops Signals answer: {escape(found)}.</p></section>"""


def _tcpd(facts: dict[str, Any], counter) -> str:
    tcpd = facts["tcpd"]
    if not tcpd:
        return ""
    rows = "".join(f"<tr class='{'ours' if r['ours'] else ''}'><td>{escape(r['method'])}</td><td class='n'>{r['f1']:.3f}</td><td class='n'>{r['cover']:.3f}</td></tr>"
                   for r in sorted(tcpd["leaderboard"], key=lambda r: -r["f1"]))
    t = next(counter)
    return f"""
<section><h2>4. TCPD</h2>
<div class="table-wrap"><table><caption>Table {t}. Mean F1 and cover over {tcpd['series']} series; published methods from the paper's
default experiment on the same series. Ops Signals, router picks: F1 {ci(tcpd['product_ci'])}.</caption>
<thead><tr><th>Method</th><th class="n">F1</th><th class="n">Cover</th></tr></thead><tbody>{rows}</tbody></table></div>
<p>Router picks minus every analyzer: paired F1 difference {ci(tcpd['paired_vs_all'])}, {interval_says(tcpd['paired_vs_all'])}. A change
detector ran on {tcpd['change_detector_ran']} of {tcpd['series']} series under routing.</p></section>"""


def _smd(facts: dict[str, Any], counter) -> str:
    smd = facts["smd"]
    if not smd:
        return ""
    rows = "".join(
        f"<tr class='{'ours' if k == 'router_picks' else ''}'><td>{escape(m['label'])}</td><td class='n'>{m['caught']}/{m['incidents']}</td>"
        f"<td class='n'>{n(m['false_alerts'])}</td><td class='n'>{pct(m['precision'], 1)}</td><td class='n'>{m['f1']:.3f} <span class='muted'>{ci(m['f1_ci'])}</span></td>"
        f"<td class='n'>{n(m['false_per_day'], 1)}</td></tr>" for k, m in smd["methods"].items())
    paired = (f"<p>Router picks minus static threshold, paired over machines: F1 difference {ci(smd['paired_f1_vs_threshold'])}, "
              f"{interval_says(smd['paired_f1_vs_threshold'])}.</p>" if smd["paired_f1_vs_threshold"] else "")
    t = next(counter)
    return f"""
<section><h2>5. SMD</h2>
<div class="table-wrap"><table><caption>Table {t}. {smd['machines']} machines, batch, confidence ≥ 0.5, no point adjustment.</caption>
<thead><tr><th>Method</th><th class="n">Incidents caught</th><th class="n">False alerts</th><th class="n">Precision</th><th class="n">F1 [95% CI]</th>
<th class="n">False alerts per machine-day</th></tr></thead><tbody>{rows}</tbody></table></div>{paired}</section>"""


def _own(facts: dict[str, Any], counter) -> str:
    behavior, router, analyzers = facts["behavior"], facts["router"], facts["analyzers"]
    if not (behavior or router or analyzers):
        return ""
    parts = ["<section><h2>6. Own scenarios</h2><p>These use this project's own answer keys and serve as regression checks, not independent evidence.</p>"]
    if behavior:
        rows = "".join(f"<tr><td>{escape(s['name'])}</td><td>{escape(s['default'] or '–')}</td><td>{escape(s['all'] or '–')}</td>"
                       f"<td class='small'>{escape('; '.join(s['findings']) or '–')}</td></tr>" for s in behavior["scenarios"])
        parts.append(f"""<div class="table-wrap"><table><caption>Table {next(counter)}. Cross-metric behaviors: routed (default) and every-analyzer mode.</caption>
<thead><tr><th>Scenario</th><th>Routed</th><th>All analyzers</th><th>Named finding (routed)</th></tr></thead><tbody>{rows}</tbody></table></div>""")
    if router:
        parts.append(f"<p>Router scenarios: {', '.join(f'{v} {k}' for k, v in router['counts'].items())} of {router['total']}.</p>")
    if analyzers:
        rows = "".join(
            f"<tr><td class='mono'>{escape(r['analyzer'])}</td><td class='small'>{escape(_cells_text(r['cells']))}</td>"
            f"<td>{escape(r['verdict'])}</td></tr>" for r in analyzers)
        parts.append(f"""<div class="table-wrap"><table><caption>Table {next(counter)}. Each analyzer alone, graded against its kind's bar
(anomaly: ≥ static threshold on catches and false alarms; change: > no-change and within 0.05 of the best published F1; own: target found, controls quiet).</caption>
<thead><tr><th>Analyzer</th><th>Results</th><th>Grade</th></tr></thead><tbody>{rows}</tbody></table></div>""")
    return "".join(parts) + "</section>"


def _cells_text(cells: dict[str, Any]) -> str:
    return "; ".join(f"{name}: {cell['text']}" for name, cell in cells.items() if cell)


def _ablation(facts: dict[str, Any], counter) -> str:
    rows = [r for r in facts["routing"] if r["everything"]]
    choices = facts["choices"]
    if not rows and not choices:
        return ""
    body = "".join(f"<tr><td>{escape(r['dataset'])}</td><td class='small'>{_markup(r['ours']['text'])}</td><td class='small'>{_markup(r['everything']['text'])}</td>"
                   f"<td class='n'>{n(r['ours'].get('analyzer_runs'))} / {n(r['everything'].get('analyzer_runs'))}</td><td class='n'>{pct(r['saving'])}</td></tr>" for r in rows)
    choice_rows = "".join(
        f"<tr><td>{escape(c['dataset'])}</td><td class='n'>{c['right_kind']['hits']}/{c['right_kind']['total']} ({pct(c['right_kind']['share'])})</td>"
        f"<td class='n'>{c['worked']['hits']}/{c['worked']['total']} ({pct(c['worked']['share'])})</td></tr>" for c in choices if c['right_kind']['total'])
    return f"""
<section><h2>7. Ablation: routing against running every analyzer</h2>
<div class="table-wrap"><table><caption>Table {next(counter)}. Same data, same code; analyzer runs count one analyzer on one series (one scheduled run for NAB replay).</caption>
<thead><tr><th>Dataset</th><th>Router picks</th><th>Every analyzer</th><th class="n">Analyzer runs</th><th class="n">Fewer runs</th></tr></thead><tbody>{body}</tbody></table></div>
<div class="table-wrap"><table><caption>Table {next(counter)}. Router choice accuracy: the right kind of analyzer ran (anomaly detector for NAB, UCR and SMD;
change detector for TCPD), and one that on its own gets the case right ran. Target: {pct(choices[0]['bar']) if choices else '80%'}.</caption>
<thead><tr><th>Dataset</th><th class="n">Right kind</th><th class="n">One that worked</th></tr></thead><tbody>{choice_rows}</tbody></table></div></section>"""


def _threats(facts: dict[str, Any]) -> str:
    run = facts["run"]
    items = [
        "<b>Development on the same corpora.</b> Analyzer fixes were designed on a fixed development sample and confirmed on a separate check "
        "sample of NAB, UCR and SMD, then on the full sets; NAB and UCR as a whole were therefore seen during development. A dataset untouched "
        "during development would give a cleaner estimate.",
        "<b>Baselines.</b> The static threshold and z-score are the rules most monitoring uses, not the strongest published detectors; published "
        "detectors are compared only through NAB's official scoreboard and TCPD's published results.",
        "<b>Own scenarios.</b> Router, behavior and per-analyzer checks use this project's own labels and are few; they are regression checks.",
        "<b>SMD metrics are unnamed</b> (38 values scaled to 0–1), so behavior rules that match metric names cannot apply there.",
        "<b>Timings</b> are wall-clock on one machine and only comparable within this run.",
    ]
    if run["sample"]:
        items.insert(0, f"<b>This run used the {escape(run['sample'])} sample,</b> not the full datasets.")
    if run["dirty_files"]:
        items.insert(0, f"<b>Uncommitted changes</b> in {escape(', '.join(run['dirty_files']))}.")
    return f"<section><h2>8. Threats to validity</h2><ul>{''.join(f'<li>{i}</li>' for i in items)}</ul></section>"


def _reproducibility(facts: dict[str, Any], counter) -> str:
    run = facts["run"]
    info = [("Run", run["run_id"]), ("Commit", run["commit"]), ("Commit date", run["commit_date"]), ("Command", run["command"]),
            ("Started", run["started_at"]), ("Finished", run["finished_at"]), ("Wall time", f"{run['hours']:.1f} h"),
            ("Accuracy fingerprint", run["fingerprint"]), ("Python", run["python"]), ("Platform", run["platform"]), ("CPU", run["cpu"]),
            ("Skipped methods", ", ".join(run["skipped_methods"]) or "none")]
    rows = "".join(f"<tr><td>{escape(a)}</td><td class='mono'>{escape(str(b or '–'))}</td></tr>" for a, b in info)
    packages = "".join(f"<tr><td class='mono'>{escape(k)}</td><td class='mono'>{escape(str(v or 'not installed'))}</td></tr>" for k, v in sorted(run["packages"].items()))
    hashes = "".join(f"<tr><td class='mono small'>{escape(k)}</td><td class='mono small'>{escape(v[:16])}…</td></tr>"
                     for k, v in sorted({**run["config_sha256"], **run["dataset_sha256"]}.items()))
    return f"""
<section><h2>9. Reproducibility</h2>
<div class="table-wrap"><table><caption>Table {next(counter)}. Run record.</caption><tbody>{rows}</tbody></table></div>
<details><summary>Package versions</summary><div class="table-wrap"><table><tbody>{packages}</tbody></table></div></details>
<details><summary>Configuration and dataset hashes (SHA-256)</summary><div class="table-wrap"><table><tbody>{hashes}</tbody></table></div></details>
</section>
<footer>Generated by benchmark/evidence from run {escape(run['run_id'] or '')}; every value is computed from that run's results.</footer>"""
