"""Formatting and page chrome shared by the evidence reports."""

from __future__ import annotations

from html import escape
from typing import Any

FONTS = ("https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@87,600;87,700"
         "&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500"
         "&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap")

# Light palette on :root, the dark one under both the OS setting and an explicit theme choice.
# Series colors are the validated reference palette the benchmark report uses (benchmark/report_html.py).
_LIGHT = ("--paper:#f6f7f4;--panel:#ffffff;--ink:#16212b;--muted:#56626d;--line:#dde2de;--accent:#0e7c66;--accent-soft:#e1f1ec;"
          "--warn:#a36200;--warn-soft:#fbf0dc;--bad:#ad3f2c;--bad-soft:#f8e6e2;--quiet:#a3aeb8;--quiet-soft:#e9edf0;"
          "--series:#2a78d6;--detected:#eb6834;--series-3:#1baf7a;--series-4:#eda100;--grid:#e6e9e6;--ink-3:#7d8791;--surface:#ffffff")
_DARK = ("color-scheme:dark;--paper:#0e1419;--panel:#151d24;--ink:#e6ebef;--muted:#9aa7b2;--line:#27323b;--accent:#44c6a6;"
         "--accent-soft:#12302a;--warn:#e3a647;--warn-soft:#33260f;--bad:#e8745f;--bad-soft:#3a1c17;--quiet:#5d6a75;--quiet-soft:#1f2931;"
         "--series:#3987e5;--detected:#d95926;--series-3:#199e70;--series-4:#c98500;--grid:#222c34;--ink-3:#7f8b96;--surface:#151d24")

BASE_CSS = f"""
:root{{{_LIGHT}}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{{_DARK}}}}}
:root[data-theme="dark"]{{{_DARK}}}
*{{box-sizing:border-box}}
body{{background:var(--paper);color:var(--ink);margin:0;padding-inline:16px;padding-block:0 48px}}
.wrap{{max-width:1040px;margin:0 auto}}
.mono{{font-family:"IBM Plex Mono",ui-monospace,Menlo,monospace;font-size:.9em}}
.muted{{color:var(--muted)}}.small{{font-size:14px}}
.table-wrap{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:14.5px}}
th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{font:500 12px "IBM Plex Mono",ui-monospace,monospace;letter-spacing:.04em;text-transform:uppercase;color:var(--muted)}}
td.n,th.n{{font-variant-numeric:tabular-nums;white-space:nowrap}}
tr.ours td{{background:var(--accent-soft)}}
.pill{{display:inline-block;padding:2px 8px;border-radius:10px;font-weight:600;font-size:12px;white-space:nowrap}}
.pill.good{{color:var(--accent);background:var(--accent-soft)}}.pill.weak{{color:var(--bad);background:var(--bad-soft)}}
.pill.mid{{color:var(--warn);background:var(--warn-soft)}}
details summary{{cursor:pointer;color:var(--muted)}}
/* equal-alert-budget chart, drawn by benchmark.report_html._budget_chart */
.chart{{margin:8px 0}}.chart figcaption{{font-size:13px;color:var(--muted);margin-bottom:6px}}
.chart svg{{width:100%;height:auto;display:block;overflow:visible}}.chart svg.budget{{aspect-ratio:720/320}}
.chart .grid{{stroke:var(--grid);stroke-width:1}}.chart .axis{{fill:var(--ink-3);font-size:11px}}
.budget .curve{{fill:none;stroke-width:2.5;vector-effect:non-scaling-stroke;stroke-linejoin:round;stroke-linecap:round}}
.budget .usual{{fill:var(--surface);stroke-width:2.5;stroke-dasharray:none}}.budget .end-label{{fill:var(--ink);font-size:12px;font-weight:600}}
.ab-live{{stroke:var(--series)}}.ab-batch{{stroke:var(--series-3)}}.ab-static_threshold{{stroke:var(--detected);stroke-dasharray:6 4}}
.ab-zscore_only{{stroke:var(--series-4);stroke-dasharray:2 3}}
.legend{{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12.5px;color:var(--muted);margin-top:4px}}
.legend-item{{display:inline-flex;align-items:center;gap:6px}}
.swatch{{display:inline-block;width:16px;height:0;border-top:2px solid}}
.swatch.ab-live{{border-color:var(--series)}}.swatch.ab-batch{{border-color:var(--series-3)}}
.swatch.ab-static_threshold{{border-color:var(--detected);border-top-style:dashed}}.swatch.ab-zscore_only{{border-color:var(--series-4);border-top-style:dotted}}
"""


def page(title: str, css: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS}">
<style>{BASE_CSS}{css}</style></head>
<body><div class="wrap">{body}</div></body></html>
"""


def n(value: Any, digits: int = 0) -> str:
    if value is None:
        return "–"
    if isinstance(value, float) and digits:
        return f"{value:,.{digits}f}"
    return f"{round(value):,}"


def pct(value: float | None, digits: int = 0) -> str:
    return "–" if value is None else f"{value * 100:.{digits}f}%"


def ci(interval: tuple[float, float] | None, digits: int = 3) -> str:
    return "" if not interval else f"[{interval[0]:.{digits}f}, {interval[1]:.{digits}f}]"


def one_in(real: int, alerts: int) -> str:
    return "–" if not real else f"1 in {alerts / real:.1f}"


def change(before: float, after: float) -> str:
    """-52% style change, rounded to a whole percent."""
    return "–" if not before else f"{(after - before) / before * 100:+.0f}%".replace("-", "−")


def interval_says(interval: tuple[float, float] | None) -> str:
    """Plain words for a paired difference interval."""
    if not interval:
        return "not enough series to tell"
    low, high = interval
    if low > 0:
        return "higher, beyond series-to-series variation"
    if high < 0:
        return "lower, beyond series-to-series variation"
    return "within series-to-series variation (the interval includes no difference)"
