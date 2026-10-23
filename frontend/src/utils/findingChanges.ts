import type { AlertChange, Finding } from '../types';
import { changeLabel, clock, foundHints, minutes, noChangesNote } from './alertChanges';

// Deploys and other change events near a finding's change, looked up by the backend when the
// finding is read (backend/app/services/finding_changes.py). Every status, including "data
// missing", has a sentence here; a finding from an older backend has no `changes` and shows nothing.

export type PodLink =
  | {
      status: 'linked';
      method: string;
      event_id: number | null;
      label: string;
      parts: string[];
      new_parts: number;
      old_parts_running: number;
      old_parts_gone: number;
      rollout_minutes: number;
    }
  | { status: 'not_linked'; reason: string; label?: string; rollout_minutes?: number };

export type FindingChanges = {
  status: 'matched' | 'none_in_window' | 'no_events_for_service' | 'unavailable';
  reason?: string;
  service?: string;
  anchor?: string;
  window_before_minutes?: number;
  window_after_minutes?: number;
  matches?: AlertChange[];
  pods?: PodLink;
  /** With no_events_for_service: Ops Signals also looks for deploys in Prometheus. */
  deploy_discovery?: boolean;
};

export type FindingWhatChanged = { lines: string[]; note: string | null; found?: (string | null)[] };

const STATUSES = ['matched', 'none_in_window', 'no_events_for_service', 'unavailable'];

export function findingChanges(finding: Pick<Finding, 'changes'>): FindingChanges | null {
  const raw = finding.changes;
  if (!raw || typeof raw !== 'object' || !STATUSES.includes((raw as FindingChanges).status)) return null;
  return raw as FindingChanges;
}

function plural(label: string, count: number): string {
  return count === 1 ? label : `${label}s`;
}

function shiftedClock(iso: string | undefined, offsetMinutes: number): string {
  if (!iso) return 'an unknown time';
  return clock(new Date(new Date(iso).getTime() + offsetMinutes * 60_000).toISOString());
}

/** The nearest change event that came before the finding's change, if any. */
export function priorChange(changes: FindingChanges | null): AlertChange | null {
  if (changes?.status !== 'matched') return null;
  return (changes.matches ?? []).find((match) => (match.minutes_before_anchor ?? -1) >= 0) ?? null;
}

/** Short chip label, e.g. "After deploy v1.4.2". Null unless a change came before the finding's change. */
export function changeChipLabel(changes: FindingChanges | null): string | null {
  const change = priorChange(changes);
  if (!change) return null;
  return `After ${change.event_type ?? 'change'} ${change.version ?? ''}`.trim();
}

const UNAVAILABLE: Record<string, string> = {
  no_service: 'Not checked: this finding has no service to match deploys against.',
  no_change_time: 'Not checked: this finding has no single start time (for example a slow trend), so deploys can’t be matched by time.',
  error: 'Could not check for deploys right now. Try again later; the backend log has the details.',
};

/** "What changed": one line per matched change, or one line saying why there is none. */
export function findingWhatChanged(changes: FindingChanges): FindingWhatChanged {
  const service = changes.service ?? 'this service';
  if (changes.status === 'unavailable') {
    return { lines: [UNAVAILABLE[changes.reason ?? ''] ?? 'Deploys could not be checked for this finding.'], note: null };
  }
  if (changes.status === 'no_events_for_service') {
    return {
      lines: [`No deploys or other changes have been recorded for ${service} yet.`],
      note: noChangesNote(
        changes.deploy_discovery,
        'Send deploys from your CI: Integrations → Send deploy events. If CI uses a different name for this service, list both names in OPS_SIGNALS_SERVICE_ALIASES.',
      ),
    };
  }
  const before = changes.window_before_minutes ?? 30;
  const after = changes.window_after_minutes ?? 5;
  const started = `The change started at ${clock(changes.anchor ?? null)}.`;
  if (changes.status === 'none_in_window' || !(changes.matches ?? []).length) {
    return {
      lines: [`No deploys or other changes for ${service} between ${shiftedClock(changes.anchor, -before)} and ${shiftedClock(changes.anchor, after)}.`],
      note: started,
    };
  }
  return {
    lines: (changes.matches ?? []).map((match) => {
      const when = match.minutes_before_anchor ?? 0;
      return when >= 0 ? `Started ${minutes(when)} after ${changeLabel(match)}` : `${changeLabel(match)} came ${minutes(when)} after the change started`;
    }),
    note: `${started} Changes from ${before} min before to ${after} min after are listed. Close timing is a hint, not proof of cause.`,
    ...foundHints(changes.matches ?? []),
  };
}

function linkedDeploy(changes: FindingChanges): AlertChange | null {
  const pods = changes.pods;
  if (pods?.status !== 'linked') return null;
  return (changes.matches ?? []).find((match) => match.id === pods.event_id) ?? null;
}

/** For the pod breakdown: which new pods started with the deploy, or why they couldn't be matched.
 * Null when there is nothing to say about pods (no deploy, no new pods, no breakdown). */
export function podLinkText(changes: FindingChanges | null): { sentence: string; detail: string | null } | null {
  if (changes?.status !== 'matched' || !changes.pods) return null;
  const pods = changes.pods;
  if (pods.status === 'linked') {
    const deploy = linkedDeploy(changes);
    const label = pods.label || 'pod';
    const count = pods.parts.length;
    const who = count === pods.new_parts
      ? count === 1 ? `This new ${label}` : `These ${count} new ${plural(label, count)}`
      : `${count} of the ${pods.new_parts} new ${plural(label, pods.new_parts)}`;
    const what = deploy ? changeLabel(deploy) : 'the deploy';
    const when = deploy?.minutes_before_anchor != null && deploy.minutes_before_anchor >= 0 ? `, ${minutes(deploy.minutes_before_anchor)} before the change` : '';
    const at = deploy?.timestamp ? ` (${clock(deploy.timestamp)})` : '';
    const sentence = `${who} started with ${what}${at}${when}.`;
    const older = pods.old_parts_running > 0
      ? ` ${pods.old_parts_running} older ${plural(label, pods.old_parts_running)} still running (canary or partial rollout).`
      : pods.old_parts_gone > 0 ? ` The older ${plural(label, 2)} were replaced.` : '';
    return { sentence, detail: `Matched by ${label} start time: within ${pods.rollout_minutes} min after the deploy.${older}` };
  }
  const label = pods.label || 'pod';
  if (pods.reason === 'started_outside_rollout') {
    return {
      sentence: `The new ${plural(label, 2)} didn’t start within ${pods.rollout_minutes ?? 15} min after the deploy, so they may come from something else, such as scaling.`,
      detail: null,
    };
  }
  if (pods.reason === 'no_start_times') {
    return {
      sentence: `This finding was analyzed before ${label} start times were recorded, so its new ${plural(label, 2)} can’t be matched to the deploy. Findings from new runs include them.`,
      detail: null,
    };
  }
  return null;
}

/** Next step when the moved pods came from a deploy; null to keep the breakdown's own advice. */
export function deployNextStep(changes: FindingChanges | null): string | null {
  if (!changes || changes.pods?.status !== 'linked') return null;
  const deploy = linkedDeploy(changes);
  const what = deploy ? changeLabel(deploy) : 'the deploy';
  return `The change is on the ${plural(changes.pods.label || 'pod', 2)} from ${what}. Compare it with the previous version before the rollout finishes, or roll it back.`;
}
