import { describe, expect, it } from 'vitest';
import type { Signal } from '../types';
import { supportingSignals } from './signalGroups';

function signal(id: string, extra: Partial<Signal> = {}): Signal {
  return {
    id,
    signal_type: 'ruptures',
    analyzer_id: 'ruptures',
    metric_name: 'http_errors_total',
    severity: 'high',
    importance_score: 0.8,
    evidence: {},
    ...extra,
  } as Signal;
}

describe('supportingSignals', () => {
  it('keeps the finding order and skips ids with no loaded signal', () => {
    const signals = [signal('b'), signal('a')];
    expect(supportingSignals(['a', 'missing', 'b'], signals).map((s) => s.id)).toEqual(['a', 'b']);
  });

  it('skips a signal whose finding rule did not match', () => {
    const signals = [signal('hit', { evidence: { finding_rule_matched: true } }), signal('diag', { severity: 'medium', evidence: { finding_rule_matched: false } })];
    expect(supportingSignals(['hit', 'diag'], signals).map((s) => s.id)).toEqual(['hit']);
  });

  it('skips low severity, and without severity uses the importance score', () => {
    const signals = [
      signal('low', { severity: 'low' }),
      signal('weak', { severity: undefined, importance_score: 0.4 }),
      signal('strong', { severity: undefined, importance_score: 0.7 }),
    ];
    expect(supportingSignals(['low', 'weak', 'strong'], signals).map((s) => s.id)).toEqual(['strong']);
  });
});
