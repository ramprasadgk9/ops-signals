import type { BehaviorFinding, Finding, OperationalCase } from '../types';

export type OverviewSummary = {
  activeFindings: number;
  openCases: number;
  behaviorChanges: number;
  impactedServices: number;
  memoryItems: number;
};

export type CategoryBreakdown = {
  category: string;
  count: number;
};

const CLOSED_CASE_STATUSES = new Set(['resolved', 'verified', 'closed', 'completed']);
const OPEN_FINDING_OUTCOMES = new Set(['resolved', 'verified', 'closed', 'completed']);

export function isOpenCase(item: OperationalCase) {
  return !CLOSED_CASE_STATUSES.has(item.case_status?.toLowerCase());
}

export function isActiveFinding(finding: Finding, cases: OperationalCase[]) {
  const matchingCase = typeof finding.id === 'number' ? cases.find((item) => item.finding_id === finding.id) : undefined;
  if (!matchingCase) return true;
  return !OPEN_FINDING_OUTCOMES.has(matchingCase.outcome_status?.toLowerCase()) && !CLOSED_CASE_STATUSES.has(matchingCase.case_status?.toLowerCase());
}

export function buildOverviewSummary(findings: Finding[], cases: OperationalCase[], behaviors: BehaviorFinding[]): OverviewSummary {
  const activeFindings = findings.filter((finding) => isActiveFinding(finding, cases));
  return {
    activeFindings: activeFindings.length,
    openCases: cases.filter(isOpenCase).length,
    behaviorChanges: behaviors.length,
    impactedServices: new Set(activeFindings.map((finding) => finding.service).filter(Boolean)).size,
    memoryItems: cases.filter((item) => item.memory_status === 'indexed').length,
  };
}

export function buildCategoryBreakdown(findings: Finding[]): CategoryBreakdown[] {
  const counts = findings.reduce<Record<string, number>>((acc, finding) => {
    const category = finding.category || 'unknown';
    acc[category] = (acc[category] ?? 0) + 1;
    return acc;
  }, {});
  return Object.entries(counts)
    .map(([category, count]) => ({ category, count }))
    .sort((a, b) => b.count - a.count || a.category.localeCompare(b.category));
}
