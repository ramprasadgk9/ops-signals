import { describe, expect, it } from 'vitest';
import type { Finding } from '../types';
import { problemTiming } from './findingProblem';

const base = { metric_name: 'memory.usage', title: '', summary: '', category: 'behavior_change', health_status: 'significant', importance_score: 0.6, investigation_priority: 2, signal_ids: [], comparison_json: {} } as Finding;

describe('problemTiming', () => {
  it('says a problem still going on started when, and an ended one ran from when to when', () => {
    const still = problemTiming({ ...base, event_start: '2026-10-12T09:00:00Z', event_end: '2026-10-12T10:00:00Z', ongoing: true });
    const over = problemTiming({ ...base, event_start: '2026-10-12T09:00:00Z', event_end: '2026-10-12T09:45:00Z', ongoing: false });

    expect(still?.ongoing).toBe(true);
    expect(still?.label).toMatch(/^Started .* · still happening$/);
    expect(over?.ongoing).toBe(false);
    expect(over?.label).toMatch(/^.*–.* · over$/);
  });

  it('starts from the earliest start any run saw', () => {
    const latest = { ...base, event_start: '2026-10-12T09:30:00Z', event_end: '2026-10-12T10:00:00Z', ongoing: true };

    expect(problemTiming(latest, '2026-10-12T09:00:00Z')?.label).toBe(problemTiming({ ...latest, event_start: '2026-10-12T09:00:00Z' })?.label);
  });

  it('has nothing to say about an older finding without event times', () => {
    expect(problemTiming(base)).toBeNull();
  });
});
