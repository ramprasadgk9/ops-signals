"""The award report: why a team should use Ops Signals, for judges who are not specialists.

Every figure comes from build_facts. A claim is only made when the data supports it: each headline
tile and each "what it does" statement has a condition, and when it fails the point moves to the
"where it falls short" section with its real numbers instead.
"""

from __future__ import annotations

import re
from html import escape
from typing import Any

from benchmark.evidence.html import change, n, one_in, page, pct
from benchmark.report_html import _budget_chart

# What each analyzer finds and why an operations team cares. Descriptions only; grades and evidence
# come from the run's scorecard.
ANALYZERS = {
    "stumpy": ("Unusual stretches", "A day, a job or a traffic curve unlike all the others, even inside normal limits"),
    "ruptures": ("The moment a metric changes for good", "Latency or cost that stepped up after a deploy and stayed there"),
    "baseline_shift": ("A metric settling at a new level", "The same need as ruptures, reported as a before and after level"),
    "trend": ("Slow, steady drift", "Memory, disk or spend creeping towards a limit, weeks before anything pages"),
    "data_health": ("Gaps and stuck values", "A collector outage or a frozen exporter: blind spots every other check misses"),
    "pyod_outlier": ("Spikes and outlier points", "CPU spikes, latency bursts, error bursts"),
    "seasonal_anomaly": ("Values unusual for the time of day", "Traffic at 3 a.m. that belongs at noon"),
    "anomaly_zscore": ("Values far from the recent average", "The classic rule, kept for comparison"),
}

NAB_CATEGORIES = {
    "artificialNoAnomaly": "artificial series without incidents",
    "artificialWithAnomaly": "artificial series with incidents",
    "realAWSCloudwatch": "AWS server metrics",
    "realAdExchange": "ad-exchange prices",
    "realKnownCause": "incidents with a known cause",
    "realTraffic": "road-traffic sensors",
    "realTweets": "Twitter volume",
}

CSS = """
body{font:16px/1.6 "IBM Plex Sans",-apple-system,"Segoe UI",Roboto,sans-serif}
h1,h2,h3{font-family:"Archivo","Helvetica Neue",Arial,sans-serif;font-stretch:87%;line-height:1.15;text-wrap:balance;margin:0}
h1{font-size:clamp(30px,5vw,44px);font-weight:700}h2{font-size:clamp(22px,3vw,28px);font-weight:700}h3{font-size:18px;font-weight:600}
p{margin:0}.read{max-width:700px}.stack{display:grid;gap:12px}
.eyebrow{font:500 12px/1.4 "IBM Plex Mono",ui-monospace,monospace;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
section{padding-block:40px 0;display:grid;gap:16px}
header.hero{padding-block:44px 32px;display:grid;gap:16px;border-bottom:1px solid var(--line)}
.lede{font-size:18.5px;max-width:700px}
.claims{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}
.claim{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:18px;display:grid;gap:6px;align-content:start}
.claim .big{font:700 42px/1 "Archivo",Arial,sans-serif;font-stretch:87%;color:var(--accent);font-variant-numeric:tabular-nums}
.claim .what{font-weight:600}.claim .how{font-size:14px;color:var(--muted)}
.flow{display:flex;flex-wrap:wrap;gap:8px}
.step{flex:1 1 150px;background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:12px 14px;display:grid;gap:4px;align-content:start}
.step b{font-family:"Archivo",Arial,sans-serif;font-stretch:87%}.step span{font-size:13.5px;color:var(--muted)}
.step.key{border-color:var(--accent);background:var(--accent-soft)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:20px;display:grid;gap:14px}
.bars{display:grid;gap:10px}.bar-row{display:grid;grid-template-columns:190px 1fr 96px;gap:12px;align-items:center}
.bar-row .val{font:500 14px "IBM Plex Mono",monospace;text-align:right}
.track{height:22px;background:var(--quiet-soft);border-radius:3px;display:flex;overflow:hidden;gap:2px}
.seg.real,.seg.ours{background:var(--accent)}.seg.false{background:var(--bad);opacity:.8}.seg.base{background:var(--quiet)}
@media (max-width:560px){.bar-row{grid-template-columns:1fr 80px}.bar-row .label{grid-column:1/-1}}
.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.fact{border-top:2px solid var(--line);padding-top:10px;display:grid;gap:2px}
.fact .v{font:600 24px/1.2 "Archivo",Arial,sans-serif;font-stretch:87%}.fact .t{font-size:14px;color:var(--muted)}
dl.terms{display:grid;grid-template-columns:minmax(150px,210px) 1fr;gap:10px 20px;margin:0;font-size:14.5px}
dl.terms dt{font-weight:600}dl.terms dd{margin:0;color:var(--muted)}
@media (max-width:560px){dl.terms{grid-template-columns:1fr;gap:2px}}
.limit{display:grid;grid-template-columns:auto 1fr;gap:12px;padding:12px 14px;border-radius:6px;background:var(--warn-soft)}
.tag{font:600 11px/1 "IBM Plex Mono",monospace;letter-spacing:.06em;text-transform:uppercase;padding:5px 7px;border-radius:3px;
color:var(--warn);border:1px solid var(--warn);white-space:nowrap;align-self:start}
ul{margin:0;padding-left:20px;display:grid;gap:6px}
footer{margin-top:44px;padding-top:14px;border-top:1px solid var(--line);font-size:13px;color:var(--muted);display:grid;gap:6px}
"""


def _markup(text: str) -> str:
    """Routing cell text from benchmark.report_html carries its own tags; show it as plain text."""
    return escape(" ".join(re.sub(r"<[^>]+>", " ", text).split()))


def render(facts: dict[str, Any]) -> str:
    limits: list[str] = []
    sections = [
        _hidden_problems(facts, limits),
        _alert_load(facts, limits),
        _analyzers(facts),
        _routing(facts, limits),
    ]
    _more_limits(facts, limits)
    body = "".join([
        _hero(facts),
        _design(),
        _terms(),
        *[s for s in sections if s],
        _limits(limits),
        _method(facts),
        _footer(facts),
    ])
    return page("Ops Signals Award Evidence", CSS, body)


# --- headline ---------------------------------------------------------------------------------


def _hero(facts: dict[str, Any]) -> str:
    tiles = []
    ucr = facts["ucr"]
    if ucr and ucr.get("only_ours"):
        static = ucr["correct"].get("static_threshold")
        ratio = f", {ucr['correct']['product'] / static:.1f}× the threshold's {static}" if static else ""
        tiles.append((str(ucr["only_ours"]), "hidden anomalies found that thresholds miss",
                      f"Out of {ucr['series']} recordings, neither a static threshold nor a z-score rule found these. "
                      f"Ops Signals found {ucr['correct']['product']} in total{ratio}."))
    budget = (facts["nab"] or {}).get("budget")
    if budget:
        untuned = {m: u for m, u in budget["untuned"].items() if u["best_threshold"] and u["usual"]["caught"] >= u["best_threshold"]["caught"]}
        if untuned:
            mode, u = max(untuned.items(), key=lambda kv: kv[1]["usual"]["caught"] - kv[1]["best_threshold"]["caught"])
            tiles.append(("0", "thresholds to tune, and no loss for it",
                          f"At its default setting, Ops Signals ({'live alerts' if mode == 'live' else 'batch review'}) catches "
                          f"{u['usual']['caught']} of {budget['windows']} real incidents with {n(u['usual']['alerts'])} alerts. The best "
                          f"threshold allowed no more alerts catches {u['best_threshold']['caught']}, and finding its setting needed the answer key."))
    savings = [r for r in facts["routing"] if r["saving"] is not None]
    if savings:
        low, high = min(r["saving"] for r in savings), max(r["saving"] for r in savings)
        holds = sum(r["verdict"][0] == "good" for r in savings)
        tiles.append((f"−{low * 100:.0f}%" if round(low * 100) == round(high * 100) else f"−{low * 100:.0f}–{high * 100:.0f}%",
                      "detector runs, from routing",
                      f"The router runs a few specialists per metric instead of all of them, and matches or beats running everything on "
                      f"{holds} of {len(savings)} datasets."))
    tile_html = "".join(f"<div class='claim'><div class='big'>{escape(big)}</div><div class='what'>{escape(what)}</div>"
                        f"<div class='how'>{escape(how)}</div></div>" for big, what, how in tiles)
    return f"""
<header class="hero">
  <p class="eyebrow">Ops Signals · benchmark evidence · run {escape(facts['run']['run_id'] or '')}{f" · {escape(facts['run']['sample'])} sample, not the full datasets" if facts['run']['sample'] else ''}</p>
  <h1>The problems thresholds never see, without more alerts to chase</h1>
  <p class="lede">Most teams watch their metrics with fixed thresholds. They get a flood of alerts, and still miss the problems that never
  cross a line: a disk filling slowly, a collector that went silent, a cost that stepped up after a deploy. Ops Signals reads the shape of
  each metric and sends it to the few detectors built for that shape, for live alerts and for reviewing stored history, with no line to
  set per metric. These results come from public datasets whose answer keys were written by outside researchers.</p>
  <div class="claims">{tile_html}</div>
</header>"""


def _design() -> str:
    return """
<section>
  <div class="read stack"><p class="eyebrow">The design</p>
  <h2>A triage step picks the specialists for each metric</h2>
  <p>A metric can go wrong in several ways: spike, move to a new level and stay there, drift slowly, stop reporting, get stuck, or take on
  an unusual shape. No single rule sees all of these, and running every detector on every metric multiplies alerts and compute. Ops Signals
  profiles each metric first, then routes it to the detectors that fit.</p></div>
  <div class="flow">
    <div class="step"><b>Profile</b><span>Measure the metric's shape: spikiness, level shifts, daily cycle, trend, gaps.</span></div>
    <div class="step key"><b>Route</b><span>Book the best detector for each shape found, up to 3, plus a data-quality check.</span></div>
    <div class="step"><b>Detect</b><span>Specialists for spikes, lasting changes, unusual stretches, drift, gaps and stuck values.</span></div>
    <div class="step"><b>Diagnose</b><span>Behavior rules combine findings across metrics into a named problem, such as "server slow".</span></div>
  </div>
</section>"""


def _terms() -> str:
    terms = [
        ("Metric", "One series of numbers over time, such as a server's CPU use every 5 minutes."),
        ("Analyzer", "One detector looking for one kind of problem. The router picks which analyzers run on each metric."),
        ("Alert", "What someone would look into. Flags less than 15 minutes (or one reading) apart count as one alert, for every method."),
        ("Incident", "A real problem marked in the dataset's answer key, with a window of time around it. Caught means at least one alert inside it."),
        ("False alert", "An alert outside every incident window: someone would investigate it and find nothing."),
        ("F1 score", "One number from 0 to 1 balancing incidents caught against false alerts. 1 is every incident, no false alert."),
        ("Static threshold", "The usual way to alert: fixed limits, here the range seen in the first 15% of each metric, treated as healthy."),
        ("Alert budget", "A number of alerts a team is willing to look at. Comparing methods at the same budget shows which one is smarter, not just quieter."),
        ("Live and batch", "Live: each metric replayed in time order, as it would arrive. Batch: a whole stored history analyzed at once."),
    ]
    rows = "".join(f"<dt>{escape(a)}</dt><dd>{escape(b)}</dd>" for a, b in terms)
    return f"""
<section id="terms"><div class="read stack"><p class="eyebrow">Terms used on this page</p><h2>What the words mean</h2></div>
<div class="panel"><dl class="terms">{rows}</dl></div></section>"""


# --- claims ---------------------------------------------------------------------------------


def _hidden_problems(facts: dict[str, Any], limits: list[str]) -> str:
    ucr, tcpd, behavior = facts["ucr"], facts["tcpd"], facts["behavior"]
    parts = []
    if ucr and "static_threshold" in ucr["correct"]:
        c = ucr["correct"]
        width = lambda v: f"{v / ucr['series'] * 100:.1f}%"
        bars = "".join(
            f"<div class='bar-row'><span class='label'>{label}</span><div class='track'><div class='seg {cls}' style='width:{width(v)}'></div></div>"
            f"<span class='val'>{v} / {ucr['series']}</span></div>"
            for label, v, cls in [("<b>Ops Signals</b>", c["product"], "ours"), ("Static threshold", c["static_threshold"], "base"),
                                  ("Z-score rule", c.get("anomaly_zscore", 0), "base")])
        parts.append(f"""
  <div class="panel">
    <h3>Anomalies that never cross a line</h3>
    <p class="small">The UCR Anomaly Archive holds {ucr['series']} long recordings (heartbeats, gait, power use, spacecraft telemetry), each
    hiding one abnormal stretch. Many stay inside the normal range, like a heartbeat with the wrong shape, so no threshold can see them.
    The test is to point at the stretch.</p>
    <div class="bars">{bars}</div>
    <div class="facts">
      <div class="fact"><span class="v">{ucr['only_ours']}</span><span class="t">found by Ops Signals and by neither a threshold nor a z-score rule</span></div>
      <div class="fact"><span class="v">{ucr['both']}</span><span class="t">found by both Ops Signals and the threshold</span></div>
      <div class="fact"><span class="v">{ucr['only_threshold']}</span><span class="t">found by the threshold and missed by Ops Signals</span></div>
    </div>
    <p class="small muted">A random guess locates about {ucr['random']:.0f}.{f" A matrix-profile discord search alone, a research method, locates {c['discord']}." if 'discord' in c else ''}</p>
  </div>""")
        if c["product"] <= c["static_threshold"]:
            limits.append(f"<b>On UCR, Ops Signals locates {c['product']} of {ucr['series']} anomalies, not more than the threshold's {c['static_threshold']}.</b>")
    if tcpd and tcpd.get("best_published"):
        best = tcpd["best_published"]
        standing = ("above every one of the" if tcpd["rank"] == 1 else f"ranked {tcpd['rank']} of the")
        parts.append(f"""
  <div class="panel"><h3>Moments a metric changed for good</h3>
    <p class="small">On TCPD, the Turing Change Point Dataset, five people marked where each of {tcpd['series']} real series changed for good.
    Ops Signals scores <b>F1 {tcpd['product_f1']:.3f}</b>, {standing} {tcpd['published_count']} published methods on their default settings
    (best: {escape(best['method'])} {best['f1']:.3f}){f", against {tcpd['no_change_f1']:.3f} for never reporting a change" if tcpd['no_change_f1'] is not None else ''}.</p></div>""")
    if behavior and behavior["scenarios"]:
        example = next((s for s in behavior["scenarios"] if s["default"] == "PASS" and s["findings"]), None)
        example_html = (f"<div class='panel' style='gap:4px;background:var(--paper)'><span class='mono' style='color:var(--bad)'>"
                        f"{escape(example['findings'][0])}</span><span class='small muted mono'>from {escape(', '.join(example['metrics']))}</span></div>"
                        if example else "")
        parts.append(f"""
  <div class="panel"><h3>A diagnosis instead of separate alerts</h3>
    <p class="small">Behavior rules combine findings from related metrics into one named problem, so the on-call engineer starts from a
    likely cause. With normal routing Ops Signals named the right problem in {behavior['passed']} of {len(behavior['scenarios'])} cross-metric
    scenarios. These scenarios are our own and few, so they show the feature works end to end, not how often it is right in the field.</p>
    {example_html}</div>""")
    if not parts:
        return ""
    return f"""
<section><div class="read stack"><p class="eyebrow">Problems found that would be missed</p>
<h2>What a threshold can't see</h2></div>{''.join(parts)}</section>"""


def _alert_load(facts: dict[str, Any], limits: list[str]) -> str:
    nab = facts["nab"]
    if not nab:
        return ""
    fair = _fair_test(nab, limits)
    if "static_threshold" not in nab["methods"] or not nab["methods"]["static_threshold"]["alerts"]:
        # The threshold method was skipped: no usual-setting comparison, but the fair test has its own threshold curve.
        return (f"<section><div class='read stack'><p class='eyebrow'>Alert load</p><h2>Fewer false leads, tested fairly</h2></div>{fair}</section>"
                if fair else "")
    methods = nab["methods"]
    shown = [m for m in ("static_threshold", "live", "batch") if m in methods and methods[m]["alerts"]]
    base = methods["static_threshold"]["alerts"]
    top = max(methods[m]["alerts"]["alerts"] for m in shown)
    bars = "".join(
        f"<div class='bar-row'><span class='label'>{escape(methods[m]['label'])}</span><div class='track'>"
        f"<div class='seg real' style='width:{methods[m]['alerts']['real'] / top * 100:.1f}%'></div>"
        f"<div class='seg false' style='width:{methods[m]['alerts']['false'] / top * 100:.1f}%'></div></div>"
        f"<span class='val'>{n(methods[m]['alerts']['alerts'])}</span></div>" for m in shown)
    rows = "".join(
        f"<tr><td>{escape(methods[m]['label'])}</td><td class='n'>{n(methods[m]['alerts']['alerts'])}</td>"
        f"<td class='n'>{n(methods[m]['alerts']['false'])}{'' if m == 'static_threshold' else ' (' + change(base['false'], methods[m]['alerts']['false']) + ')'}</td>"
        f"<td class='n'>{one_in(methods[m]['alerts']['real'], methods[m]['alerts']['alerts'])}</td>"
        f"<td class='n'>{methods[m]['caught']} of {methods[m]['windows']}</td><td class='n'>{methods[m]['f1']:.3f}</td></tr>" for m in shown)
    live = methods.get("live")
    if live and live["caught"] < methods["static_threshold"]["caught"]:
        worst = max(nab["category_gaps"], key=lambda g: g["threshold_only"] - g["ours_only"], default=None)
        where = (f" The largest gap is in {escape(NAB_CATEGORIES.get(worst['category'], worst['category']))}: {worst['threshold_only']} incidents the threshold catches and Ops Signals misses."
                 if worst and worst["threshold_only"] else "")
        limits.append(f"<b>At its usual setting, Ops Signals catches fewer NAB incidents than a threshold: {live['caught']} of {live['windows']}, "
                      f"against {methods['static_threshold']['caught']}.</b> It also sends far fewer alerts.{where}")
    return f"""
<section><div class="read stack"><p class="eyebrow">Alert load</p><h2>Fewer false leads, tested fairly</h2>
<p>NAB, the Numenta Anomaly Benchmark, holds {nab['series']} metrics ({escape(', '.join(NAB_CATEGORIES.get(c, c) for c in nab['categories']))})
with {nab['windows']} incidents marked by its authors. Each metric was replayed in time order as a live system would see it, and analyzed
whole as in a review of stored history. The comparison is a static threshold on the same data.</p></div>
<div class="panel">
  <div class="bars">{bars}</div>
  <div class="legend"><span class="legend-item"><span style="display:inline-block;width:12px;height:12px;background:var(--accent)"></span>alert during a real incident</span>
  <span class="legend-item"><span style="display:inline-block;width:12px;height:12px;background:var(--bad);opacity:.8"></span>false alert</span></div>
  <div class="table-wrap"><table><thead><tr><th>Usual setting</th><th class="n">Alerts</th><th class="n">False</th><th class="n">Real</th>
  <th class="n">Incidents caught</th><th class="n">F1</th></tr></thead><tbody>{rows}</tbody></table></div>
  <p class="small muted">Each at its usual setting. Sending fewer alerts can simply mean speaking up less, so this table alone can't say
  whether Ops Signals is smarter or quieter. The next panel answers that.</p>
</div>{fair}</section>"""


def _fair_test(nab: dict[str, Any], limits: list[str]) -> str:
    budget = nab.get("budget")
    if not budget or "static_threshold" not in budget["curves"]:
        return ""
    methods = [m for m in ("batch", "live", "static_threshold") if m in budget["curves"]]
    lines = []
    for mode, t in budget["tallies"].items():
        label = budget["labels"][mode]
        lines.append(f"<li><b>{escape(label)}</b>: more incidents than the best threshold at {t['more']} of {t['budgets']} alert budgets, "
                     f"as many at {t['same']}, fewer at {t['fewer']}.</li>")
        if t["fewer"] > t["more"]:
            limits.append(f"<b>{escape(label)}: for the same number of alerts, a well-tuned threshold catches more incidents at {t['fewer']} of "
                          f"{t['budgets']} alert budgets</b> (more at {t['more']}, the same at {t['same']}).")
    head = "".join(f"<th class='n'>{escape(budget['labels'][m])}</th>" for m in methods)
    body = "".join(f"<tr><td class='n'>{n(r['alerts'])}</td>" + "".join(
        f"<td class='n'>{'–' if r['caught'][m] is None else r['caught'][m]}</td>" for m in methods) + "</tr>" for r in budget["budgets"])
    untuned_rows = "".join(
        f"<tr><td>{escape(budget['labels'][m])}</td><td class='n'><b>{u['usual']['caught']}</b> caught · {n(u['usual']['alerts'])} alerts</td>"
        f"<td class='n'>{'–' if not u['best_threshold'] else str(u['best_threshold']['caught']) + ' caught · ' + n(u['best_threshold']['alerts']) + ' alerts'}</td></tr>"
        for m, u in budget["untuned"].items())
    return f"""
<div class="panel"><h3>The fair test: the same number of alerts</h3>
  <p class="small">Each method's sensitivity was turned through many settings, one setting for all metrics at a time. The higher a line at
  a given number of alerts, the more real incidents it catches for the same alerts. The threshold's line is the best of several limit
  settings, and choosing among them needed the answer key: it is the best a threshold can do with hindsight.</p>
  <ul class="small">{''.join(lines)}</ul>
  {_budget_chart(budget, methods)}
  <div class="table-wrap"><table><thead><tr><th class="n">Alert budget</th>{head}</tr></thead><tbody>{body}</tbody></table></div>
  <h3>No tuning needed?</h3>
  <p class="small">A team setting up alerts has no answer key. They pick a line per metric and adjust it after missed incidents and noisy
  weeks. Ops Signals learns each metric's normal behavior itself and ran on its default setting. Its default against the best threshold
  allowed no more alerts:</p>
  <div class="table-wrap"><table><thead><tr><th></th><th class="n">Ops Signals, default</th><th class="n">Best threshold, tuned with the answer key</th></tr></thead>
  <tbody>{untuned_rows}</tbody></table></div>
</div>"""


def _analyzers(facts: dict[str, Any]) -> str:
    rows = []
    for row in facts["analyzers"]:
        finds, why = ANALYZERS.get(row["analyzer"], ("", ""))
        evidence = "; ".join(
            f"{name.upper() if name != 'own' else 'Own tests'}: {c['text']}" + (f" ({c['detail']})" if name != "own" and c.get("detail") else "")
            for name, c in row["cells"].items() if c)
        grade = {"good": ("good", "Good"), "weak": ("weak", "Weak")}.get(row["verdict"], ("mid", "Not graded"))
        rows.append(f"<tr><td class='mono'>{escape(row['analyzer'])}</td><td>{escape(finds)}</td><td class='small'>{escape(why)}</td>"
                    f"<td class='small'>{escape(evidence) or '–'}</td><td><span class='pill {grade[0]}'>{grade[1]}</span></td></tr>")
    if not rows:
        return ""
    return f"""
<section><div class="read stack"><p class="eyebrow">The analyzers, one by one</p><h2>Each specialist, graded on its own</h2>
<p>Each analyzer is graded against a bar set in advance. Anomaly detectors must match or beat a static threshold on both incidents
caught and false alarms. Change detectors must beat "never report a change" and come within 0.05 of the best published method. Every
analyzer must find its own test case and stay quiet on healthy metrics. A weak analyzer costs little: the router only picks it where it fits.</p></div>
<div class="panel table-wrap"><table style="min-width:860px"><thead><tr><th>Analyzer</th><th>Finds</th><th>Why a team cares</th><th>Evidence</th><th>Grade</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div></section>"""


def _routing(facts: dict[str, Any], limits: list[str]) -> str:
    rows = [r for r in facts["routing"] if r["everything"]]
    if not rows:
        return ""
    body = "".join(
        f"<tr><td>{escape(r['dataset'])}</td><td class='small'>{_markup(r['ours']['text'])}</td><td class='small'>{_markup(r['everything']['text'])}</td>"
        f"<td class='n'>{pct(r['saving'])}</td><td class='small'>{escape(r['verdict'][1])}</td></tr>" for r in rows)
    for c in facts["choices"]:
        share = c["right_kind"]["share"]
        if share is not None and share < c["bar"]:
            limits.append(f"<b>On {escape(c['dataset'])} the router picks the right kind of detector {pct(share)} of the time; the target is {pct(c['bar'])}.</b>")
    return f"""
<section><div class="read stack"><p class="eyebrow">Why route instead of running everything</p>
<h2>The router is what keeps it affordable</h2>
<p>The obvious alternative to routing is running every detector on every metric. Both ran on the same data with the same code.</p></div>
<div class="panel table-wrap"><table><thead><tr><th>Dataset</th><th>Router picks</th><th>Every detector</th><th class="n">Fewer runs</th><th>Verdict</th></tr></thead>
<tbody>{body}</tbody></table></div></section>"""


def _more_limits(facts: dict[str, Any], limits: list[str]) -> None:
    smd = facts["smd"]
    if smd and "router_picks" in smd["methods"]:
        ours = smd["methods"]["router_picks"]
        static = smd["methods"].get("static_threshold")
        vs = (f" A static threshold scores F1 {static['f1']:.3f} there, against {ours['f1']:.3f}." if static and static["f1"] > ours["f1"] else "")
        if ours["precision"] < 0.25 or vs:
            limits.append(f"<b>Busy multi-metric servers are still noisy.</b> On {smd['machines']} servers of the Server Machine Dataset, Ops Signals "
                          f"caught {ours['caught']} of {ours['incidents']} incidents, with {pct(ours['precision'])} of its alerts real.{vs}")
    nab = facts["nab"]
    official = (nab or {}).get("official")
    if official:
        ours = next((r for r in official["board"] if r["label"] == "Ops Signals, live alerts"), None)
        published = [r["standard"] for r in official["published"] if r["standard"] is not None and r["detector"] not in ("null", "random")]
        if ours and published:
            limits.append(f"<b>On NAB's official score Ops Signals scores {ours['standard']:.1f}</b> (0 = never alarm, 100 = perfect), where "
                          f"published detectors score {min(published):.1f} to {max(published):.1f}. NAB's score rewards alerting early in each window.")


def _limits(limits: list[str]) -> str:
    if not limits:
        return ""
    items = "".join(f"<div class='limit'><span class='tag'>Limit</span><p class='small'>{item}</p></div>" for item in limits)
    return f"""
<section><div class="read stack"><p class="eyebrow">Trade-offs and limits</p><h2>Where it falls short today</h2></div>
<div class="stack">{items}</div></section>"""


def _method(facts: dict[str, Any]) -> str:
    run = facts["run"]
    return f"""
<section><div class="read stack"><p class="eyebrow">How to check these numbers</p><h2>Method</h2>
<ul class="small">
  <li><b>Outside answer keys.</b> NAB, UCR, TCPD and SMD labels come with the published datasets. Only the cross-metric scenarios and the
  per-analyzer test cases are this project's own.</li>
  <li><b>Product as shipped.</b> Ops Signals numbers are the router's own choice of detectors in default settings, counting findings at
  confidence 0.5 or above.</li>
  <li><b>One run.</b> Every number on this page comes from run <span class="mono">{escape(run['run_id'] or '')}</span> of commit
  <span class="mono">{escape((run['commit'] or '')[:12])}</span>{', with uncommitted changes' if run['dirty_files'] else ''}{f", on the {escape(run['sample'])} sample" if run['sample'] else ''}.
  The companion publication report lists every setting, package version and data hash.</li>
  <li><b>Reproducible.</b> One command re-runs it: <span class="mono">{escape(run['command'] or 'python -m benchmark.run_all')}</span>.</li>
</ul></div></section>"""


def _footer(facts: dict[str, Any]) -> str:
    return f"""
<footer><p>Generated by benchmark/evidence from run {escape(facts['run']['run_id'] or '')}; every figure is computed from that run's results.
Data: NAB (Numenta), UCR Anomaly Archive (Wu &amp; Keogh), TCPD (van den Burg &amp; Williams), SMD (OmniAnomaly).</p></footer>"""
