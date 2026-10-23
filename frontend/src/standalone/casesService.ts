import { isRootCauseUnconfirmed } from '../components/RootCauseUnconfirmedBadge';
import type { OperationalCase } from '../types';

const CLOSED_CASE_STATUSES = new Set(['resolved', 'verified', 'closed', 'completed']);

export type CaseRow = {
  id: number;
  caseId: string;
  title: string;
  severity: string;
  status: string;
  investigationStatus: string;
  assignment: 'unsupported';
  service: string;
  metric: string;
  createdAt: string;
  updatedAt: string;
  resolvedAt: string | null;
  outcome: string;
  summary: string;
  rootCause: string | null;
  resolution: string | null;
  notes: Array<{ timestamp?: string; note: string }>;
  isOpen: boolean;
  isOnHold: boolean;
  /** Where the work stands: the status pill on the Cases list. */
  workState: CaseWorkState;
  /** Imported from an incident tool or postmortem rather than opened from a finding. */
  imported: boolean;
  source: string;
  sourceId: string | null;
  sourceUrl: string | null;
  /** Resolved without a verified root cause (see RootCauseUnconfirmedBadge). */
  rootCauseUnconfirmed: boolean;
};

export type CaseWorkState = 'not_started' | 'in_progress' | 'on_hold' | 'resolved';

/** Tabs on the Cases page; `open` includes in-progress cases. */
export const CASE_TABS = [
  { value: 'open', label: 'Open' },
  { value: 'in-progress', label: 'In progress' },
  { value: 'on-hold', label: 'On hold' },
  { value: 'resolved', label: 'Resolved' },
  { value: 'all', label: 'All' },
] as const;

export type CaseTab = (typeof CASE_TABS)[number]['value'];

export function isCaseTab(value: string | null): value is CaseTab {
  return CASE_TABS.some((tab) => tab.value === value);
}

export function isClosedCaseStatus(status?: string | null) {
  return CLOSED_CASE_STATUSES.has(status?.toLowerCase() ?? '');
}

export function toCaseRow(item: OperationalCase): CaseRow {
  const severity = item.finding_snapshot?.health_status ?? 'unknown';
  const isOpen = !isClosedCaseStatus(item.case_status);
  const isOnHold = isOpen && (item.case_status === 'on_hold' || item.investigation_status === 'on_hold');
  const workState: CaseWorkState = !isOpen
    ? 'resolved'
    : isOnHold
      ? 'on_hold'
      : item.investigation_status === 'in_progress' || item.case_status === 'in_progress'
        ? 'in_progress'
        : 'not_started';

  return {
    id: item.id,
    caseId: `C-${item.id}`,
    title: item.case_title,
    severity,
    status: item.case_status,
    investigationStatus: item.investigation_status || item.case_status,
    assignment: 'unsupported',
    service: item.finding_snapshot?.service ?? 'n/a',
    metric: item.finding_snapshot?.metric_name ?? 'n/a',
    createdAt: item.created_at,
    updatedAt: item.updated_at,
    resolvedAt: item.resolved_at ?? null,
    outcome: item.outcome_status,
    summary: item.finding_snapshot?.summary ?? item.case_title,
    rootCause: item.root_cause_summary ?? null,
    resolution: item.outcome_summary ?? item.corrective_action ?? null,
    notes: item.investigation_notes ?? [],
    isOpen,
    isOnHold,
    workState,
    imported: isImportedCase(item),
    source: item.source ?? 'detected',
    sourceId: item.source_id ?? null,
    sourceUrl: item.source_url ?? null,
    rootCauseUnconfirmed: isRootCauseUnconfirmed({ case_status: item.case_status, rootCauseVerified: item.root_cause_verified, source: item.source }),
  };
}

export function isImportedCase(item: Pick<OperationalCase, 'source'>) {
  return Boolean(item.source && item.source !== 'detected');
}

export function toCaseRows(cases: OperationalCase[]) {
  return cases.map(toCaseRow);
}

export function inCaseTab(row: CaseRow, tab: CaseTab) {
  if (tab === 'open') return row.isOpen && !row.isOnHold;
  if (tab === 'in-progress') return row.workState === 'in_progress';
  if (tab === 'on-hold') return row.isOnHold;
  if (tab === 'resolved') return !row.isOpen;
  return true;
}

export function filterCaseRows(
  rows: CaseRow[],
  filters: { search: string; severity: string; origin?: 'all' | 'detected' | 'imported' }
) {
  const term = filters.search.trim().toLowerCase();
  const origin = filters.origin ?? 'all';
  return rows.filter((row) => {
    const matchesSearch = !term || [row.caseId, row.title, row.summary, row.service, row.metric, row.sourceId ?? ''].some((value) => value.toLowerCase().includes(term));
    const matchesSeverity = filters.severity === 'all' || row.severity.toLowerCase() === filters.severity;
    const matchesOrigin = origin === 'all' || (origin === 'imported') === row.imported;
    return matchesSearch && matchesSeverity && matchesOrigin;
  });
}
