import { describe, expect, it } from 'vitest';
import type { Finding } from '../types';
import { caseForSymptom, caseIdsByFinding, serviceSymptoms, symptomOf } from './serviceSymptoms';

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
