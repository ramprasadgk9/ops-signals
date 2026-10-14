"""Builds the charts for docs/analyzers-explained.md, and optionally a PDF of that guide.

    .venv/bin/python scripts/build_analyzer_guide.py                 # rewrite the SVG charts
    .venv/bin/python scripts/build_analyzer_guide.py --pdf out.pdf   # charts, then print the PDF

The charts use illustrative data, not measured results. The PDF is printed from the Markdown by the
frontend's Playwright Chromium (`cd frontend && npx playwright install chromium`), so the guide has
one source and the PDF can't drift from it. The PDF isn't committed: generate it when you need it.
"""

from __future__ import annotations

import argparse
import html
import re
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GUIDE = REPO / "docs" / "analyzers-explained.md"
CHART_DIR = REPO / "docs" / "diagrams" / "analyzers"

FONT = "system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
INK = "#16233a"
MUTED = "#5b6b82"
GRID = "#e3eaf3"
CARD = "#f6f9fd"
CARD_EDGE = "#d9e3ef"
BLUE = "#2563b8"
ORANGE = "#e07b28"
RED = "#d63b3b"
SHADE = "#fbe3e3"

WIDTH, HEIGHT = 720, 230
LEFT, RIGHT, TOP, BOTTOM = 64, 696, 50, 186


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _card(title: str, body: str, height: int = HEIGHT) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}" width="{WIDTH}" '
        f'height="{height}" font-family="{FONT}" role="img" aria-label="{_esc(title)}">\n'
        f'<rect x="1" y="1" width="{WIDTH - 2}" height="{height - 2}" rx="10" fill="{CARD}" stroke="{CARD_EDGE}"/>\n'
        f'<text x="20" y="28" font-size="14" font-weight="700" fill="{INK}">{_esc(title)}</text>\n'
        f"{body}</svg>\n"
    )


class Plot:
    """Maps data to the plot area and draws the shared axes: three gridlines and the x labels."""

    def __init__(self, x_labels: list[str], values: list[float], *, y_min: float | None = None, y_max: float | None = None):
        self.x_labels = x_labels
        low, high = min(values), max(values)
        pad = (high - low) * 0.15 or 1.0
        self.y_min = low - pad if y_min is None else y_min
        self.y_max = high + pad if y_max is None else y_max

    def x(self, index: float) -> float:
        return LEFT + (RIGHT - LEFT) * index / max(len(self.x_labels) - 1, 1)

    def y(self, value: float) -> float:
        return BOTTOM - (BOTTOM - TOP) * (value - self.y_min) / (self.y_max - self.y_min)

    def axes(self, every: int = 1) -> str:
        parts = []
        for value in (self.y_min, (self.y_min + self.y_max) / 2, self.y_max):
            y = self.y(value)
            parts.append(f'<line x1="{LEFT}" y1="{y:.1f}" x2="{RIGHT}" y2="{y:.1f}" stroke="{GRID}"/>')
            parts.append(f'<text x="{LEFT - 8}" y="{y + 4:.1f}" font-size="11" fill="{MUTED}" text-anchor="end">{value:,.0f}</text>')
        for index, label in enumerate(self.x_labels):
            if index % every == 0:
                parts.append(f'<text x="{self.x(index):.1f}" y="{BOTTOM + 20}" font-size="11" fill="{MUTED}" text-anchor="middle">{_esc(label)}</text>')
        return "\n".join(parts) + "\n"

    def line(self, values: list[float], color: str = BLUE, *, dots: bool = True, dashed: bool = False, width: float = 3) -> str:
        points = " ".join(f"{self.x(i):.1f},{self.y(v):.1f}" for i, v in enumerate(values))
        dash = ' stroke-dasharray="6 5"' if dashed else ""
        out = f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round"{dash}/>\n'
        if dots:
            out += "".join(f'<circle cx="{self.x(i):.1f}" cy="{self.y(v):.1f}" r="3.5" fill="{color}"/>' for i, v in enumerate(values)) + "\n"
        return out

    def band(self, lower: list[float], upper: list[float], color: str = ORANGE) -> str:
        top = [f"{self.x(i):.1f},{self.y(v):.1f}" for i, v in enumerate(upper)]
        bottom = [f"{self.x(i):.1f},{self.y(v):.1f}" for i, v in reversed(list(enumerate(lower)))]
        return f'<polygon points="{" ".join(top + bottom)}" fill="{color}" fill-opacity="0.14"/>\n'

    def mark(self, index: float, value: float, label: str, *, anchor: str = "middle", dx: int = 0, dy: int = -12) -> str:
        x, y = self.x(index), self.y(value)
        return (
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{RED}" stroke="#fff" stroke-width="2"/>\n'
            f'<text x="{x + dx:.1f}" y="{y + dy:.1f}" font-size="12" font-weight="600" fill="{RED}" text-anchor="{anchor}">{_esc(label)}</text>\n'
        )

    def vline(self, index: float, label: str) -> str:
        x = self.x(index)
        return (
            f'<line x1="{x:.1f}" y1="{TOP - 4}" x2="{x:.1f}" y2="{BOTTOM}" stroke="{RED}" stroke-width="1.5" stroke-dasharray="4 4"/>\n'
            f'<text x="{x + 6:.1f}" y="{TOP + 8}" font-size="12" font-weight="600" fill="{RED}">{_esc(label)}</text>\n'
        )

    def span(self, start: float, end: float, label: str) -> str:
        x1, x2 = self.x(start), self.x(end)
        return (
            f'<rect x="{x1:.1f}" y="{TOP - 4}" width="{x2 - x1:.1f}" height="{BOTTOM - TOP + 4}" fill="{SHADE}"/>\n'
            f'<text x="{(x1 + x2) / 2:.1f}" y="{TOP + 8}" font-size="12" font-weight="600" fill="{RED}" text-anchor="middle">{_esc(label)}</text>\n'
        )


def legend(items: list[tuple[str, str, bool]]) -> str:
    """Top-right legend: (label, color, is_band)."""
    out, x = [], RIGHT
    for label, color, is_band in reversed(items):
        x -= 7 * len(label) + 34
        swatch = (
            f'<rect x="{x}" y="18" width="18" height="10" fill="{color}" fill-opacity="0.25"/>'
            if is_band
            else f'<line x1="{x}" y1="23" x2="{x + 18}" y2="23" stroke="{color}" stroke-width="3"/>'
        )
        out.append(f'{swatch}<text x="{x + 24}" y="27" font-size="11" fill="{MUTED}">{_esc(label)}</text>')
    return "\n".join(out) + "\n"


FIVE_MIN = ["10:00", "10:05", "10:10", "10:15", "10:20", "10:25", "10:30", "10:35"]


def baseline_shift() -> str:
    values = [620, 622, 619, 618, 425, 428, 422, 426]
    plot = Plot(FIVE_MIN, values)
    before = plot.y(620)
    after = plot.y(425)
    body = plot.axes() + (
        f'<line x1="{LEFT}" y1="{before:.1f}" x2="{plot.x(3.5):.1f}" y2="{before:.1f}" stroke="{ORANGE}" stroke-width="2" stroke-dasharray="6 5"/>\n'
        f'<line x1="{plot.x(3.5):.1f}" y1="{after:.1f}" x2="{RIGHT}" y2="{after:.1f}" stroke="{ORANGE}" stroke-width="2" stroke-dasharray="6 5"/>\n'
        f'<text x="{plot.x(0.2):.1f}" y="{before - 10:.1f}" font-size="12" font-weight="600" fill="{ORANGE}">old normal ~620 ms</text>\n'
        f'<text x="{plot.x(5.2):.1f}" y="{after - 10:.1f}" font-size="12" font-weight="600" fill="{ORANGE}">new normal ~425 ms</text>\n'
    ) + plot.line(values)
    return _card("Latency (ms)", body)


def ruptures() -> str:
    values = [35, 36, 34, 35, 78, 81, 79, 80]
    plot = Plot(FIVE_MIN, values)
    return _card("CPU (%)", plot.axes() + plot.vline(3.5, "change point ~10:18 (deploy at 10:17)") + plot.line(values))


def zscore() -> str:
    values = [40, 41, 39, 40, 96, 40, 41, 39]
    plot = Plot(FIVE_MIN, values)
    normal = plot.band([34] * 8, [46] * 8, BLUE)
    note = f'<text x="{RIGHT - 4}" y="{plot.y(46) - 6:.1f}" font-size="11" fill="{MUTED}" text-anchor="end">usual range</text>\n'
    return _card("CPU (%)", plot.axes() + normal + note + plot.line(values) + plot.mark(4, 96, "96% - far from average", dy=-12))


def pyod() -> str:
    values = [40, 42, 39, 41, 43, 40, 85, 41]
    labels = [f"#{i}" for i in range(1, 9)]
    plot = Plot(labels, values)
    dots = "".join(f'<circle cx="{plot.x(i):.1f}" cy="{plot.y(v):.1f}" r="6" fill="{BLUE}"/>' for i, v in enumerate(values) if v != 85)
    return _card("Readings (each dot is one reading)", plot.axes() + dots + "\n" + plot.mark(6, 85, "85 - doesn't fit the others"))


def trend() -> str:
    hours = ["9 AM", "10 AM", "11 AM", "12 PM", "1 PM", "2 PM", "3 PM", "4 PM", "5 PM"]
    values = [40, 46, 51, 57, 64, 69, 76, 83, 90]
    plot = Plot(hours, values)
    fit = [40 + 6.25 * i for i in range(len(hours))]
    return _card("Memory (%)", plot.axes() + legend([("readings", BLUE, False), ("fitted trend", ORANGE, False)]) + plot.line(fit, ORANGE, dots=False, dashed=True, width=2) + plot.line(values))


def stumpy() -> str:
    labels = ["Mon AM", "Mon noon", "Mon PM", "Tue AM", "Tue noon", "Tue PM", "Wed AM", "Wed noon", "Wed PM", "Thu AM"]
    values = [30, 75, 35, 34, 78, 32, 34, 95, 88, 40]
    plot = Plot(labels, values)
    return _card("CPU (%) - a daily surge that usually returns to normal", plot.axes() + plot.span(6.5, 8.6, "unusual stretch") + plot.line(values))


def prophet() -> str:
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    actual = [1050, 1180, 1400, 1320, 1560, 860, 1450]
    expected = [1040, 1190, 1380, 1300, 1580, 850, 700]
    plot = Plot(days, actual + expected)
    band = plot.band([v * 0.88 for v in expected], [v * 1.12 for v in expected])
    body = plot.axes() + legend([("actual", BLUE, False), ("expected", ORANGE, False), ("expected range", ORANGE, True)]) + band
    body += plot.line(expected, ORANGE, width=2.5) + plot.line(actual) + plot.mark(6, 1450, "1,450 vs ~700 expected", anchor="end", dy=-12)
    return _card("Requests per day", body)


def seasonal() -> str:
    hours = ["12 AM", "2 AM", "4 AM", "6 AM", "8 AM", "10 AM", "12 PM", "2 PM", "4 PM", "6 PM", "8 PM", "10 PM"]
    usual = [22, 20, 21, 35, 70, 88, 60, 55, 52, 45, 35, 26]
    actual = list(usual)
    actual[1] = 90
    plot = Plot(hours, usual + actual, y_min=0, y_max=110)
    band = plot.band([v - 8 for v in usual], [v + 8 for v in usual])
    body = plot.axes() + legend([("today", BLUE, False), ("usual for this hour", ORANGE, True)]) + band + plot.line(actual)
    body += plot.mark(1, 90, "90% at 2 AM - unusual", anchor="start", dx=12, dy=4)
    body += f'<text x="{plot.x(5):.1f}" y="{plot.y(88) - 14:.1f}" font-size="12" font-weight="600" fill="{MUTED}" text-anchor="middle">90% at 10 AM - normal</text>\n'
    return _card("CPU (%) by hour of day", body)


def data_health() -> str:
    values = [40, 42, 45, 45, 45, 45, 45, 45]
    plot = Plot(FIVE_MIN, values, y_min=36, y_max=50)
    return _card("Memory (%)", plot.axes() + plot.span(2, 7, "exactly 45.0 - not changing") + plot.line(values))


def flow() -> str:
    steps = [("Raw metrics", "CPU, latency"), ("Profile + route", "Choose methods"), ("Analyzers", "Detect behavior"), ("Findings", "Plain language"), ("Investigate", "Correlate evidence")]
    box_w, gap, top = 118, 22, 20
    start = (WIDTH - (len(steps) * box_w + (len(steps) - 1) * gap)) / 2
    parts = []
    for i, (name, sub) in enumerate(steps):
        x = start + i * (box_w + gap)
        parts.append(
            f'<rect x="{x:.1f}" y="{top}" width="{box_w}" height="74" rx="9" fill="#eaf1fb" stroke="#b9cde8"/>'
            f'<text x="{x + box_w / 2:.1f}" y="{top + 33}" font-size="13" font-weight="700" fill="{INK}" text-anchor="middle">{_esc(name)}</text>'
            f'<text x="{x + box_w / 2:.1f}" y="{top + 54}" font-size="11" fill="{MUTED}" text-anchor="middle">{_esc(sub)}</text>'
        )
        if i:
            ax = x - gap
            parts.append(
                f'<line x1="{ax + 3:.1f}" y1="{top + 37}" x2="{x - 4:.1f}" y2="{top + 37}" stroke="{BLUE}" stroke-width="2"/>'
                f'<path d="M{x - 9:.1f},{top + 32} L{x - 3:.1f},{top + 37} L{x - 9:.1f},{top + 42}" fill="none" stroke="{BLUE}" stroke-width="2"/>'
            )
    parts.append(f'<text x="{WIDTH / 2}" y="{top + 112}" font-size="12" fill="{MUTED}" text-anchor="middle">Investigation outcomes can become reusable operational cases</text>')
    height = 150
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}" width="{WIDTH}" height="{height}" '
        f'font-family="{FONT}" role="img" aria-label="Raw metrics, profile and route, analyzers, findings, investigate">\n'
        f'<rect x="1" y="1" width="{WIDTH - 2}" height="{height - 2}" rx="10" fill="#ffffff" stroke="{CARD_EDGE}"/>\n'
        + "\n".join(parts)
        + "\n</svg>\n"
    )


CHARTS = {
    "flow": flow,
    "baseline-shift": baseline_shift,
    "ruptures": ruptures,
    "zscore": zscore,
    "pyod-outlier": pyod,
    "trend": trend,
    "stumpy": stumpy,
    "prophet": prophet,
    "seasonal-anomaly": seasonal,
    "data-health": data_health,
}


def write_charts() -> None:
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    for name, build in CHARTS.items():
        (CHART_DIR / f"{name}.svg").write_text(build(), encoding="utf-8")


def _inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)


def markdown_to_html(markdown: str) -> str:
    """Just the Markdown this guide uses: headings, paragraphs, images, lists, quotes and tables."""
    out: list[str] = []
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == "<!-- pdf: page break -->":
            out.append('<div style="break-after: page"></div>')
            i += 1
            continue
        if not line.strip() or line.startswith("<!--"):
            i += 1
            continue
        if heading := re.match(r"(#{1,3}) (.*)", line):
            level = len(heading.group(1))
            # GitHub's anchor for the heading, so in-page links like (#one-page-comparison) work.
            anchor = re.sub(r"[^a-z0-9 -]", "", heading.group(2).lower()).replace(" ", "-")
            out.append(f'<h{level} id="{anchor}">{_inline(heading.group(2))}</h{level}>')
            i += 1
        elif image := re.match(r"!\[([^\]]*)\]\(([^)]+)\)", line):
            src = (GUIDE.parent / image.group(2)).resolve()
            out.append(f'<figure>{src.read_text(encoding="utf-8")}</figure>')
            i += 1
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                if not re.match(r"\|\s*-", lines[i]):
                    rows.append([cell.strip() for cell in lines[i].strip("|").split("|")])
                i += 1
            head, *body = rows
            out.append("<table><thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in head) + "</tr></thead><tbody>")
            out.extend("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>" for row in body)
            out.append("</tbody></table>")
        elif line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(f"<li>{_inline(lines[i][2:])}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
        elif line.startswith("> "):
            quote = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(lines[i].lstrip("> "))
                i += 1
            out.append(f"<blockquote>{_inline(' '.join(quote))}</blockquote>")
        else:
            paragraph = []
            while i < len(lines) and lines[i].strip() and not re.match(r"(#|!\[|\||- |> )", lines[i]):
                paragraph.append(lines[i])
                i += 1
            out.append(f"<p>{_inline(' '.join(paragraph))}</p>")
    return "\n".join(out)


PAGE_CSS = f"""
@page {{ size: A4; margin: 18mm 18mm 20mm; }}
body {{ font-family: {FONT}; color: #1f2a3c; font-size: 10.5pt; line-height: 1.5; }}
h1 {{ font-size: 26pt; color: {INK}; margin: 0 0 4pt; }}
h2 {{ font-size: 15pt; color: {INK}; margin: 20pt 0 6pt; break-after: avoid; }}
h3 {{ font-size: 12pt; color: {INK}; margin: 14pt 0 4pt; break-after: avoid; }}
p {{ margin: 0 0 7pt; }}
figure {{ margin: 6pt 0 8pt; break-inside: avoid; }}
figure svg {{ width: 100%; height: auto; }}
blockquote {{ margin: 6pt 0 8pt; padding: 6pt 10pt; border-left: 3px solid {BLUE}; background: {CARD}; color: {MUTED}; font-size: 9.5pt; }}
table {{ width: 100%; border-collapse: collapse; font-size: 9.5pt; break-inside: avoid; }}
th {{ text-align: left; background: #eaf1fb; border-bottom: 2px solid {BLUE}; padding: 6pt; }}
td {{ padding: 6pt; border-bottom: 1px solid {GRID}; vertical-align: top; }}
code {{ font-size: 9pt; background: #eef2f7; padding: 0 3px; border-radius: 3px; }}
a {{ color: {BLUE}; text-decoration: none; }}
"""

FOOTER = (
    '<div style="width:100%;font-size:8px;color:#5b6b82;padding:0 18mm;display:flex;justify-content:space-between;'
    f'font-family:{FONT}"><span>OPS SIGNALS &nbsp;|&nbsp; Analyzer guide</span><span class="pageNumber"></span></div>'
)

PRINT_SCRIPT = """
const { chromium } = require('playwright');
(async () => {
  const [html, pdf, footer] = process.argv.slice(1);
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto('file://' + html);
  await page.pdf({ path: pdf, format: 'A4', printBackground: true, preferCSSPageSize: true,
    displayHeaderFooter: true, headerTemplate: '<span></span>', footerTemplate: footer });
  await browser.close();
})();
"""


def write_pdf(target: Path) -> None:
    body = markdown_to_html(GUIDE.read_text(encoding="utf-8"))
    page = f'<!doctype html><html><head><meta charset="utf-8"><style>{PAGE_CSS}</style></head><body>{body}</body></html>'
    with tempfile.TemporaryDirectory() as workdir:
        html_path = Path(workdir) / "guide.html"
        html_path.write_text(page, encoding="utf-8")
        subprocess.run(
            ["node", "-e", PRINT_SCRIPT, str(html_path), str(target.resolve()), FOOTER],
            cwd=REPO / "frontend",
            check=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pdf", type=Path, help="also print the guide to this PDF file")
    args = parser.parse_args()
    write_charts()
    print(f"Wrote {len(CHARTS)} charts to {CHART_DIR.relative_to(REPO)}")
    if args.pdf:
        write_pdf(args.pdf)
        print(f"Wrote {args.pdf}")


if __name__ == "__main__":
    main()
