import { describe, expect, it } from 'vitest';
import { buildBehaviorSummary, toBehaviorRows } from './behaviorService';
import type { BehaviorFinding } from '../types';

function behavior(overrides: Partial<BehaviorFinding> = {}): BehaviorFinding {
  return {
    id: 1,
    behavior_id: 'cpu-saturation',
    definition_id: 'cpu_saturation',
    definition_version: 1,
    title: 'CPU Saturation Pattern',
    summary: 'CPU and load are elevated.',
    category: 'saturation',
    severity: 'critical',
    service: 'checkout-api',
    input_metrics_json: { cpu: 'cpu_usage', load: 'load_average' },
    facts_json: {},
    evidence_json: ['cpu.high', 'load.high'],
    matched_conditions_json: [],
    confidence: 0.92,
    correlation_json: {},
    occurrence_count: 1,
    last_seen_at: '2026-07-26T00:00:00Z',
    created_at: '2026-07-26T00:00:00Z',
    ...overrides,
  };
}

describe('behavior service', () => {
  const now = Date.parse('2026-07-26T06:00:00Z');

  it('builds summary from returned behavior evaluations', () => {
    const quiet = behavior({ id: 3, last_seen_at: '2026-07-20T00:00:00Z', input_metrics_json: { cpu: 'cpu_usage', mem: 'memory_usage' } });
    expect(buildBehaviorSummary([behavior(), behavior({ id: 2, service: 'payments-api', confidence: 0.8 }), quiet], now)).toEqual({
      activeBehaviors: 2,
      metricsCombined: 3,
      affectedServices: 2,
      confidenceAverage: 88,
    });
  });

  it('says whether a behavior is still going on', () => {
    expect(toBehaviorRows([behavior()], now)[0].status).toBe('active');
    expect(toBehaviorRows([behavior({ last_seen_at: '2026-07-20T00:00:00Z' })], now)[0].status).toBe('quiet');
  });

  it('marks missing impacted service as unavailable', () => {
    expect(toBehaviorRows([behavior({ service: undefined })])[0].impactedServices).toBe('unavailable');
  });
});
