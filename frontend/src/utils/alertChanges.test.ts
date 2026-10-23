import { describe, expect, it } from 'vitest';
import type { AlertItem } from '../types';
import { changeLabel, foundChangeHint, whatChanged } from './alertChanges';

function alert(overrides: Partial<AlertItem>): AlertItem {
  return {
    id: 1, source: 'alertmanager', alert_name: 'CheckoutLatencyHigh', status: 'firing', service: 'checkout', severity: 'warning',
    summary: '', starts_at: '2026-10-01T21:33:00Z', ends_at: null, received_at: '2026-10-01T21:33:00Z', labels: {},
    generator_url: null, analysis_status: 'analyzed', recommendation: null, notify_status: null, finding_id: 7, case_id: null,
    service_has_change_events: true, change_window_before_minutes: 30, changes: [], timing: null,
    ...overrides,
  };
}

const deploy = (version: string, minutesBefore: number) => ({
  id: 1, event_type: 'deploy', version, description: null, author: 'demo', url: null, timestamp: null, minutes_before_anchor: minutesBefore,
});

describe('whatChanged', () => {
  it('times deploys from a step change and says where the start time came from', () => {
    const result = whatChanged(alert({ timing: { basis: 'step_change', time: '2026-10-01T21:32:00Z', analyzer_id: 'ruptures', trend_direction: 'upward' }, changes: [deploy('v2.4.38', 1)] }));
    expect(result?.lines).toEqual(['Started 1 min after deploy v2.4.38 by demo']);
    expect(result?.note).toMatch(/^Start time .+, from a step change \(change-point detection\)\.$/);
  });

  it('times a spike and notes the trend it sits on', () => {
    const result = whatChanged(alert({ timing: { basis: 'spike', time: '2026-10-01T21:34:00Z', analyzer_id: 'stumpy', trend_direction: 'upward' }, changes: [deploy('v3.2.38', 1)] }));
    expect(result?.lines).toEqual(['Spike started 1 min after deploy v3.2.38 by demo']);
    expect(result?.note).toContain('It sits on a gradual upward trend, which these changes may not explain.');
  });

  it('never says "started after" for a slow trend', () => {
    const result = whatChanged(alert({ timing: { basis: 'trend', time: null, analyzer_id: null, trend_direction: 'upward' }, changes: [deploy('v5.1.38', 2)] }));
    expect(result?.lines).toEqual(['deploy v5.1.38 by demo, 2 min before the alert fired']);
    expect(result?.note).toContain('Gradual upward trend with no clear start time.');
    expect(result?.note).toContain('a slow trend is rarely explained by a single change');
    expect(JSON.stringify(result)).not.toContain('Started');
  });

  it('says when there is no start time instead of implying one', () => {
    const result = whatChanged(alert({ timing: { basis: 'alert_time', time: null, analyzer_id: null, trend_direction: null }, changes: [deploy('v7.2', -3)] }));
    expect(result?.lines).toEqual(['deploy v7.2 by demo, 3 min after the alert fired']);
    expect(result?.note).toMatch(/^No start time found in the metric\./);
  });

  it('names the window when nothing matched', () => {
    expect(whatChanged(alert({ timing: { basis: 'step_change', time: '2026-10-01T21:32:00Z', analyzer_id: 'baseline_shift', trend_direction: null } }))?.lines[0])
      .toMatch(/^No changes in the 30 min before the step change at /);
    expect(whatChanged(alert({ timing: { basis: 'trend', time: null, analyzer_id: null, trend_direction: 'downward' } })))
      .toEqual({ lines: ['No changes in the 30 min before the alert fired.'], note: 'Gradual downward trend with no clear start time.' });
  });

  it('points to the Integrations tile when the service never sent any', () => {
    expect(whatChanged(alert({ service: 'mixed-lab', service_has_change_events: false }))?.lines).toEqual(['No deploys or other changes have been recorded for mixed-lab yet.']);
  });

  it('shows nothing for an alert that is not enriched yet or has no service', () => {
    expect(whatChanged(alert({ service_has_change_events: null }))).toBeNull();
    expect(whatChanged(alert({ service: null }))).toBeNull();
  });
});

describe('changeLabel', () => {
  it('names the cluster a deploy went to, and nothing for a deploy to every cluster', () => {
    expect(changeLabel({ ...deploy('v2.4.38', 1), cluster: 'us' })).toBe('deploy v2.4.38 to us by demo');
    expect(changeLabel({ ...deploy('v2.4.38', 1), cluster: null })).toBe('deploy v2.4.38 by demo');
    expect(changeLabel(deploy('v2.4.38', 1))).toBe('deploy v2.4.38 by demo');
  });
});

describe('deploys found in Prometheus', () => {
  const found = {
    ...deploy('1.0.1', 4),
    author: null,
    source: 'ops-signals:build_info',
    timestamp: '2026-10-01T21:29:00Z',
    description: 'Found automatically: version changed from 1.0.0 to 1.0.1 (build_info metric).',
  };

  it('explains how a found deploy was found, and has nothing to say about one CI sent', () => {
    const hint = foundChangeHint(found)!;
    expect(hint).toMatch(/^Ops Signals found this deploy in Prometheus: version changed from 1\.0\.0 to 1\.0\.1 \(build_info metric\), first seen at .+\. Send deploys from CI to add who deployed and a link\.$/);
    expect(foundChangeHint(deploy('v2', 1))).toBeNull();
    expect(foundChangeHint({ ...deploy('v2', 1), source: 'github-actions' })).toBeNull();
    expect(foundChangeHint({ ...found, description: null, timestamp: null })).toBe('Ops Signals found this deploy in Prometheus. Send deploys from CI to add who deployed and a link.');
  });

  it('marks the found line only, and adds nothing when no deploy was found', () => {
    const timing = { basis: 'step_change' as const, time: '2026-10-01T21:33:00Z', analyzer_id: 'ruptures', trend_direction: null };
    const result = whatChanged(alert({ timing, changes: [found, deploy('v2', 10)] }))!;
    expect(result.lines).toEqual(['Started 4 min after deploy 1.0.1', 'Started 10 min after deploy v2 by demo']);
    expect(result.found?.[0]).toContain('found this deploy in Prometheus');
    expect(result.found?.[1]).toBeNull();
    expect(whatChanged(alert({ timing, changes: [deploy('v2', 10)] }))).not.toHaveProperty('found');
  });

  it('says Ops Signals looked in Prometheus when nothing is recorded and discovery is on', () => {
    const on = whatChanged(alert({ service_has_change_events: false, deploy_discovery: true }))!;
    expect(on.note).toMatch(/^Ops Signals also looks in Prometheus .+ found none for this service\. Send them from your CI/);
    expect(whatChanged(alert({ service_has_change_events: false }))!.note).toBe('Send them from your CI to see them here: Integrations → Send deploy events.');
  });
});
