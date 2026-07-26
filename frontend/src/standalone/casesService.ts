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
  priority: 'Critical' | 'High' | 'Medium';
  isOpen: boolean;
  needsAttention: boolean;
  isOnHold: boolean;
};

export function isClosedCaseStatus(status?: string | null) {
  return CLOSED_CASE_STATUSES.has(status?.toLowerCase() ?? '');
}

export function toCaseRow(item: OperationalCase): CaseRow {
  const severity = item.finding_snapshot?.health_status ?? 'unknown';
  const priorityScore = item.finding_snapshot?.investigation_priority ?? item.finding_snapshot?.importance_score ?? 0;
  const priority = priorityScore >= 0.8 || severity === 'critical' ? 'Critical' : priorityScore >= 0.6 || severity === 'high' ? 'High' : 'Medium';
  const isOnHold = item.case_status === 'on_hold' || item.investigation_status === 'on_hold';

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
    priority,
    isOpen: !isClosedCaseStatus(item.case_status),
    needsAttention: severity === 'critical' || item.root_cause_status === 'unknown',
    isOnHold,
  };
}

export function toCaseRows(cases: OperationalCase[]) {
  return cases.map(toCaseRow);
}

export function filterCaseRows(rows: CaseRow[], filters: { search: string; status: string; severity: string }) {
  const term = filters.search.trim().toLowerCase();
  return rows.filter((row) => {
    const matchesSearch = !term || [row.caseId, row.title, row.summary, row.service].some((value) => value.toLowerCase().includes(term));
    const matchesStatus = filters.status === 'all' || row.status === filters.status || row.investigationStatus === filters.status;
    const matchesSeverity = filters.severity === 'all' || row.severity.toLowerCase() === filters.severity;
    return matchesSearch && matchesStatus && matchesSeverity;
  });
}

export function groupInvestigationRows(rows: CaseRow[]) {
  return {
    active: rows.filter((row) => row.isOpen && !row.needsAttention && !row.isOnHold),
    attention: rows.filter((row) => row.needsAttention && !row.isOnHold),
    onHold: rows.filter((row) => row.isOnHold),
    all: rows,
  };
}
