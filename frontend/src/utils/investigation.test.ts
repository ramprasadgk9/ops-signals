import { describe, expect, it } from 'vitest';
import type { Finding } from '../types';
import { canInvestigate, endingBanner, stepChecks, stepTag, type Investigation, type InvestigationStep } from './investigation';

const finding = (overrides: Partial<Finding> = {}): Finding =>
  ({
    id: 4,
    service: 'checkout',
    metric_name: 'http_request_duration_seconds',
    title: 'Latency jumped',
    summary: '',
    category: 'behavior_change',
    health_status: 'critical',
    importance_score: 0.9,
    investigation_priority: 1,
    signal_ids: [],
    comparison_json: {},
    connection_id: 'default',
    source: 'prometheus',
    ...overrides,
  }) as Finding;

const step = (overrides: Partial<InvestigationStep> = {}): InvestigationStep => ({
  id: 1,
  round: 1,
  position: 1,
  kind: 'checked',
  status: 'worth_a_look',
  title: 'Waiting for checkout-db',
  why: null,
  result: null,
  evidence: ['c2'],
  unverified: false,
  mark: null,
  note: null,
  marked_by: null,
  ...overrides,
});

describe('canInvestigate', () => {
  it('needs a Prometheus finding with a service that needs attention', () => {
    expect(canInvestigate(finding())).toBe(true);
    expect(canInvestigate(finding({ source: 'csv' }))).toBe(false);
    expect(canInvestigate(finding({ connection_id: null }))).toBe(false);
    expect(canInvestigate(finding({ service: 'unknown' }))).toBe(false);
    expect(canInvestigate(finding({ trust: { tier: 'context' } as Finding['trust'] }))).toBe(false);
  });
});

describe('endingBanner', () => {
  it('says how the round ended in plain words', () => {
    const base = { ending_detail: null, question: null } as Investigation;
    expect(endingBanner({ ...base, ending: 'found' }).title).toBe('Found where to look');
    expect(endingBanner({ ...base, ending: 'waiting', question: 'Who changed the pool size?' }).detail).toBe('Who changed the pool size?');
    expect(endingBanner({ ...base, ending: 'budget', ending_detail: '15 of 15 checks used.' })).toEqual({ severity: 'warning', title: 'Paused', detail: '15 of 15 checks used.' });
    expect(endingBanner({ ...base, ending: 'source_down' }).title).toBe("Couldn't reach Prometheus");
  });
});

describe('stepTag', () => {
  it('puts what a person marked before what the model said', () => {
    expect(stepTag(step()).label).toBe('Worth a look');
    expect(stepTag(step({ mark: 'found' })).label).toBe('You found something');
    expect(stepTag(step({ kind: 'your_step', status: 'todo' })).label).toBe('Your step');
    expect(stepTag(step({ status: 'ruled_out' })).label).toBe('Ruled out');
  });
});

describe('stepChecks', () => {
  it('finds the checks a step cites and skips past cases', () => {
    const checks = [{ ref: 'c2', round: 1, tool: 'query_range', purpose: null, query: 'db_wait', ok: true, result: 'rose', at: null }];
    expect(stepChecks(step({ evidence: ['c2', 'case #204'] }), checks)).toEqual(checks);
  });
});
