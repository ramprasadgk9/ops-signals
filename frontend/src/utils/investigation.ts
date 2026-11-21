import type { Finding } from '../types';
import { needsAttention } from './findingTrust';

// Guided investigation (backend/app/investigation/): types for its API and the words the dialog uses.

export type ServiceDependency = { name: string; kind: DependencyKind };
export type DependencyKind = 'service' | 'database' | 'queue' | 'cache' | 'outside';
export type ServiceBehaviour = { text: string; by?: string | null; at?: string | null; case_id?: number | null };

export type ServiceNote = {
  service: string;
  exists: boolean;
  depends_on: ServiceDependency[];
  behaviours: ServiceBehaviour[];
  dismissed: string[];
  owner: string | null;
  channel: string | null;
  runbook_url: string | null;
  updated_by: string | null;
  updated_at: string | null;
};

export type DependencySuggestion = ServiceDependency & { label: string };

export type InvestigationStatus = 'running' | 'done' | 'paused' | 'stopped' | 'failed';
export type InvestigationEnding =
  | 'found'
  | 'nothing_found'
  | 'waiting'
  | 'budget'
  | 'no_progress'
  | 'source_down'
  | 'ai_failed'
  | 'stopped'
  | 'interrupted';

export type InvestigationSummary = {
  id: number;
  finding_id: number;
  service: string | null;
  status: InvestigationStatus;
  ending: InvestigationEnding | null;
  ending_detail: string | null;
  summary: string | null;
  question: string | null;
  round: number;
  checks_used: number;
  check_budget: number;
  case_id: number | null;
  model: string | null;
  started_by: string | null;
  context_note: string | null;
  skipped_sources: string[];
  created_at: string | null;
  updated_at: string | null;
};

export type InvestigationCheck = {
  ref: string;
  round: number;
  tool: string;
  purpose: string | null;
  query: string | null;
  ok: boolean;
  result: string;
  at: string | null;
};

export type StepKind = 'checked' | 'your_step' | 'from_history';
export type StepStatus = 'ruled_out' | 'worth_a_look' | 'todo';
export type StepMark = 'found' | 'ruled_out';

export type InvestigationStep = {
  id: number;
  round: number;
  position: number;
  kind: StepKind;
  status: StepStatus;
  title: string;
  why: string | null;
  result: string | null;
  evidence: string[];
  unverified: boolean;
  mark: StepMark | null;
  note: string | null;
  marked_by: string | null;
};

export type Investigation = InvestigationSummary & { checks: InvestigationCheck[]; steps: InvestigationStep[] };

export type InvestigationStartInfo = {
  finding_id: number;
  eligible: boolean;
  reason: string | null;
  ai_on: boolean;
  service: string | null;
  connection_id: string | null;
  connection_name: string | null;
  has_query: boolean;
  note: ServiceNote;
  latest: InvestigationSummary | null;
};

export type StartInvestigationRequest = {
  finding_id: number;
  note?: string | null;
  save_note?: boolean;
  skipped_sources?: string[];
};

export const DEPENDENCY_KINDS: { value: DependencyKind; label: string }[] = [
  { value: 'service', label: 'service' },
  { value: 'database', label: 'database' },
  { value: 'queue', label: 'queue' },
  { value: 'cache', label: 'cache' },
  { value: 'outside', label: 'outside service' },
];

/** Sources a person can leave out, in the order the dialog lists them. */
export const OPTIONAL_SOURCES = [
  { key: 'changes', label: 'Deploys and changes', detail: 'CI events and deploys found automatically.' },
  { key: 'cases', label: 'Past cases', detail: 'Closed cases on this service, with their cause and fix.' },
  { key: 'notes', label: 'What your team knows', detail: 'The dependencies and known behaviour above.' },
] as const;

/** Checks per round, as backend/app/investigation/loop.py sets them. */
export const FIRST_CHECKS = 15;
export const LATER_CHECKS = 8;

export const INVESTIGATE_LIMITS = `It runs up to ${FIRST_CHECKS} read-only checks, each over at most 12 hours of data.`;

export const DISCLAIMER =
  "It suggests where to look and checks what it can. It can be wrong, and it won't claim a root cause: you confirm one.";

export const SHARED_WITH_AI =
  'It sends the finding, the results of its checks, the notes above and your note to the AI provider in AI settings. It reads metrics only: not logs, traces or the databases themselves.';

export const INVESTIGATE_AI_SETUP = {
  intro:
    'Investigate uses an AI model to choose what to check and to explain what it found. It works best with a strong model: small local models often lose track over several checks.',
  other: 'Everything else on this card works without AI: what changed, seen before and similar cases.',
} as const;

/** Whether a finding can be investigated: needs attention, came from Prometheus, has a service. */
export function canInvestigate(finding: Finding): boolean {
  return (
    finding.id != null &&
    needsAttention(finding) &&
    !!finding.connection_id &&
    (!finding.source || finding.source === 'prometheus') &&
    !!finding.service &&
    finding.service !== 'unknown'
  );
}

export function isRunning(investigation: Pick<InvestigationSummary, 'status'> | null | undefined): boolean {
  return investigation?.status === 'running';
}

/** The banner at the top of the steps: what the round ended with. */
export function endingBanner(investigation: InvestigationSummary): { severity: 'success' | 'info' | 'warning' | 'error'; title: string; detail: string | null } {
  const detail = investigation.ending_detail;
  switch (investigation.ending) {
    case 'found':
      return { severity: 'success', title: 'Found where to look', detail: null };
    case 'nothing_found':
      return { severity: 'info', title: 'Nothing found in metrics', detail: "Everything it could reach is ruled out. What's left is below." };
    case 'waiting':
      return { severity: 'info', title: 'Waiting for you', detail: investigation.question };
    case 'budget':
      return { severity: 'warning', title: 'Paused', detail: detail ?? 'The checks for this round are used up.' };
    case 'no_progress':
      return { severity: 'info', title: 'It stopped finding anything new', detail: detail ?? 'The steps so far are kept.' };
    case 'source_down':
      return { severity: 'error', title: "Couldn't reach Prometheus", detail: 'The steps so far are kept.' };
    case 'ai_failed':
      return { severity: 'error', title: "The AI model didn't answer", detail };
    case 'stopped':
      return { severity: 'warning', title: 'Stopped', detail: 'The steps so far are kept.' };
    case 'interrupted':
      return { severity: 'warning', title: 'Interrupted', detail: detail ?? 'The steps so far are kept.' };
    default:
      return { severity: 'info', title: 'Investigating…', detail: null };
  }
}

/** Whether "Continue" makes sense: paused, or stopped by a person or a passing failure. */
export function canContinue(investigation: InvestigationSummary): boolean {
  return investigation.status !== 'running';
}

export function stepTag(step: InvestigationStep): { label: string; color: 'warning' | 'default' | 'info' | 'success' } {
  if (step.mark === 'found') return { label: 'You found something', color: 'success' };
  if (step.mark === 'ruled_out') return { label: 'You ruled it out', color: 'default' };
  if (step.kind === 'your_step') return { label: 'Your step', color: 'info' };
  if (step.status === 'worth_a_look') return { label: 'Worth a look', color: 'warning' };
  if (step.status === 'ruled_out') return { label: 'Ruled out', color: 'default' };
  if (step.kind === 'from_history') return { label: 'From a past case', color: 'info' };
  return { label: 'To check', color: 'default' };
}

/** "Started by priya · 5 checks · round 2". */
export function investigationByline(investigation: Investigation): string {
  const checks = investigation.checks.length;
  return [
    investigation.started_by ? `Started by ${investigation.started_by}` : null,
    `${checks} ${checks === 1 ? 'check' : 'checks'}`,
    investigation.round > 1 ? `round ${investigation.round}` : null,
    investigation.model ? `model ${investigation.model}` : null,
  ]
    .filter(Boolean)
    .join(' · ');
}

/** The checks a step cites, for "Show query". */
export function stepChecks(step: InvestigationStep, checks: InvestigationCheck[]): InvestigationCheck[] {
  return step.evidence.map((ref) => checks.find((check) => check.ref === ref)).filter((check): check is InvestigationCheck => !!check);
}

export function sameDependencies(a: ServiceDependency[], b: ServiceDependency[]): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}
