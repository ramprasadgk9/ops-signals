import { describe, expect, it } from 'vitest';
import type { Finding } from '../types';
import { chartPoints, durationWords, findingChart, formatReading } from './findingChartMarks';

const iso = (h: number, m = 0) => new Date(Date.UTC(2026, 10, 9, h, m)).toISOString();
const readings = (fromH: number, toH: number, everyMin = 10, skip: [number, number] | null = null) => {
  const out: Array<{ timestamp: string; value: number }> = [];
  for (let t = Date.UTC(2026, 10, 9, fromH); t <= Date.UTC(2026, 10, 9, toH); t += everyMin * 60_000) {
    const h = new Date(t).getUTCHours();
    if (skip && h >= skip[0] && h < skip[1]) continue;
    out.push({ timestamp: new Date(t).toISOString(), value: 0.006 });
  }
  return out;
};

function finding(plain: Partial<NonNullable<Finding['plain']>>, extra: Partial<Finding> = {}): Finding {
  return {
    id: 1,
    metric_name: 'error_rate',
    plain: { kind: 'flatline', badge: 'gap', badge_label: 'Data problem', headline: '', what: '', ...plain },
    ...extra,
  } as Finding;
}

describe('findingChart', () => {
  it('shades the stuck stretch and says it was still going when the data ended', () => {
    const f = finding({ marks: { bands: [{ start: iso(4, 30), end: iso(12) }] } }, { ongoing: true, event_end: iso(12) });
    const chart = findingChart(f, readings(0, 12), Date.UTC(2026, 10, 20));
    expect(chart.bands).toHaveLength(1);
    expect(chart.bands[0]).toMatchObject({ x1: Date.parse(iso(4, 30)), x2: Date.parse(iso(12)), style: 'problem' });
    expect(chart.bands[0].label).toMatch(/^Started .* · still going when the data ended$/);
  });

  it('says still happening while the data is recent', () => {
    const f = finding({ marks: { bands: [{ start: iso(4, 30), end: iso(12) }] } }, { ongoing: true, event_end: iso(12) });
    const chart = findingChart(f, readings(0, 12), Date.UTC(2026, 10, 9, 12, 30));
    expect(chart.bands[0].label).toMatch(/still happening$/);
  });

  it('labels a finished stretch with its length', () => {
    const f = finding({ kind: 'spikes', marks: { bands: [{ start: iso(5), end: iso(5, 45) }] } }, { ongoing: false });
    expect(findingChart(f, readings(0, 12)).bands[0].label).toMatch(/· 45 min$/);
  });

  it('shades every burst but labels none when there are several', () => {
    const f = finding({ kind: 'spikes', marks: { bands: [{ start: iso(2), end: iso(2, 10) }, { start: iso(7), end: iso(7, 20) }] } });
    const chart = findingChart(f, readings(0, 12));
    expect(chart.bands.map((b) => b.label)).toEqual([null, null]);
  });

  it('draws missing data as a gap and widens the chart when the data stopped at the end', () => {
    const f = finding({ kind: 'data_gap', marks: { bands: [{ start: iso(12), end: iso(13) }], style: 'gap' } });
    const chart = findingChart(f, readings(0, 12));
    expect(chart.domain[1]).toBe(Date.parse(iso(13)));
    expect(chart.bands[0]).toMatchObject({ style: 'gap', label: 'No data · 60 min' });
  });

  it('marks where a level changed and where it came back', () => {
    const f = finding({ kind: 'level_change', marks: { lines: [{ at: iso(3), kind: 'change' }, { at: iso(9), kind: 'back' }] } });
    const chart = findingChart(f, readings(0, 12));
    expect(chart.lines.map((l) => l.label.split(' ')[0])).toEqual(['Changed', 'Back']);
    expect(chart.lines.map((l) => l.labelSide)).toEqual(['start', 'end']);
  });

  it('leaves out marks outside the readings', () => {
    const f = finding({ kind: 'level_change', marks: { lines: [{ at: iso(3), kind: 'change' }, { at: iso(20), kind: 'partly_back' }] } });
    expect(findingChart(f, readings(0, 12)).lines).toHaveLength(1);
  });

  it('explains why a trend has nothing marked', () => {
    const chart = findingChart(finding({ kind: 'trend', marks: null }), readings(0, 12));
    expect(chart.bands).toEqual([]);
    expect(chart.note).toMatch(/whole time shown/);
  });

  it('draws the plain line when marks are badly shaped, instead of breaking the drawer', () => {
    const bad = { bands: { start: iso(1), end: iso(2) }, lines: 'x' } as unknown as NonNullable<Finding['plain']>['marks'];
    const chart = findingChart(finding({ marks: bad }), readings(0, 12));
    expect(chart.bands).toEqual([]);
    expect(chart.lines).toEqual([]);
    const holes = { bands: [null, { start: 'soon' }], lines: [null] } as unknown as NonNullable<Finding['plain']>['marks'];
    expect(() => findingChart(finding({ marks: holes }), readings(0, 12))).not.toThrow();
  });

  it('draws the plain line for findings without marks (older findings)', () => {
    const chart = findingChart({ id: 2, metric_name: 'cpu' } as Finding, readings(0, 2));
    expect(chart.bands).toEqual([]);
    expect(chart.lines).toEqual([]);
    expect(chart.note).toBeNull();
  });
});

describe('chartPoints', () => {
  it('breaks the line only across the missing-data stretch the finding is about', () => {
    const gapped = readings(0, 6, 10, [2, 4]);
    expect(chartPoints(gapped).filter((p) => p.value === null)).toHaveLength(0);
    const gap = { start: Date.parse(iso(2)), end: Date.parse(iso(4)) };
    expect(chartPoints(gapped, [gap]).filter((p) => p.value === null)).toHaveLength(1);
  });
});

describe('formatReading', () => {
  it('keeps the decimals of small values', () => {
    expect(formatReading(0.006)).toBe('0.006');
    expect(formatReading(0)).toBe('0');
  });
});

describe('durationWords', () => {
  it('reads in minutes, hours or days', () => {
    expect(durationWords(45 * 60_000)).toBe('45 min');
    expect(durationWords(17 * 3_600_000)).toBe('17 hours');
    expect(durationWords(72 * 3_600_000)).toBe('3 days');
  });
});
