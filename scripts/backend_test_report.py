#!/usr/bin/env python3
"""Run the backend tests and write an HTML report that lists every test with what it checks and its
result, grouped by test file. Meant for reading what the suite covers, not for CI.

Everything in the report comes from the code: "What it checks" is the test name as a sentence plus
its docstring, "Purpose" is the test file's docstring, and "Expected" is the part of the name from
its first verb on ("..._is_not_a_trend") - left empty when the name has no such verb, never guessed.

Qdrant is pointed at an unreachable URL, as in CI, so a test that escapes the in-memory guard fails
instead of writing to dev data (CLAUDE.md, Traps).

Usage:
    ./scripts/backend_test_report.py                                 # whole suite, ~4 min
    ./scripts/backend_test_report.py tests/test_trend_analyzer.py    # extra args go to pytest
    ./scripts/backend_test_report.py --from-xml results.xml          # render an earlier run, no tests run
"""
from __future__ import annotations

import argparse
import ast
import html
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT_DIR / "tmp" / "reports"
# Playwright specs, not pytest.
DEFAULT_PYTEST_ARGS = ["--ignore=tests/scenarios/integration"]

# The first of these in a test name starts its expected outcome: "trend_analyzer | emits_finding_rule_metadata".
VERBS = {
    "is", "isnt", "are", "arent", "was", "stays", "stay", "becomes", "remains", "does", "doesnt", "do", "dont",
    "should", "must", "can", "cant", "cannot", "never", "always", "only", "returns", "return", "raises", "raise",
    "rejects", "refuses", "fails", "passes", "keeps", "skips", "shows", "hides", "gets", "has", "have",
    "uses", "creates", "emits", "suppresses", "writes", "reads", "finds", "matches", "ignores", "includes",
    "excludes", "counts", "reports", "ranks", "records", "sends", "posts", "links", "names", "says", "adds",
    "removes", "drops", "deletes", "updates", "stores", "saves", "loads", "lists", "falls", "picks", "groups",
    "marks", "flags", "detects", "treats", "survives", "handles", "accepts", "allows", "blocks", "limits",
    "requires", "needs", "works", "runs", "starts", "stops", "opens", "closes", "resolves", "merges", "splits",
    "maps", "builds", "parses", "renders", "explains", "describes", "wins", "beats", "prefers",
    "fits", "measures", "sets", "gives", "takes", "tells", "points", "sorts", "orders", "caps", "truncates", "turns",
    "routes", "recommends", "redacts", "masks", "leaves", "clears", "resets", "retries", "times", "persists",
}

RESULT_LABELS = {"passed": "Passed", "failed": "Failed", "error": "Error", "skipped": "Skipped"}


@dataclass
class TestRow:
    file: str
    name: str
    params: str
    sentence: str
    expected: str
    docstring: str
    result: str
    seconds: float
    message: str


def run_pytest(pytest_args: list[str], xml_path: Path) -> int:
    env = {**os.environ, "OPS_SIGNALS_QDRANT_URL": os.environ.get("OPS_SIGNALS_QDRANT_URL", "http://localhost:6399")}
    python = ROOT_DIR / ".venv" / "bin" / "python"
    command = [
        str(python if python.exists() else sys.executable), "-m", "pytest", "-q", "-p", "no:cacheprovider",
        "--continue-on-collection-errors", "-o", "junit_family=xunit1", f"--junitxml={xml_path}", *pytest_args,
    ]
    print("Running:", " ".join(command[1:]), flush=True)
    return subprocess.run(command, cwd=ROOT_DIR, env=env).returncode


def humanize(words: list[str]) -> str:
    text = " ".join(word for word in words if word)
    return text[:1].upper() + text[1:]


def split_name(name: str) -> tuple[str, str, str]:
    """test_x_is_not_y[case] -> ("X is not y", "is not y", "case")."""
    base, _, params = name.partition("[")
    words = base.removeprefix("test_").split("_")
    verb_at = next((index for index, word in enumerate(words) if word in VERBS), None)
    expected = humanize(words[verb_at:]) if verb_at is not None else ""
    return humanize(words), expected, params.rstrip("]")


def docstrings(path: Path) -> tuple[str, dict[str, str]]:
    """The file's docstring and each test's, keyed by "name" and "Class::name"."""
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError):
        return "", {}
    tests: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            tests[node.name] = ast.get_docstring(node) or ""
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    tests[f"{node.name}::{child.name}"] = ast.get_docstring(child) or ""
    return ast.get_docstring(tree) or "", tests


def outcome(case: ET.Element) -> tuple[str, str]:
    for tag in ("failure", "error", "skipped"):
        element = case.find(tag)
        if element is not None:
            message = element.get("message") or (element.text or "")
            return ("failed" if tag == "failure" else tag), message.strip()
    return "passed", ""


def read_results(xml_path: Path) -> tuple[list[TestRow], dict[str, str]]:
    rows: list[TestRow] = []
    purposes: dict[str, str] = {}
    cache: dict[str, dict[str, str]] = {}
    for case in ET.parse(xml_path).getroot().iter("testcase"):
        file = case.get("file") or case.get("classname", "").replace(".", "/") + ".py"
        if file not in cache:
            purposes[file], cache[file] = docstrings(ROOT_DIR / file)
        name = case.get("name", "")
        test_class = case.get("classname", "").rsplit(".", 1)[-1]
        base = name.partition("[")[0]
        docstring = cache[file].get(f"{test_class}::{base}") or cache[file].get(base, "")
        sentence, expected, params = split_name(name)
        result, message = outcome(case)
        rows.append(TestRow(file, name, params, sentence, expected, docstring, result, float(case.get("time") or 0), message))
    return rows, purposes


def first_paragraph(text: str) -> str:
    return " ".join(text.strip().split("\n\n")[0].split())


def file_title(file: str) -> str:
    return humanize(Path(file).stem.removeprefix("test_").split("_"))


def render(rows: list[TestRow], purposes: dict[str, str], source: str) -> str:
    totals = Counter(row.result for row in rows)
    by_file: dict[str, list[TestRow]] = defaultdict(list)
    for row in rows:
        by_file[row.file].append(row)
    seconds = sum(row.seconds for row in rows)
    documented = sum(1 for row in rows if row.docstring)
    verdict = "All tests passed." if not (totals["failed"] or totals["error"]) else (
        f"{totals['failed'] + totals['error']} test(s) did not pass. They are listed first and their files are open."
    )
    e = html.escape

    failing = [row for row in rows if row.result in ("failed", "error")]
    failing_html = "".join(
        f'<li><code>{e(row.file)}::{e(row.name)}</code><br><span class="msg">{e(row.message[:400])}</span></li>' for row in failing
    )

    groups = []
    for file in sorted(by_file, key=lambda f: (not any(r.result in ("failed", "error") for r in by_file[f]), f)):
        file_rows = by_file[file]
        counts = Counter(row.result for row in file_rows)
        bad = counts["failed"] + counts["error"]
        badge = f'<span class="pill failed">{bad} failed</span>' if bad else f'<span class="pill passed">{counts["passed"]} passed</span>'
        if counts["skipped"]:
            badge += f' <span class="pill skipped">{counts["skipped"]} skipped</span>'
        purpose = first_paragraph(purposes.get(file, "")) or "No file docstring."
        body = "".join(
            f'<tr data-result="{row.result}">'
            f'<td><code>{e(row.name)}</code></td>'
            f'<td>{e(row.sentence)}{f" <span class=muted>({e(row.params)})</span>" if row.params else ""}'
            f'{f"<div class=doc>{e(first_paragraph(row.docstring))}</div>" if row.docstring else ""}</td>'
            f'<td>{e(row.expected) or "<span class=muted>-</span>"}</td>'
            f'<td><span class="pill {row.result}">{RESULT_LABELS.get(row.result, row.result)}</span> <span class=muted>{row.seconds:.2f}s</span>'
            f'{f"<div class=msg>{e(row.message[:400])}</div>" if row.message else ""}</td></tr>'
            for row in file_rows
        )
        groups.append(
            f'<details class="group"{" open" if bad else ""}><summary><b>{e(file_title(file))}</b> '
            f'<code class="muted">{e(file)}</code> {badge}<div class="purpose">{e(purpose)}</div></summary>'
            f'<div class="table-wrap"><table><thead><tr><th>Test</th><th>What it checks</th><th>Expected</th><th>Result</th></tr></thead>'
            f'<tbody>{body}</tbody></table></div></details>'
        )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Backend Test Report</title>
<style>
:root {{ --bg:#f7f7f8; --panel:#fff; --text:#1d1d22; --muted:#6b6b76; --border:#e3e3e8; --pass:#1f7a46; --pass-bg:#e5f4ea;
  --fail:#b42318; --fail-bg:#fde8e6; --skip:#8a5a00; --skip-bg:#fbf0d9; --accent:#5b3fd1; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#141418; --panel:#1d1d23; --text:#ececf1;
  --muted:#9a9aa6; --border:#30303a; --pass:#6fd39a; --pass-bg:#16301f; --fail:#ff8a7f; --fail-bg:#3a1714; --skip:#f0c060;
  --skip-bg:#33280f; --accent:#a996ff; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:14px/1.5 -apple-system, system-ui, sans-serif; }}
main {{ max-width:1200px; margin:0 auto; padding:24px 16px 64px; }}
h1 {{ margin:0 0 4px; font-size:24px; }} h2 {{ font-size:17px; margin:28px 0 10px; }}
.muted {{ color:var(--muted); }} code {{ font:12px ui-monospace, Menlo, monospace; word-break:break-all; }}
.glance {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(170px, 1fr)); gap:10px; margin-top:16px; }}
.card {{ background:var(--panel); border:1px solid var(--border); border-radius:10px; padding:12px 14px; }}
.card b {{ display:block; font-size:22px; }} .card span {{ color:var(--muted); font-size:12px; }}
.verdict {{ margin-top:12px; padding:12px 14px; border-radius:10px; background:var(--panel); border-left:4px solid var(--accent); }}
.controls {{ display:flex; flex-wrap:wrap; gap:8px; margin:20px 0 12px; }}
.controls input {{ flex:1 1 260px; padding:8px 10px; border:1px solid var(--border); border-radius:8px; background:var(--panel); color:var(--text); }}
.controls button {{ padding:7px 12px; border:1px solid var(--border); border-radius:8px; background:var(--panel); color:var(--text); cursor:pointer; }}
.controls button[aria-pressed="true"] {{ border-color:var(--accent); color:var(--accent); font-weight:600; }}
.group {{ background:var(--panel); border:1px solid var(--border); border-radius:10px; margin-bottom:8px; }}
.group summary {{ cursor:pointer; padding:10px 14px; }} .purpose {{ color:var(--muted); font-size:13px; margin-top:2px; }}
.table-wrap {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; }}
th, td {{ text-align:left; vertical-align:top; padding:8px 14px; border-top:1px solid var(--border); }}
th {{ font-size:12px; color:var(--muted); font-weight:600; }}
td:first-child {{ width:30%; }} td:nth-child(3) {{ width:22%; }} td:last-child {{ width:16%; white-space:nowrap; }}
.doc {{ color:var(--muted); font-size:13px; margin-top:4px; }}
.msg {{ color:var(--fail); font:12px ui-monospace, Menlo, monospace; white-space:pre-wrap; margin-top:4px; }}
.pill {{ display:inline-block; padding:1px 8px; border-radius:999px; font-size:12px; font-weight:600; }}
.passed {{ background:var(--pass-bg); color:var(--pass); }} .failed, .error {{ background:var(--fail-bg); color:var(--fail); }}
.skipped {{ background:var(--skip-bg); color:var(--skip); }}
ul.failing {{ padding-left:18px; }} ul.failing li {{ margin-bottom:8px; }}
</style></head>
<body><main>
<h1>Backend test report</h1>
<div class="muted">{e(datetime.now().strftime("%d %b %Y, %H:%M"))} · {e(source)}</div>

<h2>At a glance</h2>
<div class="glance">
  <div class="card"><b>{len(rows)}</b><span>tests in {len(by_file)} files</span></div>
  <div class="card"><b>{totals["passed"]}</b><span>passed</span></div>
  <div class="card"><b>{totals["failed"] + totals["error"]}</b><span>failed or errored</span></div>
  <div class="card"><b>{totals["skipped"]}</b><span>skipped</span></div>
  <div class="card"><b>{seconds / 60:.1f} min</b><span>time in tests</span></div>
  <div class="card"><b>{documented}</b><span>tests with a docstring</span></div>
</div>
<div class="verdict">{e(verdict)} "What it checks" is the test name as a sentence; "Expected" is the name from its first
verb on, empty when the name has none. Only {documented} of {len(rows)} tests have a docstring, so most rows rely on the name.</div>
{f'<h2>Did not pass</h2><ul class="failing">{failing_html}</ul>' if failing else ""}

<h2>All tests by file</h2>
<div class="controls">
  <input id="q" type="search" placeholder="Search test names, descriptions, files..." aria-label="Search tests">
  <button data-filter="all" aria-pressed="true">All</button>
  <button data-filter="failed" aria-pressed="false">Failed</button>
  <button data-filter="skipped" aria-pressed="false">Skipped</button>
  <button id="expand">Open all</button>
</div>
<div id="groups">{"".join(groups)}</div>
</main>
<script>
let filter = 'all';
const q = document.getElementById('q');
function apply() {{
  const term = q.value.trim().toLowerCase();
  document.querySelectorAll('.group').forEach((group) => {{
    const fileMatch = group.querySelector('summary').textContent.toLowerCase().includes(term);
    let shown = 0;
    group.querySelectorAll('tbody tr').forEach((row) => {{
      const result = row.dataset.result;
      const okResult = filter === 'all' || result === filter || (filter === 'failed' && result === 'error');
      const ok = okResult && (!term || fileMatch || row.textContent.toLowerCase().includes(term));
      row.hidden = !ok; if (ok) shown++;
    }});
    group.hidden = shown === 0;
    if (term || filter !== 'all') group.open = shown > 0;
  }});
}}
q.addEventListener('input', apply);
document.querySelectorAll('[data-filter]').forEach((button) => button.addEventListener('click', () => {{
  filter = button.dataset.filter;
  document.querySelectorAll('[data-filter]').forEach((b) => b.setAttribute('aria-pressed', String(b === button)));
  apply();
}}));
document.getElementById('expand').addEventListener('click', (event) => {{
  const open = event.target.textContent === 'Open all';
  document.querySelectorAll('.group:not([hidden])').forEach((group) => {{ group.open = open; }});
  event.target.textContent = open ? 'Close all' : 'Open all';
}});
</script>
</body></html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from-xml", type=Path, help="render this JUnit XML instead of running the tests")
    parser.add_argument("--out", type=Path, help=f"report path (default {DEFAULT_OUT_DIR.relative_to(ROOT_DIR)}/backend-tests-<date>.html)")
    args, pytest_args = parser.parse_known_args()

    exit_code = 0
    if args.from_xml:
        xml_path, source = args.from_xml, f"from {args.from_xml}"
    else:
        xml_path = Path(tempfile.mkdtemp(prefix="backend-test-report-")) / "results.xml"
        pytest_args = pytest_args or DEFAULT_PYTEST_ARGS
        exit_code = run_pytest(pytest_args, xml_path)
        source = "pytest " + " ".join(pytest_args)
        if not xml_path.exists():
            print("pytest wrote no results (it stopped before running tests); see the output above.", file=sys.stderr)
            return exit_code or 1

    rows, purposes = read_results(xml_path)
    out = args.out or DEFAULT_OUT_DIR / f"backend-tests-{datetime.now():%Y-%m-%d}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(rows, purposes, source))
    print(f"Report: {out}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
