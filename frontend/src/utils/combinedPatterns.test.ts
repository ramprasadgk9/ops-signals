import { describe, expect, it } from 'vitest';
import type { BehaviorFinding, Finding } from '../types';
import { conditionsPassed, findingsWindowFor, formatChange, inWindow, overlapMinutes, parseUtc, partFindings, patternFindingsHref, patternParts, patternsByFinding, patternStatus, searchPatterns } from './combinedPatterns';

// Shaped like the real record the engine stores for the shipped pool_exhaustion rule.
const trend = (direction: string, change: number, start: string) => ({
  anomaly: { present: false },
  trend: { present: true, direction, change_percent: change },
  baseline_shift: { present: false, signed_change_percent: 0 },
  ruptures: { present: false, signed_change_percent: 0 },
  signal: { window_start: start, window_end: '2026-10-21T14:40:00' },
});

const pool: BehaviorFinding = {
  id: 7,
  behavior_id: 'pool_exhaustion:1:run-1',
  definition_id: 'pool_exhaustion',
  definition_version: 1,
  title: 'Database connection pool exhaustion',
  summary: 'Database connection pool reached saturation with surging connection wait times.',
  category: 'resource_constraint',
  severity: 'critical',
  service: 'checkout-api',
  analysis_run_id: 'run-1',
  input_metrics_json: { db_wait: 'db_connection_wait_seconds', db_pool: 'db_connections_active' },
  facts_json: { db_wait: trend('upward', 85, '2026-10-21T14:00:00'), db_pool: trend('upward', 40, '2026-10-21T14:05:00') },
  evidence_json: ['db_wait.trend.direction', 'db_pool.trend.direction'],
  matched_conditions_json: [
    { group: 'all', fact: 'db_wait.trend.direction', passed: true },
    { group: 'any', fact: 'db_pool.trend.direction', passed: true },
  ],
  confidence: 1,
  correlation_json: { matched: true, overlap_minutes: 35.0, closest_gap_minutes: 0 },
  case_id: null,
  occurrence_count: 1,
  last_seen_at: '2026-10-21T14:40:00+00:00',
  created_at: '2026-10-21T14:40:00+00:00',
};

const finding = (id: number, metric: string, extra: Partial<Finding> = {}) =>
  ({ id, metric_name: metric, service: 'checkout-api', analysis_run_id: 'run-1', ...extra }) as Finding;

describe('patternParts', () => {
  it('lists each metric with its shape and change, in rule order', () => {
    expect(patternParts(pool)).toEqual([
      { alias: 'db_wait', metric: 'db_connection_wait_seconds', shape: 'Slowly rising', change: 85, start: '2026-10-21T14:00:00', end: '2026-10-21T14:40:00' },
      { alias: 'db_pool', metric: 'db_connections_active', shape: 'Slowly rising', change: 40, start: '2026-10-21T14:05:00', end: '2026-10-21T14:40:00' },
    ]);
  });

  it('prefers a level jump over a trend, and keeps its sign', () => {
    const facts = { ...trend('upward', 10, 'x'), ruptures: { present: true, signed_change_percent: -32.4 } };
    const behavior = { ...pool, input_metrics_json: { m: 'memory_usage' }, facts_json: { m: facts } };
    expect(patternParts(behavior)[0]).toMatchObject({ shape: 'Jumps to a new level', change: -32.4 });
  });

  it('names a falling trend and an anomaly-only metric', () => {
    const behavior = {
      ...pool,
      input_metrics_json: { a: 'free_bytes', b: 'error_rate' },
      facts_json: { a: trend('downward', 20, 'x'), b: { anomaly: { present: true }, trend: { present: false } } },
    };
    expect(patternParts(behavior).map((part) => [part.shape, part.change])).toEqual([['Slowly falling', -20], ['Unusual spike', null]]);
  });
});

describe('why it matched', () => {
  it('counts passed conditions and reads the overlap', () => {
    expect(conditionsPassed(pool)).toEqual({ passed: 2, total: 2 });
    expect(overlapMinutes(pool)).toBe(35);
    expect(overlapMinutes({ ...pool, correlation_json: { matched: false, overlap_minutes: 35 } })).toBeNull();
  });

  it('formats changes with a sign', () => {
    expect(formatChange(85.4)).toBe('+85%');
    expect(formatChange(-20)).toBe('-20%');
    expect(formatChange(null)).toBeNull();
  });
});

describe('window and search', () => {
  const now = parseUtc('2026-10-21T20:00:00Z');

  it('reads a zone-less timestamp as UTC', () => {
    expect(parseUtc('2026-10-21 14:40:00')).toBe(parseUtc('2026-10-21T14:40:00Z'));
  });

  it('keeps patterns last seen inside the window', () => {
    expect(inWindow(pool, '6h', now)).toBe(true);
    expect(inWindow(pool, '6h', parseUtc('2026-10-22T02:00:00Z'))).toBe(false);
    expect(inWindow(pool, '24h', parseUtc('2026-10-22T02:00:00Z'))).toBe(true);
  });

  it('matches title, service, rule id and the metrics used', () => {
    expect(searchPatterns([pool], 'checkout wait')).toHaveLength(1);
    expect(searchPatterns([pool], 'pool_exhaustion')).toHaveLength(1);
    expect(searchPatterns([pool], 'db_connections_active')).toHaveLength(1);
    expect(searchPatterns([pool], 'payments')).toHaveLength(0);
  });
});

describe('patternsByFinding', () => {
  it('links the findings from the same run, service and metrics', () => {
    const findings = [
      finding(1, 'db_connection_wait_seconds'),
      finding(2, 'db_connections_active'),
      finding(3, 'cpu_usage'),
      finding(4, 'db_connections_active', { analysis_run_id: 'run-0' }),
      finding(5, 'db_connections_active', { service: 'payments' }),
    ];
    const byFinding = patternsByFinding([pool], findings);
    expect([...byFinding.keys()]).toEqual([1, 2]);
    expect(partFindings(pool, byFinding, findings).map((item) => item.id)).toEqual([1, 2]);
  });

  it('links nothing when the pattern has no run', () => {
    expect(patternsByFinding([{ ...pool, analysis_run_id: undefined }], [finding(1, 'db_connection_wait_seconds')]).size).toBe(0);
  });
});

describe('status and link', () => {
  const seen = parseUtc(pool.last_seen_at);
  const hours = (count: number) => seen + count * 3600_000;

  it('is active while a run saw it in the last 24 hours, quiet after', () => {
    expect(patternStatus(pool, hours(2))).toBe('active');
    expect(patternStatus(pool, hours(30))).toBe('quiet');
  });

  it('links to the smallest Findings window that lists it', () => {
    expect(findingsWindowFor(pool, hours(2))).toBe('6h');
    expect(findingsWindowFor(pool, hours(10))).toBe('24h');
    expect(patternFindingsHref(pool, hours(30))).toBe('/findings?window=7d&pattern=7');
    expect(patternFindingsHref(pool, hours(24 * 8))).toBeNull();
  });
});
