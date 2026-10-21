import { describe, expect, it } from 'vitest';
import { analyzersFor, describeCondition, parsePlain, toCondition, type PlainCondition } from './plainConditions';

describe('plain conditions', () => {
  it.each<PlainCondition>([
    { alias: 'lag', kind: 'rising' },
    { alias: 'lag', kind: 'falling' },
    { alias: 'cpu', kind: 'unusual' },
    { alias: 'lag', kind: 'rose_more', percent: 40 },
    { alias: 'hits', kind: 'fell_more', percent: 30 },
  ])('reads back what it writes: $alias $kind', (plain) => {
    expect(parsePlain(toCondition(plain))).toEqual(plain);
  });

  it('writes the facts the engine reads', () => {
    expect(toCondition({ alias: 'lag', kind: 'rising' })).toEqual({ fact: 'lag.change.upward', operator: 'equals', value: true });
    expect(toCondition({ alias: 'hits', kind: 'fell_more', percent: 30 })).toEqual({ fact: 'hits.change.signed_change_percent', operator: 'less_than', value: -30 });
  });

  it('reads a value typed by hand as text', () => {
    expect(parsePlain({ fact: 'cpu.anomaly.present', operator: 'equals', value: 'true' })).toEqual({ alias: 'cpu', kind: 'unusual' });
  });

  it('leaves anything else to be written by hand', () => {
    expect(parsePlain({ fact: 'cpu.anomaly.max_score', operator: 'greater_than', value: 0.8 })).toBeNull();
    expect(parsePlain({ fact: 'lag.change.upward', operator: 'equals', value: false })).toBeNull();
    expect(parsePlain({ fact: '', operator: 'equals', value: true })).toBeNull();
  });

  it('says it in plain words, or as written', () => {
    expect(describeCondition({ fact: 'lag.change.upward', operator: 'equals', value: true })).toBe('lag is rising');
    expect(describeCondition({ fact: 'lag.change.signed_change_percent', operator: 'greater_than', value: 40 })).toBe('lag went up by more than 40%');
    expect(describeCondition({ fact: 'cpu.anomaly.count', operator: 'greater_than', value: 2 })).toBe('cpu.anomaly.count greater_than 2');
  });

  it('names the analyzers each choice needs', () => {
    expect(analyzersFor('unusual')).toEqual(['anomaly_zscore', 'pyod_outlier']);
    expect(analyzersFor('rising')).toContain('ruptures');
  });
});
