"""Render a finding-trust snapshot (run.py's results.json) as one self-contained HTML page.

    .venv/bin/python -m benchmark.finding_trust.report benchmark/results/<run>/results.json
"""

from __future__ import annotations

import argparse
import json
from html import escape
from pathlib import Path
from typing import Any

from benchmark.finding_trust import events as ev

# The go/no-go agreed before measuring: trust numbers ship only if some finding groups that would
# reach "Needs attention" were real at least this often, on at least MIN_GROUP checked.
GO_RATE = 0.35
# Added after the first full run showed RCAEval's high real rates were mostly chance: a group must
# also be real at least this many times as often as an alarm at a random moment would be.
GO_LIFT = 2.0

_CAUGHT = '<span class="pill good">caught</span>'
_MISSED = '<span class="pill critical">missed</span>'

AGREEMENT_ORDER = {"2+ analyzers": 0, "1 analyzer": 1}


def write_report(payload: dict[str, Any], path: Path) -> Path:
    path.write_text(render(payload), encoding="utf-8")
    return path


def render(payload: dict[str, Any]) -> str:
    step1, step2, step3 = payload.get("step1"), payload.get("step2"), payload.get("step3")
    passing = _passing_groups(step2)
    passing3 = _passing_groups(step3)
    body = "".join(
        [
            _glance(step1, step2, step3, passing, passing3),
            _step1(step1) if step1 and "missing" not in step1 else "",
            _step2(step2, passing) if step2 else "",
            _step3(step3, passing3) if step3 else "",
            _what_users_see(step2),
            _limits(step1, step2, step3),
        ]
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Finding Trust Evidence</title><style>{_CSS}</style></head>
<body><main>
<p class="kicker">Ops Signals · local benchmark report · commit {escape(str(payload.get('commit')))} · {escape(str(payload.get('started_at')))}</p>
<h1>How often were findings real?</h1>
<p class="lede">Every finding should carry a measured number: "findings like this were real X% of the time". This report measures X on public
data whose incidents were marked by outside researchers, for each kind of finding.</p>
{body}
</main></body></html>"""


# ---------------------------------------------------------------- at a glance


def _glance(step1, step2, step3, passing, passing3) -> str:
    results = []
    if step1 and "missing" not in step1:
        live = step1["live_alerts"]
        results.append(f"Live alerts ({_nab_scope(step1.get('category'), step1.get('series_count', 58))}, saved run): <b>{_pct(live['real_rate'])} real</b>, {_pct(live['early_rate'])} just before an incident, {_pct(live['false_rate'])} false.")
    if step2:
        overall = step2["overall"]
        results.append(f"Findings replayed ({_nab_scope(step2.get('category'), len(step2['series']))}): <b>{_pct(overall['real_rate'])} real</b> of {overall['n']}; best and worst groups below.")
    if step3:
        caught = sum(row["caught"] for row in step3["cases"])
        results.append(
            f"Injected faults (RCAEval, {len(step3['cases'])} cases): <b>{caught} caught</b> within {step3['incident_minutes']} minutes; "
            f"{step3['false_alarms_per_metric_hour']} false findings per metric per hour of normal running."
        )
    def names(rows):
        return ", ".join(f"{_type(row['group']['finding_type'])} with {row['group']['agreement']} ({_pct(row['real_rate'])} real, {row['lift']:.1f}× random)" for row in rows)

    parts = []
    if passing is not None:
        parts.append(f"<b>NAB:</b> {names(passing)} pass." if passing else "<b>NAB:</b> no group passes.")
    if passing3 is not None:
        parts.append(f"<b>RCAEval:</b> {names(passing3)} pass." if passing3 else "<b>RCAEval:</b> no group passes.")
    if not parts:
        verdict = ("warning", "Not decided", "Neither replay step ran, so the go/no-go can't be checked.")
    elif passing or passing3:
        verdict = ("good" if passing and passing3 else "warning", "Go, only for the groups named", " ".join(parts) + " Everything else goes to “Context only” or needs fixing first.")
    else:
        verdict = ("critical", "No-go for now", " ".join(parts) + " Fix or filter finding types before showing trust numbers to users.")
    rows = [
        ("What it tests", "For each kind of finding: how often it fell inside a real, marked incident, how often it came just before one, and how often it was a false alarm."),
        ("Data source", f"NAB (Numenta Anomaly Benchmark): {_nab_scope((step2 or step1 or {}).get('category'), len(step2['series']) if step2 else 58)}. "
         f"RCAEval ({escape(step3['system']) if step3 else 'not run'}): faults injected into microservice demo shops, Pham et al. 2024."),
        ("Ground truth", "Incident windows marked by NAB's authors; the recorded fault-injection moment in RCAEval. Not written by this project."),
        ("Our result", "<br>".join(results)),
        ("What good looks like", f"A finding group that reaches “Needs attention” is real at least <b>{_pct(GO_RATE)}</b> of the time (the bar agreed before measuring) "
         f"<b>and</b> at least <b>{GO_LIFT:.0f}×</b> as often as an alarm at a random moment (added after the first full run), on at least {ev.MIN_GROUP} checked."),
    ]
    items = "".join(f"<div><dt>{label}</dt><dd>{value}</dd></div>" for label, value in rows)
    tone, title, detail = verdict
    return f"""<section><h2>At a glance</h2><div class="card">
<p class="verdict"><span class="pill {tone}">{title}</span> {detail}</p><dl class="glance">{items}</dl></div></section>"""


def _passing_groups(step2) -> list[dict[str, Any]] | None:
    if not step2:
        return None
    rows = step2["tables"]["type, agreement"]
    return [row for row in rows if row["n"] >= ev.MIN_GROUP and (row["real_rate"] or 0) >= GO_RATE and (row.get("lift") or 0) >= GO_LIFT]


# ---------------------------------------------------------------- step 1


def _step1(step1) -> str:
    live = step1["live_alerts"]
    analyzer_rows = "".join(
        f"<tr><td>{escape(row['analyzer'])}</td><td class='num'>{row['alerts']}</td>"
        + (
            f"<td class='num'>{_bar(row['real_rate'])}</td><td class='num muted'>{_pct(row['real_rate_low'])}</td>"
            if row["alerts"]
            else "<td colspan='2' class='muted'>no alerts at this setting</td>"
        )
        + f"<td class='num'>{row['incidents_caught']} of {row['incidents']}</td></tr>"
        for row in sorted(step1["analyzers"], key=lambda r: -(r["real_rate"] or -1))
    )
    return f"""<section><h2>Step 1 · What the saved full run already shows</h2>
<p class="lede">Re-read from <code>{escape(step1['run'])}</code>, nothing rerun. Alerts at the headline setting (confidence ≥ {step1['threshold']}).</p>
<div class="card"><h3>The product's live alerts, {_nab_scope(step1.get('category'), step1.get('series_count', 58))}</h3>{_split(live)}
<p class="small muted">“Just before” means within one incident-window length ahead of a marked window. Of alerts with a marked anomaly moment,
{live['warned_first']} of {live['with_lead']} came before that moment (median lead {_minutes(live['median_lead'])}).</p></div>
<div class="card"><h3>Each analyzer on its own (every analyzer run on every series)</h3>
{'<p class="small muted">Across all 58 NAB series: the saved run keeps per-analyzer results only in total.</p>' if step1.get('category') else ''}
<div class="table-wrap"><table><thead><tr><th>Analyzer</th><th class="num">Alerts</th><th class="num">Real</th><th class="num">At least*</th><th class="num">Incidents caught</th></tr></thead>
<tbody>{analyzer_rows}</tbody></table></div>
<p class="small muted">* The lowest real rate the sample supports (95% Wilson lower bound). For us, not for users: users see rates per finding, not per analyzer.</p></div>
</section>"""


# ---------------------------------------------------------------- step 2


def _step2(step2, passing) -> str:
    overall = step2["overall"]
    series = ", ".join(escape(item["series"].split("/")[-1]) for item in step2["series"])
    by_type = _table(step2["tables"]["type"], ("finding_type",))
    by_agreement = _table(
        sorted(step2["tables"]["type, agreement"], key=lambda r: (r["group"]["finding_type"], AGREEMENT_ORDER.get(r["group"]["agreement"], 9))),
        ("finding_type", "agreement"),
        highlight=passing,
    )
    full = _table(step2["tables"]["type, agreement, importance"], ("finding_type", "agreement", "band"))
    combos = _table(step2["tables"]["type, exact analyzers"][:15], ("finding_type", "analyzers"))
    return f"""<section><h2>Step 2 · NAB sample, by kind of finding</h2>
<p class="lede">{_nab_scope(step2.get('category'), len(step2['series']))} replayed the way scheduled runs see them: {series}. Every finding a user would newly see counts,
labeled with its type, whether 2+ analyzers agreed, and its importance.</p>
<div class="card"><h3>All findings</h3>{_split(overall)}</div>
<div class="card"><h3>By type</h3>{by_type}</div>
<div class="card"><h3>By type and agreement</h3><p class="small muted">Highlighted rows meet the bar (≥ {_pct(GO_RATE)} real, ≥ {GO_LIFT:.0f}× random, ≥ {ev.MIN_GROUP} checked).</p>{by_agreement}</div>
<details class="card" open><summary>By type, agreement and importance</summary>{full}</details>
<details class="card"><summary>By type and exact analyzers (top 15)</summary>{combos}</details>
</section>"""


# ---------------------------------------------------------------- step 3


def _step3(step3, passing) -> str:
    fault_rows = "".join(
        f"<tr><td>{escape(row['fault'])}</td><td class='num'>{row['caught']} of {row['cases']}</td><td class='num'>{_minutes(row['median_delay_minutes'])}</td></tr>"
        for row in step3["faults"]
    )
    case_rows = "".join(
        f"<tr><td>{escape(row['case'])}</td><td>{_CAUGHT if row['caught'] else _MISSED}</td>"
        f"<td class='num'>{_minutes(row['delay_minutes'])}</td><td>{escape(row['caught_on'] or '—')}</td><td class='num'>{row['false_alarms']}</td></tr>"
        for row in step3["cases"]
    )
    by_type = _table(step3["tables"]["type"], ("finding_type",))
    by_agreement = _table(step3["tables"]["type, agreement"], ("finding_type", "agreement"), highlight=passing)
    full = _table(step3["tables"]["type, agreement, importance"], ("finding_type", "agreement", "band"))
    combos = _table(step3["tables"]["type, exact analyzers"][:15], ("finding_type", "analyzers"))
    return f"""<section><h2>Step 3 · RCAEval: real faults at a known moment</h2>
<p class="lede">{len(step3['cases'])} cases from {escape(step3['system'])}: CPU, memory, disk, network delay and packet loss injected into one service.
We watch that service's CPU, memory and p95 latency, as {step3.get('settings', {}).get('interval_seconds', 5)}-second points with an analysis run every
{step3.get('settings', {}).get('run_every_seconds', 60)} seconds. A finding within {step3['incident_minutes']} minutes after injection is a catch; any finding
during the normal half hour before it is a false alarm.</p>
{_systems(step3)}
<div class="card"><h3>Faults caught, by fault type</h3>
<div class="table-wrap"><table><thead><tr><th>Fault</th><th class="num">Caught</th><th class="num">Median time to finding</th></tr></thead><tbody>{fault_rows}</tbody></table></div>
<p class="small muted">False findings while nothing was wrong: {step3['false_alarms']} over {step3['metric_hours_normal']} metric-hours,
{step3['false_alarms_per_metric_hour']} per metric per hour. Read “caught” with that in mind: at that rate a 10-minute window over
3 metrics often gets a finding by chance alone, so a catch here is weak evidence on its own; the “vs random” columns are the fair measure.</p></div>
<div class="card"><h3>By type</h3>{by_type}</div>
<div class="card"><h3>By type and agreement</h3><p class="small muted">Highlighted rows meet the bar (≥ {_pct(GO_RATE)} real, ≥ {GO_LIFT:.0f}× random, ≥ {ev.MIN_GROUP} checked).</p>{by_agreement}</div>
<details class="card" open><summary>By type, agreement and importance</summary>{full}</details>
<details class="card"><summary>By type and exact analyzers (top 15)</summary>{combos}</details>
<details class="card"><summary>Every case</summary><div class="table-wrap"><table><thead><tr><th>Case</th><th>Result</th><th class="num">Time to finding</th><th>First caught on</th><th class="num">False findings</th></tr></thead>
<tbody>{case_rows}</tbody></table></div></details>
</section>"""


# ---------------------------------------------------------------- what a user would see


def _what_users_see(step2) -> str:
    if not step2:
        return ""
    tables = step2["tables"]
    seen: set[tuple] = set()
    cards = []
    for record in sorted(step2["events"], key=lambda r: (r["finding_type"], -len(r["analyzers"]), -r["importance"])):
        event = ev.FindingEvent(row=0, finding_type=record["finding_type"], analyzers=tuple(record["analyzers"]), importance=record["importance"], confidence=0)
        key = (event.finding_type, event.agreement)
        if key in seen:
            continue
        seen.add(key)
        found = ev.lookup(event, tables)
        if found is None:
            line = f"No trust number yet: fewer than {ev.MIN_GROUP} findings of this type were checked."
            tone = "info"
        else:
            tone = "good" if found["real_rate"] >= GO_RATE else "warning"
            line = (
                f"Findings like this were real <b>{_pct(found['real_rate'])}</b> of the time ({found['n']} checked"
                f"{'' if found['level'] == 'type, agreement, importance' else ', grouped by ' + found['level']})."
            )
        cards.append(
            f"<div class='mini'><div class='mini-title'>{_type(event.finding_type)} · {escape(event.agreement)} "
            f"<span class='muted'>({escape('+'.join(event.analyzers))})</span></div><p><span class='pill {tone}'>{'Shown' if tone == 'good' else 'Context only' if tone == 'warning' else 'No number'}</span> {line}</p></div>"
        )
    return f"""<section><h2>What a user would see</h2>
<p class="lede">One example per type and agreement, with the trust number it would get from the Step 2 tables (most specific group with
≥ {ev.MIN_GROUP} checked, falling back to a broader one).</p><div class="minis">{''.join(cards)}</div></section>"""


# ---------------------------------------------------------------- limits


def _limits(step1, step2, step3) -> str:
    items = [
        "NAB's windows are wide (about 10% of each series) and centred on the marked anomaly, so “real” is generous and “just before” is rough.",
        "Groups under 30 checked are shown but never used for a user-facing number.",
        "Sock Shop and Train Ticket have only 6-8 minutes of normal running before each fault, so their false-alarm rate rests on little time; Online Boutique has about 35 minutes.",
        "RCAEval faults are injected abruptly, so it measures how fast a finding follows a fault, not early warning. Early warning needs run-to-failure data.",
        "RCAEval data is second-level and runs every 30 seconds; some analyzers are tuned for minute-level data.",
        "Public data is not your system. These numbers are a starting point that a service's own resolved findings replace.",
    ]
    return "<section><h2>Limits</h2><div class='card'><ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul></div></section>"


# ---------------------------------------------------------------- helpers


def _nab_scope(category: str | None, count: int) -> str:
    names = {"realAWSCloudwatch": "cloud-server metrics (AWS CloudWatch)"}
    if category:
        return f"{count} NAB {escape(names.get(category, category))} series"
    return f"{count} NAB series"


def _systems(step3) -> str:
    rows = step3.get("systems") or []
    if not rows:
        return ""
    names = {"RE1-OB": "Online Boutique", "RE1-SS": "Sock Shop", "RE1-TT": "Train Ticket"}
    body = "".join(
        f"<tr><td>{escape(names.get(row['system'], row['system']))}</td><td class='num'>{row['caught']} of {row['cases']}</td>"
        f"<td class='num'>{_minutes(row['median_delay_minutes'])}</td><td class='num'>{row['false_alarms']}</td>"
        f"<td class='num'>{row['metric_hours_normal']}</td><td class='num'>{row['false_alarms_per_metric_hour'] if row['false_alarms_per_metric_hour'] is not None else '—'}</td></tr>"
        for row in rows
    )
    missing = step3.get("missing_metrics") or []
    note = f"<p class='small muted'>Metrics missing from the data, skipped: {escape(', '.join(missing))}.</p>" if missing else ""
    return (
        "<div class='card'><h3>By shop</h3><div class='table-wrap'><table><thead><tr><th>Shop</th><th class='num'>Faults caught</th>"
        "<th class='num'>Median time to finding</th><th class='num'>False findings</th><th class='num'>Normal metric-hours</th>"
        f"<th class='num'>False per metric-hour</th></tr></thead><tbody>{body}</tbody></table></div>{note}</div>"
    )


def _table(rows: list[dict[str, Any]], keys: tuple[str, ...], highlight: list[dict[str, Any]] | None = None) -> str:
    if not rows:
        return "<p class='muted'>No findings.</p>"
    heads = {"finding_type": "Type", "agreement": "Agreement", "band": "Importance", "analyzers": "Analyzers"}
    marked = [row["group"] for row in highlight or []]
    body = "".join(
        f"<tr class='{'hit' if row['group'] in marked else ''}{' small-n' if row['n'] < ev.MIN_GROUP else ''}'>"
        + "".join(f"<td>{_type(row['group'][key]) if key == 'finding_type' else escape(str(row['group'][key]))}</td>" for key in keys)
        + f"<td class='num'>{row['n']}</td><td class='num'>{_bar(row['real_rate'])}</td><td class='num muted'>{_pct(row.get('chance'))}</td>"
        f"<td class='num'>{_lift(row.get('lift'))}</td><td class='num'>{_pct(row['early_rate'])}</td>"
        f"<td class='num'>{_pct(row['false_rate'])}</td><td class='num muted'>{_pct(row['real_rate_low'])}</td></tr>"
        for row in rows
    )
    head = "".join(f"<th>{heads[key]}</th>" for key in keys)
    return (
        f"<div class='table-wrap'><table><thead><tr>{head}<th class='num'>Checked</th><th class='num'>Real</th><th class='num'>Random†</th><th class='num'>vs random</th>"
        f"<th class='num'>Just before</th><th class='num'>False</th><th class='num'>At least*</th></tr></thead><tbody>{body}</tbody></table></div>"
        f"<p class='small muted'>† How often an alarm at a random moment would count as real on the same data (the share of scored time inside incidents). "
        f"* 95% Wilson lower bound on the real rate. Faded rows have fewer than {ev.MIN_GROUP} checked.</p>"
    )


def _split(row: dict[str, Any]) -> str:
    parts = [("real", row["real_rate"], "In a real incident"), ("early", row["early_rate"], "Just before one"), ("false", row["false_rate"], "False alarm")]
    segments = "".join(f"<span class='seg {cls}' style='width:{(value or 0) * 100:.1f}%'></span>" for cls, value, _ in parts)
    legend = "".join(f"<span><i class='dot {cls}'></i>{label}: <b>{_pct(value)}</b></span>" for cls, value, label in parts)
    return f"<p class='big'>{row['n']} checked</p><div class='stack'>{segments}</div><div class='legend'>{legend}</div>"


def _bar(rate: float | None) -> str:
    if rate is None:
        return "—"
    return f"<span class='bar'><span style='width:{rate * 100:.0f}%'></span></span> {_pct(rate)}"


def _lift(value: float | None) -> str:
    if value is None:
        return "—"
    tone = "good" if value >= GO_LIFT else "warning" if value >= 1.2 else "critical"
    return f"<span class='pill {tone}'>{value:.1f}×</span>"


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.0f}%"


def _minutes(value: float | None) -> str:
    if value is None:
        return "—"
    if abs(value) >= 120:
        return f"{value / 60:.1f} h"
    return f"{value:.1f} min" if abs(value) < 10 else f"{value:.0f} min"


def _type(value: str) -> str:
    return escape(ev.TYPE_LABELS.get(value, value))


_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--text:#1d2330;--muted:#5b6475;--line:#e3e6ec;--good:#1f8a4c;--good-bg:#e6f4ec;--warn:#b26a00;--warn-bg:#fdf1dc;
--bad:#b4232c;--bad-bg:#fbe7e8;--info:#2b5fb8;--info-bg:#e7eefb;--track:#d9dde5;--real:#1f8a4c;--early:#c98a1a;--false:#b9bfca;--hit:#eef8f1}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#12151b;--card:#1b2029;--text:#e6e9ef;--muted:#9aa3b4;--line:#2a313d;
--good:#5cc98a;--good-bg:#1b3326;--warn:#f0b45a;--warn-bg:#3a2c14;--bad:#f07a80;--bad-bg:#3a1d20;--info:#7fa6f0;--info-bg:#1c2a44;--track:#343c4a;
--real:#4fb57c;--early:#d9a441;--false:#4a5262;--hit:#1a2a20}}
:root[data-theme="dark"]{--bg:#12151b;--card:#1b2029;--text:#e6e9ef;--muted:#9aa3b4;--line:#2a313d;--good:#5cc98a;--good-bg:#1b3326;--warn:#f0b45a;
--warn-bg:#3a2c14;--bad:#f07a80;--bad-bg:#3a1d20;--info:#7fa6f0;--info-bg:#1c2a44;--track:#343c4a;--real:#4fb57c;--early:#d9a441;--false:#4a5262;--hit:#1a2a20}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:1040px;margin:0 auto;padding:28px 16px 64px}h1{font-size:26px;margin:4px 0 6px}h2{font-size:19px;margin:36px 0 8px}h3{font-size:15px;margin:0 0 10px}
.kicker{color:var(--muted);font-size:13px;margin:0}.lede{color:var(--muted);margin:0 0 14px;max-width:820px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:12px}
details.card summary{cursor:pointer;font-weight:600}details.card[open] summary{margin-bottom:10px}
.glance{display:grid;gap:10px;margin:12px 0 0}.glance div{display:grid;grid-template-columns:180px 1fr;gap:12px}
@media (max-width:640px){.glance div{grid-template-columns:1fr;gap:2px}}
dt{font-weight:600;color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.03em}dd{margin:0}
.verdict{margin:0;font-size:15px}.pill{display:inline-block;font-size:12px;font-weight:600;border-radius:12px;padding:2px 10px;margin-right:6px}
.pill.good{background:var(--good-bg);color:var(--good)}.pill.warning{background:var(--warn-bg);color:var(--warn)}
.pill.critical{background:var(--bad-bg);color:var(--bad)}.pill.info{background:var(--info-bg);color:var(--info)}
.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
th{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.03em}.num{text-align:right}
tr.hit td{background:var(--hit)}tr.small-n td{opacity:.55}
.bar{display:inline-block;width:70px;height:7px;background:var(--track);border-radius:4px;overflow:hidden;vertical-align:middle;margin-right:6px}
.bar span{display:block;height:100%;background:var(--real)}
.big{font-size:18px;font-weight:700;margin:0 0 6px}.stack{display:flex;height:14px;border-radius:7px;overflow:hidden;background:var(--track)}
.seg.real{background:var(--real)}.seg.early{background:var(--early)}.seg.false{background:var(--false)}
.legend{display:flex;gap:18px;flex-wrap:wrap;font-size:14px;margin-top:8px}.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}
.dot.real{background:var(--real)}.dot.early{background:var(--early)}.dot.false{background:var(--false)}
.small{font-size:13px}.muted{color:var(--muted)}code{font-size:13px}
.minis{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
.mini{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}.mini-title{font-weight:600;margin-bottom:6px}.mini p{margin:0}
ul{margin:0;padding-left:20px}li{margin-bottom:6px}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild a finding-trust report from its results.json")
    parser.add_argument("results", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.results.read_text(encoding="utf-8"))
    print(write_report(payload, args.results.with_name("report.html")))


if __name__ == "__main__":
    main()
