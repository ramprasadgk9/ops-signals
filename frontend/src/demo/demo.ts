// Demo mode for the hosted demo (backend/app/demo.py): what the web UI needs to know, the "Things to
// try" steps, and how a step ticks itself off. Off unless the backend says it's on.
import { useContext } from 'react';
import { QueryClient, QueryClientContext, useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import type { DemoInfo } from '../types';

// For components rendered with no QueryClient (some tests, embeds): never queried, so "not a demo".
const NO_CLIENT = new QueryClient();

export function useDemo(): DemoInfo | null {
  const client = useContext(QueryClientContext);
  const query = useQuery(
    { queryKey: ['demo'], queryFn: () => api.demo(), retry: false, refetchOnWindowFocus: false, staleTime: 10 * 60_000, enabled: Boolean(client) },
    client ?? NO_CLIENT,
  );
  return query.data?.enabled ? query.data : null;
}

export { DEMO_STEP_EVENT, markDemoStep } from './events';

export type DemoStep = {
  id: string;
  title: string;
  how: string;
  go: string;
  goLabel: string;
  /** Done when the visitor opens one of these pages... */
  pages?: string[];
  /** ...or does something that fires one of these marks (markDemoStep). */
  marks?: string[];
  /** The button opens today's finding for this service (and metric) instead of the plain page. */
  finding?: { service: string; metric?: string };
  /** The button also opens this on the page it goes to. */
  open?: 'handoff';
};

// The tour in docs/demo.md, "Things to try". The story's services come from demo/scenario.py.
export const DEMO_STEPS: DemoStep[] = [
  {
    id: 'alert',
    title: 'Read the alert as it reached the team',
    how: 'Alerts shows the checkout-api alert as Slack got it: what happened, the deploy behind it, and how it was fixed last time.',
    go: '/alerts',
    goLabel: 'Open Alerts',
    pages: ['/alerts'],
  },
  {
    id: 'overview',
    title: 'See what needs you now',
    how: 'The Overview ranks today\'s problems. Shift handoff (top right) writes the note the next on-call person would get.',
    go: '/',
    goLabel: 'Open Shift handoff',
    marks: ['handoff'],
    open: 'handoff',
  },
  {
    id: 'pods',
    title: 'Find where checkout\'s slowdown came from',
    how: 'Today\'s checkout-api finding: under "Where the change came from", the pods the deploy started.',
    go: '/findings?service=checkout-api',
    goLabel: 'Open the finding',
    marks: ['finding:checkout-api'],
    finding: { service: 'checkout-api', metric: 'request_latency_p95' },
  },
  {
    id: 'case',
    title: 'Make a case and draft a root cause',
    how: 'On the checkout-api finding, click Create Case. On the case, open the Root Cause tab and click Draft from case.',
    go: '/findings?service=checkout-api',
    goLabel: 'Open the finding',
    marks: ['case-draft'],
    finding: { service: 'checkout-api', metric: 'request_latency_p95' },
  },
  {
    id: 'came-back',
    title: 'See a fix that didn\'t hold',
    how: 'The payments-db connection pool ran out again, 9 days after it was fixed. See "Seen before?" in the finding.',
    go: '/findings?service=payments-db',
    goLabel: 'Open the finding',
    marks: ['finding:payments-db'],
    finding: { service: 'payments-db', metric: 'db_connection_wait_seconds' },
  },
  {
    id: 'recurring',
    title: 'See problems that keep coming back',
    how: 'Recurring problems groups past cases with the same symptom, with each cause and fix.',
    go: '/recurring-problems',
    goLabel: 'Open Recurring problems',
    pages: ['/recurring-problems'],
  },
  {
    id: 'patterns',
    title: 'See metrics that moved together',
    how: 'Behavior Intelligence finds problems made of several metrics: pool exhaustion on payments-db, a cascading failure on search-svc.',
    go: '/behavior-intelligence',
    goLabel: 'Open Behavior Intelligence',
    pages: ['/behavior-intelligence'],
  },
  {
    id: 'found-deploy',
    title: 'Find the deploy nobody announced',
    how: 'search-svc\'s problem started after version 1.9.0, which Ops Signals found in its metrics. No CI sent it. See "What changed" in the finding.',
    go: '/findings?service=search-svc',
    goLabel: 'Open the finding',
    marks: ['finding:search-svc'],
    finding: { service: 'search-svc', metric: 'error_rate' },
  },
  {
    id: 'analysis',
    title: 'Analyze a metric yourself',
    how: 'New Analysis: pick a metric from the demo\'s Prometheus, or try a sample file.',
    go: '/validate-data',
    goLabel: 'Open New Analysis',
    marks: ['analysis'],
  },
  {
    id: 'ask',
    title: 'Ask about past incidents',
    how: 'Ask Ops Signals, for example: "Have we seen payments-db connection pool problems before?"',
    go: '/assistant',
    goLabel: 'Open Ask Ops Signals',
    marks: ['ask'],
  },
];

export function stepDoneBy(step: DemoStep, event: { page?: string; mark?: string }): boolean {
  if (event.mark) return Boolean(step.marks?.includes(event.mark));
  if (event.page) return Boolean(step.pages?.some((page) => event.page === page || event.page?.startsWith(`${page}/`)));
  return false;
}

// Progress lives in the visitor's browser only, for the current demo period: a reset starts over.
const STORAGE_KEY = 'ops-signals.demo.progress';

export type DemoProgress = { period: string; done: string[]; hidden: boolean };

export function loadProgress(period: string): DemoProgress {
  try {
    const saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? 'null') as DemoProgress | null;
    if (saved && saved.period === period && Array.isArray(saved.done)) return saved;
  } catch {
    // Unreadable: start over.
  }
  return { period, done: [], hidden: false };
}

export function saveProgress(progress: DemoProgress): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(progress));
  } catch {
    // Private mode or full storage: progress just isn't kept.
  }
}

/** "Resets in 1 h 12 min"; "Resets in a moment" once it's due. */
export function resetText(resetsAt: string | null | undefined, now = Date.now()): string | null {
  if (!resetsAt) return null;
  const minutes = Math.ceil((new Date(resetsAt).getTime() - now) / 60_000);
  if (!Number.isFinite(minutes)) return null;
  if (minutes <= 0) return 'Resets in a moment';
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return `Resets in ${hours ? `${hours} h ` : ''}${rest || !hours ? `${rest} min` : ''}`.trim();
}

// Pages that would change the site for everyone: view-only in the demo, with the reason shown
// (the backend refuses the requests too).
export const DEMO_TURNED_OFF: { path: string; reason: string }[] = [
  { path: '/integrations', reason: 'Connecting Prometheus, Slack, Jira or an AI provider changes the server for everyone, so it\'s view-only here.' },
  { path: '/autonomous-monitoring', reason: 'Schedules are shared by everyone on this site, so they\'re view-only here.' },
  { path: '/experiments', reason: 'Analyzer labs write files on the server, so they\'re off here.' },
  { path: '/analyzer-router', reason: 'Analyzer settings are shared by everyone on this site, so they\'re view-only here.' },
  { path: '/settings', reason: 'Settings are shared by everyone on this site, so they\'re view-only here.' },
  { path: '/setup-check', reason: 'Set-up details are off in the demo.' },
  { path: '/capabilities', reason: 'Set-up details are off in the demo.' },
];

export function turnedOffReason(pathname: string): string | null {
  return DEMO_TURNED_OFF.find((entry) => pathname === entry.path || pathname.startsWith(`${entry.path}/`))?.reason ?? null;
}

/** Fired by the guide to open Shift handoff on the Overview (ShiftHandoffButton listens). */
export const OPEN_HANDOFF_EVENT = 'ops-signals:demo-open-handoff';

/** Where a step's button goes: today's finding for its service when it names one (the Findings page
 * opens ?finding=<id>), else its page. */
export async function stepTarget(step: DemoStep, findings: () => Promise<{ id?: number | null; service?: string; metric_name?: string; health_status?: string }[]>): Promise<string> {
  if (!step.finding) return step.go;
  try {
    const rows = (await findings()).filter((row) => typeof row.id === 'number' && row.health_status !== 'normal');
    const match = rows.find((row) => row.metric_name === step.finding?.metric) ?? rows[0];
    return match ? `${step.go}&finding=${match.id}` : step.go;
  } catch {
    return step.go;
  }
}
