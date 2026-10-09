/**
 * How a finding's health_status reads on screen. The stored values (critical / significant /
 * normal, from the importance score) stay as they are; "normal" only means low importance - a
 * change was still found - so it is shown as "Low" in grey, never as a green "all fine".
 */
export type FindingLevel = {
  label: 'High' | 'Medium' | 'Low' | string;
  /** MUI Chip color. */
  chip: 'error' | 'warning' | 'default';
  tone: { color: string; bg: string; border: string };
};

const levels: Record<string, FindingLevel> = {
  critical: { label: 'High', chip: 'error', tone: { color: '#ef4444', bg: 'var(--os-tint-rose)', border: 'var(--os-tint-rose-border)' } },
  significant: { label: 'Medium', chip: 'warning', tone: { color: '#d97706', bg: 'var(--os-tint-amber)', border: 'var(--os-tint-amber-border)' } },
  normal: { label: 'Low', chip: 'default', tone: { color: 'var(--os-muted)', bg: 'var(--os-surface-alt)', border: 'var(--os-border)' } },
};

export function findingLevel(status?: string | null): FindingLevel {
  const known = levels[(status ?? '').toLowerCase()];
  if (known) return known;
  const label = status ? status.charAt(0).toUpperCase() + status.slice(1) : 'Unknown';
  return { label, chip: 'default', tone: levels.normal.tone };
}

/** Explains the level in a tooltip. */
export function findingLevelHint(status?: string | null): string {
  switch ((status ?? '').toLowerCase()) {
    case 'critical':
      return 'High importance (score 0.8 or more): look at this first.';
    case 'significant':
      return 'Medium importance (score 0.55 to 0.8): worth investigating.';
    case 'normal':
      return 'Low importance (score below 0.55): a change was found, but it is small or weakly supported.';
    default:
      return '';
  }
}
