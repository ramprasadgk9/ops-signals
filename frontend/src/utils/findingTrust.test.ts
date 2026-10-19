import { describe, expect, it } from 'vitest';
import type { Finding, FindingTrust } from '../types';
import { answerLine, movedNote, needsAttention, serviceCaption, serviceHeadline, serviceRateLeads, testedCaption, testedHeadline, testedTooltip, trustBadge } from './findingTrust';

const base: FindingTrust = {
  group: 'level_change_agree', tier: 'needs_attention', badge: 'strong', checks: ['change', 'pyod_outlier'],
  tested: { real: 0.91, checked: 266, random: 0.603, dataset: 'RCAEval RE1', data_kind: 'microservice', fits_metric: true, measured_at: '2026-10-08' },
  service: { real: 0, answered: 0, min_answers: 5 }, your_answer: null,
};

describe('findingTrust wording', () => {
  it('leads with the tested rate and says where it came from', () => {
    expect(testedHeadline(base)).toBe('91% were real');
    expect(testedCaption(base)).toBe('266 checked in tests');
    expect(testedTooltip(base)).toContain('microservice data');
    expect(testedTooltip(base)).toContain('right 60% of the time');
  });

  it('warns when the metric is unlike the tested ones', () => {
    const other = { ...base, tested: { ...base.tested!, fits_metric: false } };
    expect(testedCaption(other)).toBe('266 checked in tests · tested on microservice CPU, memory and latency, not metrics like this one');
  });

  it('calls a data problem a fact, not a rate', () => {
    const data: FindingTrust = { ...base, group: 'data_problem', badge: 'data_problem', tested: null };
    expect(testedHeadline(data)).toBe('This is a fact');
    expect(trustBadge(data)?.label).toBe('Data problem');
  });

  it('shows the service count, and says when it is too few to lead', () => {
    expect(serviceHeadline(base)).toBe('Not yet');
    expect(serviceCaption(base, 'cart')).toContain('on 5 findings like this on cart');
    const few = { ...base, service: { real: 2, answered: 3, min_answers: 5 } };
    expect(serviceHeadline(few)).toBe('2 of 3 were real');
    expect(serviceCaption(few)).toContain('Too few yet');
    expect(serviceRateLeads(few)).toBe(false);
    expect(serviceRateLeads({ ...base, service: { real: 5, answered: 6, min_answers: 5 } })).toBe(true);
  });

  it('keeps findings without trust in the main list', () => {
    const finding = { metric_name: 'm', title: 't', summary: 's', category: 'c', health_status: 'normal', importance_score: 0, investigation_priority: 3, signal_ids: [], comparison_json: {} } as Finding;
    expect(needsAttention(finding)).toBe(true);
    expect(needsAttention({ ...finding, trust: { ...base, tier: 'context', badge: null } })).toBe(false);
    expect(trustBadge({ ...base, tier: 'context', badge: null })?.label).toBe('Context only');
  });

  it('says when the team moved a kind of finding to the other list', () => {
    const up: FindingTrust = { ...base, group: 'spike', badge: 'team_confirmed', moved: 'up', service: { real: 4, answered: 6, min_answers: 5 } };
    expect(trustBadge(up)?.label).toBe('Confirmed by your team');
    expect(movedNote(up, 'cart')).toBe('Moved to Needs attention: your team said 4 of 6 findings like this on cart were real.');
    const down: FindingTrust = { ...base, tier: 'context', badge: null, moved: 'down', service: { real: 0, answered: 5, min_answers: 5 } };
    expect(trustBadge(down)?.label).toBe('Usually not a problem here');
    expect(movedNote(down, 'cart')).toContain('only 0 of 5');
    expect(movedNote(base)).toBeNull();
  });
});

describe('answerLine', () => {
  const now = Date.parse('2026-10-19T12:00:00Z');
  const base = { your_answer: 'expected_change', answered_by: 'priya', answered_at: '2026-10-19T11:50:00Z' } as never;

  it('says who answered and when', () => {
    expect(answerLine(base, now)).toBe('Answered Expected change by priya · 10m ago');
    expect(answerLine({ ...(base as object), answered_by: null } as never, now)).toBe('Answered Expected change · 10m ago');
  });

  it('adds nothing without an answer, or when an older backend sends no who or when', () => {
    expect(answerLine({ ...(base as object), your_answer: null } as never, now)).toBeNull();
    expect(answerLine({ your_answer: 'real_problem' } as never, now)).toBeNull();
    expect(answerLine(null, now)).toBeNull();
  });
});
