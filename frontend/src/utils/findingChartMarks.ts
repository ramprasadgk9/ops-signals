import type { Finding, FindingChartMarks } from '../types';
import { stillHappening } from './findingProblem';

// What the Finding details chart draws on a finding's readings. The backend sends `plain.marks`
// built from the same times the finding's sentence names (services/finding_plain.py), so the
// picture marks what the words say.

export type ChartPoint = { t: number; value: number | null };
export type ChartBand = { x1: number; x2: number; style: 'problem' | 'gap'; label: string | null; labelSide: 'start' | 'end' };
export type ChartLine = { x: number; label: string; labelSide: 'start' | 'end' };
export type FindingChart = {
  points: ChartPoint[];
  domain: [number, number];
  bands: ChartBand[];
  lines: ChartLine[];
  /** Why nothing is marked, for findings about the whole time shown. */
  note: string | null;
};

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;

function at(ms: number): string {
  return new Date(ms).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function time(ms: number): string {
  return new Date(ms).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

export function durationWords(ms: number): string {
  if (ms < 90 * MINUTE) return `${Math.max(1, Math.round(ms / MINUTE))} min`;
  if (ms < 48 * HOUR) return `${Math.round(ms / HOUR)} hours`;
  return `${Math.round(ms / (24 * HOUR))} days`;
}

/** The readings as chart points. The line breaks only across a missing-data stretch the finding
 * is about, so it isn't drawn straight through the "No data" band; elsewhere it joins up as before. */
export function chartPoints(readings: Array<{ timestamp: string; value: number }>, gaps: Array<{ start: number; end: number }> = []): ChartPoint[] {
  const sorted = readings.map((r) => ({ t: Date.parse(r.timestamp), value: r.value })).filter((p) => Number.isFinite(p.t)).sort((a, b) => a.t - b.t);
  const out: ChartPoint[] = [];
  sorted.forEach((p, i) => {
    const prev = sorted[i - 1];
    if (prev && gaps.some((g) => prev.t <= g.start && p.t >= g.end)) out.push({ t: (prev.t + p.t) / 2, value: null });
    out.push(p);
  });
  return out;
}

// Marks that aren't a list (a bad response) draw nothing rather than break the drawer.
function listOf<T>(value: T[] | null | undefined): T[] {
  return Array.isArray(value) ? value : [];
}

const LINE_WORDS: Record<string, string> = { change: 'Changed', back: 'Back', partly_back: 'Partly back' };

export function findingChart(finding: Finding, readings: Array<{ timestamp: string; value: number }>, now: number = Date.now()): FindingChart {
  const marks: FindingChartMarks = finding.plain?.marks ?? {};
  const style = marks.style === 'gap' ? 'gap' : 'problem';
  const parsedBands = listOf(marks.bands)
    .map((b) => ({ start: Date.parse(b?.start), end: Date.parse(b?.end) }))
    .filter((b) => Number.isFinite(b.start) && Number.isFinite(b.end) && b.end >= b.start);
  const points = chartPoints(readings, style === 'gap' ? parsedBands : []);
  const first = points[0]?.t ?? 0;
  const last = points[points.length - 1]?.t ?? 0;

  // Missing data at the very end has no readings after it: widen the chart to show the gap.
  let [lo, hi] = [first, last];
  if (style === 'gap') parsedBands.forEach((b) => { lo = Math.min(lo, b.start); hi = Math.max(hi, b.end); });
  const span = hi - lo || 1;
  const side = (x: number): 'start' | 'end' => (x - lo > span * 0.55 ? 'end' : 'start');

  // Marks outside the readings (an older run's time in a later sentence) aren't drawn.
  const visible = parsedBands
    .filter((b) => b.end >= lo && b.start <= hi)
    .map((b) => ({ x1: Math.max(b.start, lo), x2: Math.min(b.end, hi), start: b.start, end: b.end }));

  const ongoing = Boolean(finding.ongoing) && !finding.trust?.ended_at;
  const bands: ChartBand[] = visible.map((b, i) => {
    let label: string | null = null;
    if (visible.length === 1) {
      if (style === 'gap') label = `No data · ${durationWords(b.end - b.start)}`;
      else if (ongoing && i === visible.length - 1 && hi - b.end <= span * 0.02) {
        const stillNow = stillHappening(finding.event_end ?? new Date(b.end).toISOString(), now);
        label = `Started ${at(b.start)} · ${stillNow ? 'still happening' : 'still going when the data ended'}`;
      } else {
        const sameDay = new Date(b.start).toDateString() === new Date(b.end).toDateString();
        label = `${at(b.start)}–${sameDay ? time(b.end) : at(b.end)} · ${durationWords(b.end - b.start)}`;
      }
    }
    return { x1: b.x1, x2: b.x2, style, label, labelSide: side(b.x1) };
  });

  const lines: ChartLine[] = listOf(marks.lines)
    .map((l) => ({ x: Date.parse(l?.at), kind: l?.kind }))
    .filter((l) => Number.isFinite(l.x) && l.x >= lo && l.x <= hi)
    .map((l) => ({ x: l.x, label: `${LINE_WORDS[l.kind] ?? 'Changed'} ${at(l.x)}`, labelSide: side(l.x) }));

  const note = finding.plain?.kind === 'trend' && bands.length === 0 && lines.length === 0
    ? 'This finding is about the whole time shown, not one moment, so nothing is marked.'
    : null;

  return { points, domain: [lo, hi], bands, lines, note };
}

/** Axis and tooltip numbers: small values keep their decimals (a stuck 0.006 isn't shown as 0). */
export function formatReading(value: number): string {
  if (!Number.isFinite(value)) return '';
  return new Intl.NumberFormat(undefined, { maximumSignificantDigits: 3, notation: Math.abs(value) >= 10_000 ? 'compact' : 'standard' }).format(value);
}
