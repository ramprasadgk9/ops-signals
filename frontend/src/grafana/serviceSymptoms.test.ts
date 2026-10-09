import { describe, expect, it } from 'vitest';
import type { Finding } from '../types';
import { caseForSymptom, caseIdsByFinding, serviceSymptoms, stillShowing, symptomChange, symptomKind, symptomOf, symptomRole, triageOrder, triageSymptoms } from './serviceSymptoms';

function finding(overrides: Partial<Finding>): Finding {
  return {
    id: 1,
    service: 'trend-lab',
    metric_name: 'error_rate',
    title: 'error_rate experienced a persistent baseline shift',
    summary: '',
    category: 'behavior_change',
    health_status: 'warning',
    importance_score: 0.5,
    investigation_priority: 1,
    signal_ids: [],
    comparison_json: {},
    ...overrides,
  };
}

describe('serviceSymptoms', () => {
  const findings = [
    finding({ id: 1, importance_score: 0.6, created_at: '2026-10-09T01:00:00Z' }),
    finding({ id: 2, importance_score: 0.88, created_at: '2026-10-09T02:00:00Z' }),
    finding({ id: 3, metric_name: 'cpu_usage', title: 'cpu_usage is trending in one direction.', category: 'trend', importance_score: 0.7 }),
    finding({ id: 4, service: 'checkout', importance_score: 0.99 }),
    finding({ id: 5, service: undefined, metric_name: 'up', title: 'up stopped reporting', importance_score: 0.4 }),
  ];

  it('folds repeats of the same symptom into one, worst first, for one service', () => {
    const symptoms = serviceSymptoms(findings, 'trend-lab');

    expect(symptoms.map((symptom) => symptom.finding.id)).toEqual([2, 3]);
    expect(symptoms[0].runs.map((run) => run.id)).toEqual([2, 1]);
    expect(symptoms[0].firstSeen).toBe('2026-10-09T01:00:00Z');
  });

  it('groups findings without a service under "unknown"', () => {
    expect(serviceSymptoms(findings, 'unknown').map((symptom) => symptom.finding.id)).toEqual([5]);
  });

  it("finds a symptom's case through any of its runs, and the symptom a finding belongs to", () => {
    const symptoms = serviceSymptoms(findings, 'trend-lab');
    const byFinding = caseIdsByFinding([{ id: 37, finding_id: 1 }, { id: 12, finding_id: 99 }]);

    expect(caseForSymptom(symptoms[0], byFinding)).toBe(37);
    expect(caseForSymptom(symptoms[1], byFinding)).toBeNull();
    expect(symptomOf(symptoms, findings[0])).toBe(symptoms[0]);
    expect(symptomOf(symptoms, findings[3])).toBeNull();
    expect(symptomOf(symptoms, null)).toBeNull();
  });
});

describe('triageSymptoms', () => {
  const trust = (group: NonNullable<Finding['trust']>['group'], tier: 'needs_attention' | 'context', badge: NonNullable<Finding['trust']>['badge']) =>
    ({ group, tier, badge, moved: null, checks: [], tested: null, service: { real: 0, answered: 0, min_answers: 5 }, your_answer: null });
  const shift = finding({ id: 1, importance_score: 0.9, trust: trust('level_change_agree', 'needs_attention', 'strong'), comparison_json: { previous_mean: 0.006, current_mean: 0.0463, change_percent: 671.06 } });
  const gap = finding({ id: 2, title: 'error_rate stopped reporting', category: 'data_quality', importance_score: 0.85, trust: trust('data_problem', 'needs_attention', 'data_problem') });
  const weak = finding({ id: 3, title: 'error_rate has unusual activity', importance_score: 0.84, trust: trust('pattern', 'context', null) });
  const spike = finding({ id: 4, metric_name: 'queue_depth', title: 'queue_depth spiked', importance_score: 0.5, trust: trust('spike', 'context', null), comparison_json: { current_max: 180 } });
  const oldBackend = finding({ id: 5, metric_name: 'up', title: 'up stopped reporting', category: 'data_quality', importance_score: 0.4 });

  it('puts data problems and weak signals aside and gives each needing-attention metric one row', () => {
    const triage = triageSymptoms(serviceSymptoms([shift, gap, weak, spike, oldBackend], 'trend-lab'));

    expect(triage.attention.map((row) => row.lead.finding.id)).toEqual([1]);
    expect(triage.attention[0].others.map((other) => other.finding.id)).toEqual([3]);
    expect(triage.data.map((symptom) => symptom.finding.id)).toEqual([2, 5]);
    expect(triage.background.map((symptom) => symptom.finding.id)).toEqual([3, 4]);
    expect(triageOrder(triage).map((symptom) => symptom.finding.id)).toEqual([1, 2, 5, 3, 4]);
  });

  it('says what changed in the metric\'s own values', () => {
    expect(symptomChange(shift)).toEqual({ text: 'stepped up 0.006 → 0.046', percent: '+671%' });
    expect(symptomChange(spike)).toEqual({ text: 'spiked to 180', percent: null });
    expect(symptomChange(gap)).toBeNull();
    expect(symptomChange(finding({ comparison_json: { previous_mean: 412.5, current_mean: 388.2, change_percent: -5.9 } }))).toEqual({ text: 'fell 413 → 388', percent: '-6%' });
    expect(symptomKind(weak)).toBe('unusual activity');
    expect(symptomRole(oldBackend)).toBe('data');
  });

  it('counts a symptom as still showing when it was seen within 90 minutes of the newest finding', () => {
    const [recent, earlier] = serviceSymptoms([
      finding({ id: 10, created_at: '2026-10-09T05:00:00Z' }),
      finding({ id: 11, metric_name: 'cpu_usage', title: 'cpu', created_at: '2026-10-09T02:00:00Z', importance_score: 0.1 }),
    ], 'trend-lab');
    const latest = triageSymptoms([recent, earlier]).latestSeen;

    expect(latest).toBe('2026-10-09T05:00:00Z');
    expect(stillShowing(recent, latest)).toBe(true);
    expect(stillShowing(earlier, latest)).toBe(false);
  });
});
