import { describe, expect, it } from 'vitest';
import type { RecordingRule } from '../types';
import { missingLabelSelector, recordingRulesByName, ruleForRun, ruleNoteLead, ruleSchedule, selectorMetricName } from './recordingRules';

const rule = (overrides: Partial<RecordingRule> = {}): RecordingRule => ({
  name: 'service:error_rate:percent',
  query: '100 * avg by (service, env) (error_rate)',
  group: 'lab-rules',
  interval_seconds: 15,
  health: 'ok',
  source_metrics: ['error_rate'],
  ...overrides,
});

describe('recording rules', () => {
  it('says how often the rule runs', () => {
    expect(ruleSchedule(rule())).toBe('every 15s');
    expect(ruleSchedule(rule({ interval_seconds: 60 }))).toBe('every 1m');
    expect(ruleSchedule(rule({ interval_seconds: 90 }))).toBe('every 1m30s');
    expect(ruleSchedule(rule({ interval_seconds: null }))).toBe('on a schedule');
  });

  it('words the note for a working, a not-run-yet and a failed rule', () => {
    expect(ruleNoteLead(rule())).toBe('Recording rule in group lab-rules. Prometheus runs this query every 15s and saves the result under this name:');
    expect(ruleNoteLead(rule({ health: 'unknown' }))).toMatch(/hasn't run it yet/);
    expect(ruleNoteLead(rule({ health: 'err' }))).toMatch(/last run failed/);
  });

  it('keeps the first rule of a name saved by two groups', () => {
    const byName = recordingRulesByName([rule(), rule({ group: 'other' })]);
    expect(byName.get('service:error_rate:percent')?.group).toBe('lab-rules');
    expect(recordingRulesByName(undefined).size).toBe(0);
  });

  it('finds the rule behind a run by metric name or plain selector', () => {
    const byName = recordingRulesByName([rule()]);
    expect(ruleForRun(byName, 'service:error_rate:percent', null)?.name).toBe('service:error_rate:percent');
    expect(ruleForRun(byName, 'something_else', 'service:error_rate:percent{service="spike-lab"}')?.name).toBe('service:error_rate:percent');
    expect(ruleForRun(byName, 'cpu_usage', 'avg(cpu_usage)')).toBeNull();
    expect(selectorMetricName('rate(x[5m])')).toBeNull();
  });

  it('builds one selector for rules without the service label', () => {
    expect(missingLabelSelector(['a:b:c', 'all_services_error_rate_percent'], 'service')).toBe('{__name__=~"a:b:c|all_services_error_rate_percent",service=""}');
    expect(missingLabelSelector(['bad"name'], 'service')).toBeNull();
    expect(missingLabelSelector(['ok'], 'bad-label')).toBeNull();
    expect(missingLabelSelector([], 'service')).toBeNull();
  });
});
