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
    input_metrics_json: {},
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
  it('builds summary from returned behavior evaluations', () => {
    expect(buildBehaviorSummary([behavior(), behavior({ id: 2, service: 'payments-api', confidence: 0.8 })])).toEqual({
      activeBehaviors: 2,
      totalSignals: 4,
      affectedServices: 2,
      confidenceAverage: 86,
    });
  });

  it('marks missing impacted service as unavailable', () => {
    expect(toBehaviorRows([behavior({ service: undefined })])[0].impactedServices).toBe('unavailable');
  });
});
