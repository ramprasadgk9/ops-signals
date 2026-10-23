import { describe, expect, it } from 'vitest';
import type { AlertChange } from '../types';
import { changeChipLabel, deployNextStep, findingChanges, findingWhatChanged, podLinkText, type FindingChanges } from './findingChanges';

const deploy: AlertChange = {
  id: 7,
  event_type: 'deploy',
  version: 'v1.4.2',
  description: null,
  author: null,
  url: null,
  timestamp: '2026-10-01T14:06:00Z',
  minutes_before_anchor: 4,
};

const matched: FindingChanges = {
  status: 'matched',
  service: 'cart',
  anchor: '2026-10-01T14:10:00Z',
  window_before_minutes: 30,
  window_after_minutes: 5,
  matches: [deploy],
  pods: {
    status: 'linked',
    method: 'pod_start_time',
    event_id: 7,
    label: 'pod',
    parts: ['cart-8c2-q1', 'cart-8c2-w7'],
    new_parts: 2,
    old_parts_running: 4,
    old_parts_gone: 0,
    rollout_minutes: 15,
  },
};

describe('findingChanges', () => {
  it('ignores a missing or unknown value instead of failing', () => {
    expect(findingChanges({})).toBeNull();
    expect(findingChanges({ changes: { status: 'something-new' } })).toBeNull();
    expect(findingChanges({ changes: 'oops' })).toBeNull();
  });

  it('labels the chip with the change that came before the finding', () => {
    expect(changeChipLabel(matched)).toBe('After deploy v1.4.2');
    const afterOnly = { ...matched, matches: [{ ...deploy, minutes_before_anchor: -3 }] };
    expect(changeChipLabel(afterOnly)).toBeNull();
    expect(changeChipLabel({ status: 'no_events_for_service', service: 'cart' })).toBeNull();
  });

  it('says which new pods started with the deploy', () => {
    const text = podLinkText(matched)!;
    expect(text.sentence).toMatch(/^These 2 new pods started with deploy v1\.4\.2 \(.+\), 4 min before the change\.$/);
    expect(text.detail).toBe('Matched by pod start time: within 15 min after the deploy. 4 older pods still running (canary or partial rollout).');
    expect(deployNextStep(matched)).toContain('pods from deploy v1.4.2');
  });

  it('explains when new pods could not be matched, and stays quiet when there is nothing to say', () => {
    const outside = { ...matched, pods: { status: 'not_linked' as const, reason: 'started_outside_rollout', label: 'pod', rollout_minutes: 15 } };
    expect(podLinkText(outside)?.sentence).toContain('didn’t start within 15 min after the deploy');
    const old = { ...matched, pods: { status: 'not_linked' as const, reason: 'no_start_times', label: 'pod' } };
    expect(podLinkText(old)?.sentence).toContain('before pod start times were recorded');
    for (const reason of ['no_breakdown', 'no_new_parts', 'no_deploy']) {
      expect(podLinkText({ ...matched, pods: { status: 'not_linked', reason } })).toBeNull();
    }
    expect(deployNextStep(outside)).toBeNull();
  });

  it('has a plain sentence for every status', () => {
    expect(findingWhatChanged(matched).lines).toEqual(['Started 4 min after deploy v1.4.2']);
    expect(findingWhatChanged({ ...matched, status: 'none_in_window', matches: [], pods: undefined }).lines[0]).toMatch(/^No deploys or other changes for cart between .+ and .+\.$/);
    const none = findingWhatChanged({ status: 'no_events_for_service', service: 'cart' });
    expect(none.lines).toEqual(['No deploys or other changes have been recorded for cart yet.']);
    expect(none.note).toContain('OPS_SIGNALS_SERVICE_ALIASES');
    expect(none.note).not.toContain('Prometheus');
    expect(findingWhatChanged({ status: 'no_events_for_service', service: 'cart', deploy_discovery: true }).note)
      .toMatch(/^Ops Signals also looks in Prometheus for new versions on \*_build_info metrics .+ Send deploys from your CI/);
    const foundDeploy = { ...matched.matches![0], source: 'ops-signals:kube_replicaset', description: 'Found automatically: Kubernetes rolled out a new ReplicaSet cart-7d9 in namespace shop.' };
    const withFound = findingWhatChanged({ ...matched, matches: [foundDeploy] });
    expect(withFound.found?.[0]).toContain('Kubernetes rolled out a new ReplicaSet cart-7d9');
    expect(findingWhatChanged(matched)).not.toHaveProperty('found');
    expect(findingWhatChanged({ status: 'unavailable', reason: 'no_service' }).lines[0]).toContain('no service');
    expect(findingWhatChanged({ status: 'unavailable', reason: 'no_change_time' }).lines[0]).toContain('no single start time');
    expect(findingWhatChanged({ status: 'unavailable', reason: 'error' }).lines[0]).toContain('Could not check for deploys');
    expect(findingWhatChanged({ status: 'unavailable', reason: 'brand_new_reason' }).lines[0]).toBe('Deploys could not be checked for this finding.');
  });
});
