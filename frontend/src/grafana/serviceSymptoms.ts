import type { Finding } from '../types';
import { groupRepeatedFindings, type FindingGroup } from '../utils/findingSearch';
import { needsAttention } from '../utils/findingTrust';
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

// --- Triage: what to act on, what is a data problem, what is background -------------------------

export type SymptomRole = 'attention' | 'data' | 'background';

/** Data problems (no data arrived, or the value froze) are monitoring fixes, not service changes;
 * the rest follow the trust tiers the web UI uses: needs attention, or context (background). */
export function symptomRole(finding: Finding): SymptomRole {
  const trust = finding.trust;
  if (trust?.group === 'data_problem' || trust?.badge === 'data_problem' || (!trust && finding.category === 'data_quality')) return 'data';
  return needsAttention(finding) ? 'attention' : 'background';
}

/** One row per metric that needs attention: its worst symptom leads; the metric's other,
 * non-data symptoms ride along instead of appearing as rows that look the same. */
export type MetricRow = { lead: ServiceSymptom; others: ServiceSymptom[] };

export type SymptomTriage = {
  attention: MetricRow[];
  data: ServiceSymptom[];
  background: ServiceSymptom[];
  /** Newest finding on the service: what "still showing" is measured against. */
  latestSeen: string | null;
};

export function triageSymptoms(symptoms: ServiceSymptom[]): SymptomTriage {
  const attention: MetricRow[] = [];
  const data: ServiceSymptom[] = [];
  const background: ServiceSymptom[] = [];
  for (const symptom of symptoms) {
    const role = symptomRole(symptom.finding);
    if (role === 'data') data.push(symptom);
    else if (role === 'background') background.push(symptom);
    else {
      const row = attention.find((item) => item.lead.finding.metric_name === symptom.finding.metric_name);
      if (row) row.others.push(symptom);
      else attention.push({ lead: symptom, others: [] });
    }
  }
  for (const row of attention) {
    row.others.push(...background.filter((symptom) => symptom.finding.metric_name === row.lead.finding.metric_name));
  }
  const latestSeen = symptoms.map((symptom) => symptom.lastSeen).filter((value): value is string => Boolean(value))
    .sort((a, b) => Date.parse(b) - Date.parse(a))[0] ?? null;
  return { attention, data, background, latestSeen };
}

/** In this order the overview picks its default symptom: worst needs-attention first. */
export function triageOrder(triage: SymptomTriage): ServiceSymptom[] {
  return [...triage.attention.map((row) => row.lead), ...triage.data, ...triage.background];
}

const STILL_SHOWING_MS = 90 * 60_000;

/** Seen in the service's latest run(s), within 90 minutes of its newest finding. */
export function stillShowing(symptom: ServiceSymptom, latestSeen: string | null): boolean {
  if (!symptom.lastSeen || !latestSeen) return false;
  return Date.parse(latestSeen) - Date.parse(symptom.lastSeen) <= STILL_SHOWING_MS;
}

/** 0.006, 0.046, 417, 1.25: two significant figures for small values, without trailing zeros. */
function formatValue(value: number): string {
  const magnitude = Math.abs(value);
  if (magnitude >= 100) return value.toFixed(0);
  if (magnitude >= 1) return String(Number(value.toFixed(2)));
  return magnitude === 0 ? '0' : String(Number(value.toPrecision(2)));
}

function numeric(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/** What changed, in the metric's own values: "stepped up 0.006 → 0.046", with the percent apart.
 * Null for data problems and findings without before/after values. */
export function symptomChange(finding: Finding): { text: string; percent: string | null } | null {
  if (symptomRole(finding) === 'data') return null;
  const comparison = finding.comparison_json ?? {};
  const before = numeric(comparison.previous_mean) ?? numeric(comparison.first_half_mean);
  const after = numeric(comparison.current_mean) ?? numeric(comparison.second_half_mean);
  const change = numeric(comparison.change_percent) ?? numeric(comparison.percent_change);
  const percent = change === null ? null : `${change >= 0 ? '+' : ''}${Math.round(change)}%`;
  const group = finding.trust?.group;
  if (group === 'spike') {
    const peak = numeric(comparison.current_max);
    if (peak !== null) return { text: `spiked to ${formatValue(peak)}`, percent: null };
  }
  if (before === null || after === null) return null;
  const up = after >= before;
  const verb = group === 'level_change_agree' || group === 'level_change_single' ? (up ? 'stepped up' : 'stepped down') : (up ? 'rose' : 'fell');
  return { text: `${verb} ${formatValue(before)} → ${formatValue(after)}`, percent };
}

/** Short plain name for a symptom that rides along on a metric row or sits in background. */
export function symptomKind(finding: Finding): string {
  const group = finding.trust?.group;
  if (group === 'level_change_agree' || group === 'level_change_single') return 'level change';
  if (group === 'spike') return 'spike';
  if (group === 'pattern') return /trend/i.test(finding.title) ? 'trend' : 'unusual activity';
  if (group === 'data_problem') return 'data gap';
  return finding.category.split('_').join(' ');
}
