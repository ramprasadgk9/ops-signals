import type { AlertChange, AlertItem } from '../types';

// Received alerts grouped per alert rule, shared by the web UI's AlertTimeline and the Grafana
// plugin's PluginAlerts so both list and order alerts the same way.

export type SeverityKey = 'critical' | 'warning' | 'other';

/** Worst first. */
export const SEVERITY_RANK: Record<SeverityKey, number> = { critical: 0, warning: 1, other: 2 };

export function severityKey(severity: string | null | undefined): SeverityKey {
  const value = (severity ?? '').toLowerCase();
  if (value === 'critical' || value === 'page' || value === 'high') return 'critical';
  if (value === 'warning' || value === 'warn' || value === 'medium') return 'warning';
  return 'other';
}

export type AlertGroup = {
  key: string;
  alertName: string;
  service: string | null;
  severity: SeverityKey;
  firing: boolean;
  isTest: boolean;
  /** Newest first. */
  occurrences: AlertItem[];
  lastReceivedAt: string;
  /** The case, else the finding, one of the occurrences was linked to. `to` is a web UI route. */
  link: { text: string; to: string } | null;
};

export function alertLink(alert: AlertItem): AlertGroup['link'] {
  if (alert.case_id !== null) return { text: `Case #${alert.case_id}`, to: `/cases/${alert.case_id}` };
  if (alert.finding_id !== null) return { text: `Finding #${alert.finding_id}`, to: `/findings?finding=${alert.finding_id}` };
  return null;
}

/** One group per alert rule (name + service): the list shows a rule once, not every occurrence.
 * Firing groups first, then linked ones, then the most recent. */
export function groupAlerts(alerts: AlertItem[]): AlertGroup[] {
  const groups = new Map<string, AlertItem[]>();
  for (const alert of alerts) {
    const key = `${alert.alert_name}\u0000${alert.service ?? ''}`;
    groups.set(key, [...(groups.get(key) ?? []), alert]);
  }
  return [...groups.entries()]
    .map(([key, items]) => {
      const occurrences = [...items].sort((a, b) => Date.parse(b.received_at) - Date.parse(a.received_at));
      const latest = occurrences[0];
      const linked = occurrences.find((item) => item.case_id !== null || item.finding_id !== null);
      const worst = occurrences.map((item) => severityKey(item.severity)).sort((a, b) => SEVERITY_RANK[a] - SEVERITY_RANK[b])[0];
      return {
        key,
        alertName: latest.alert_name,
        service: latest.service,
        severity: worst,
        firing: occurrences.some((item) => item.status === 'firing'),
        isTest: latest.source === 'test',
        occurrences,
        lastReceivedAt: latest.received_at,
        link: linked ? alertLink(linked) : null,
      };
    })
    .sort((a, b) => Number(b.firing) - Number(a.firing) || Number(Boolean(b.link)) - Number(Boolean(a.link)) || Date.parse(b.lastReceivedAt) - Date.parse(a.lastReceivedAt));
}

export function summarizeAlerts(alerts: AlertItem[]) {
  return {
    firing: alerts.filter((alert) => alert.status === 'firing').length,
    linked: alerts.filter((alert) => alert.finding_id !== null).length,
    resolved: alerts.filter((alert) => alert.status !== 'firing').length,
  };
}

/** The change events matched to any of the group's alerts, once each. */
export function groupChanges(group: AlertGroup): AlertChange[] {
  const seen = new Map<string, AlertChange>();
  for (const alert of group.occurrences) {
    for (const change of alert.changes ?? []) {
      const key = change.id !== null ? String(change.id) : `${change.version}|${change.timestamp}`;
      if (change.timestamp && !seen.has(key)) seen.set(key, change);
    }
  }
  return [...seen.values()];
}
