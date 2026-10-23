import type { AlertChange, AlertItem } from '../types';

// "What changed" for an alert, worded like the Slack message
// (backend/app/notifications/message_builder.py, _what_changed). Only a step change or a spike gives
// a real start time, so only those say "started N min after"; a trend or a missing start time lists
// nearby changes for reference, timed from when the alert fired.

export type WhatChanged = {
  /** One line per matched change, or a single line saying nothing matched. */
  lines: string[];
  /** Where the start time came from, or why there is none. */
  note: string | null;
  /** Per line: how Ops Signals found that deploy in Prometheus, for a "Found automatically" tag;
   * null for a change CI sent. Absent when no line is a found deploy. */
  found?: (string | null)[];
};

const ANALYZER_LABEL: Record<string, string> = {
  baseline_shift: 'baseline shift',
  ruptures: 'change-point detection',
  anomaly_zscore: 'z-score',
  pyod_outlier: 'outlier detection',
  stumpy: 'pattern matching',
};

export function minutes(value: number): string {
  const rounded = Math.round(Math.abs(value));
  if (rounded < 1) return '<1 min';
  if (rounded < 120) return `${rounded} min`;
  return `${(rounded / 60).toFixed(1)} h`;
}

export function clock(iso: string | null): string {
  if (!iso) return 'an unknown time';
  return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

const FOUND_SOURCE = 'ops-signals:';

/** Hover text for a deploy Ops Signals found in Prometheus (docs/deploy-discovery.md); null for a
 * change CI sent. */
export function foundChangeHint(change: AlertChange): string | null {
  if (!change.source?.startsWith(FOUND_SOURCE)) return null;
  const how = (change.description ?? '').replace(/^Found automatically:\s*/, '').replace(/\.$/, '');
  const at = change.timestamp ? `, first seen at ${clock(change.timestamp)}` : '';
  const what = how ? `: ${how}${at}` : at;
  return `Ops Signals found this deploy in Prometheus${what}. Send deploys from CI to add who deployed and a link.`;
}

/** The `found` field of WhatChanged for these changes, or nothing when none was found. */
export function foundHints(changes: AlertChange[]): { found?: (string | null)[] } {
  const found = changes.map(foundChangeHint);
  return found.some(Boolean) ? { found } : {};
}

/** The note under "nothing recorded for this service yet". */
export function noChangesNote(deployDiscovery: boolean | undefined, ciStep: string): string {
  if (!deployDiscovery) return ciStep;
  return `Ops Signals also looks in Prometheus for new versions on *_build_info metrics and new Kubernetes ReplicaSets, and found none for this service. ${ciStep}`;
}

export function changeLabel(change: AlertChange): string {
  const what = `${change.event_type ?? 'change'} ${change.version ?? change.description ?? 'unversioned'}`;
  const where = change.cluster ? `${what} to ${change.cluster}` : what;
  return change.author ? `${where} by ${change.author}` : where;
}

/** Null when the alert hasn't been enriched yet or has no service to match changes against. */
export function whatChanged(alert: AlertItem): WhatChanged | null {
  if (!alert.service || alert.service_has_change_events == null) return null;
  if (!alert.service_has_change_events) {
    return {
      lines: [`No deploys or other changes have been recorded for ${alert.service} yet.`],
      note: noChangesNote(alert.deploy_discovery, 'Send them from your CI to see them here: Integrations → Send deploy events.'),
    };
  }
  const timing = alert.timing ?? { basis: 'alert_time', time: null, analyzer_id: null, trend_direction: null };
  const changes = alert.changes ?? [];
  const window = alert.change_window_before_minutes ?? 30;

  if (timing.basis === 'step_change' || timing.basis === 'spike') {
    const kind = timing.basis === 'step_change' ? 'step change' : 'spike';
    const source = ANALYZER_LABEL[timing.analyzer_id ?? ''] ?? timing.analyzer_id ?? 'analysis';
    let note = `Start time ${clock(timing.time)}, from a ${kind} (${source}).`;
    if (timing.basis === 'spike' && timing.trend_direction) {
      note += ` It sits on a gradual ${timing.trend_direction} trend, which these changes may not explain.`;
    }
    if (!changes.length) return { lines: [`No changes in the ${window} min before the ${kind} at ${clock(timing.time)}.`], note };
    const verb = timing.basis === 'step_change' ? 'Started' : 'Spike started';
    return {
      lines: changes.map((change) => {
        const when = change.minutes_before_anchor ?? 0;
        return `${verb} ${minutes(when)} ${when >= 0 ? 'after' : 'before'} ${changeLabel(change)}`;
      }),
      note,
      ...foundHints(changes),
    };
  }

  const intro = timing.basis === 'trend' ? `Gradual ${timing.trend_direction ?? ''} trend with no clear start time.`.replace('  ', ' ') : 'No start time found in the metric.';
  if (!changes.length) return { lines: [`No changes in the ${window} min before the alert fired.`], note: intro };
  return {
    lines: changes.map((change) => {
      const when = change.minutes_before_anchor ?? 0;
      return `${changeLabel(change)}, ${minutes(when)} ${when >= 0 ? 'before' : 'after'} the alert fired`;
    }),
    note: `${intro} Changes near when the alert fired, listed for reference${timing.basis === 'trend' ? '; a slow trend is rarely explained by a single change' : ''}.`,
    ...foundHints(changes),
  };
}
