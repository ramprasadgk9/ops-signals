import { describe, expect, it } from 'vitest';
import type { Finding } from '../types';
import { problemTiming } from './findingProblem';

const base = { metric_name: 'memory.usage', title: '', summary: '', category: 'behavior_change', health_status: 'significant', importance_score: 0.6, investigation_priority: 2, signal_ids: [], comparison_json: {} } as Finding;

describe('problemTiming', () => {
  const now = Date.parse('2026-10-12T10:30:00Z');

  it('says a problem still going on started when, and an ended one ran from when to when', () => {
    const still = problemTiming({ ...base, event_start: '2026-10-12T09:00:00Z', event_end: '2026-10-12T10:00:00Z', ongoing: true }, undefined, now);
    const over = problemTiming({ ...base, event_start: '2026-10-12T09:00:00Z', event_end: '2026-10-12T09:45:00Z', ongoing: false }, undefined, now);

    expect(still?.ongoing).toBe(true);
    expect(still?.label).toMatch(/^Started .* · still happening$/);
    expect(over?.ongoing).toBe(false);
    expect(over?.label).toMatch(/^.*–.* · over$/);
  });

  it('calls a level change that came back over, until the time it came back', () => {
    const trust = { ended_at: '2026-10-12T10:12:00Z' } as Finding['trust'];
    const back = problemTiming({ ...base, event_start: '2026-10-12T09:00:00Z', event_end: '2026-10-12T10:25:00Z', ongoing: true, trust }, undefined, now);

    expect(back?.ongoing).toBe(false);
    const sameLabel = problemTiming({ ...base, event_start: '2026-10-12T09:00:00Z', event_end: '2026-10-12T10:12:00Z', ongoing: false }, undefined, now);
    expect(back?.label).toBe(sameLabel?.label);
  });

  it('does not call a problem in old data still happening, and says when the data ended', () => {
    const oldCsv = { ...base, event_start: '2026-09-20T09:00:00Z', event_end: '2026-09-20T12:00:00Z', ongoing: true };
    const timing = problemTiming(oldCsv, undefined, now);

    expect(timing?.ongoing).toBe(false);
    expect(timing?.label).not.toMatch(/still happening/);
    expect(timing?.label).toMatch(/^Started .* · still going when the data ended \(.*\)$/);
  });

  it('still happening holds up to 2 hours after the data ended, not after', () => {
    const finding = { ...base, event_start: '2026-10-12T07:00:00Z', event_end: '2026-10-12T08:30:00Z', ongoing: true };

    expect(problemTiming(finding, undefined, now)?.ongoing).toBe(true);
    expect(problemTiming(finding, undefined, now + 1)?.ongoing).toBe(false);
  });

  it('starts from the earliest start any run saw', () => {
    const latest = { ...base, event_start: '2026-10-12T09:30:00Z', event_end: '2026-10-12T10:00:00Z', ongoing: true };

    expect(problemTiming(latest, '2026-10-12T09:00:00Z', now)?.label).toBe(problemTiming({ ...latest, event_start: '2026-10-12T09:00:00Z' }, undefined, now)?.label);
  });

  it('has nothing to say about an older finding without event times', () => {
    expect(problemTiming(base)).toBeNull();
  });
});
