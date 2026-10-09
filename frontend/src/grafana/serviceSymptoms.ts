import type { Finding } from '../types';
import { groupRepeatedFindings, type FindingGroup } from '../utils/findingSearch';
import type { GrafanaCase } from './contracts';

// A service's symptoms for the Autonomous overview: its findings with repeats across runs folded
// into one (the web UI's "Group repeats", utils/findingSearch), worst first. A case is opened per
// symptom, as in the web UI; any run of a symptom can carry it.

export type ServiceSymptom = FindingGroup;

export function symptomKey(symptom: ServiceSymptom): string {
  return String(symptom.finding.id ?? `${symptom.finding.metric_name}:${symptom.finding.title}`);
}

/** Findings with no service are grouped under "unknown", as the overview's service list does. */
export function serviceSymptoms(findings: Finding[], service: string): ServiceSymptom[] {
  const onService = findings.filter((finding) => (finding.service || 'unknown') === service);
  const worstFirst = [...onService].sort((a, b) => (b.importance_score ?? 0) - (a.importance_score ?? 0));
  return groupRepeatedFindings(worstFirst);
}

/** Finding id -> case id, from cases opened from a finding. */
export function caseIdsByFinding(cases: Array<Pick<GrafanaCase, 'id' | 'finding_id'>>): Map<number, number> {
  const byFinding = new Map<number, number>();
  for (const caseItem of cases) {
    if (typeof caseItem.finding_id === 'number' && !byFinding.has(caseItem.finding_id)) byFinding.set(caseItem.finding_id, caseItem.id);
  }
  return byFinding;
}

export function caseForSymptom(symptom: ServiceSymptom, byFinding: Map<number, number>): number | null {
  for (const run of symptom.runs) {
    if (typeof run.id === 'number' && byFinding.has(run.id)) return byFinding.get(run.id) ?? null;
  }
  return null;
}

/** The symptom a finding belongs to, by any of its runs. */
export function symptomOf(symptoms: ServiceSymptom[], finding: Finding | null): ServiceSymptom | null {
  if (!finding) return null;
  return symptoms.find((symptom) => symptom.runs.some((run) => run === finding || (run.id !== undefined && run.id === finding.id))) ?? null;
}
