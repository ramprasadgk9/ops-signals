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
    how: 'The Overview ranks today\'s problems. Open Shift handoff for the note the next on-call person would get.',
    go: '/',
    goLabel: 'Open Overview',
    marks: ['handoff'],
  },
  {
    id: 'pods',
    title: 'Find where checkout\'s slowdown came from',
    how: 'Open the checkout-api finding. The pods chip says which pods the change came from: the ones the deploy started.',
    go: '/findings?service=checkout-api',
    goLabel: 'Go to the finding',
    marks: ['finding:checkout-api'],
  },
  {
    id: 'case',
    title: 'Make a case and draft a root cause',
    how: 'Create a case from the checkout-api finding, then click Draft from case on its Root Cause tab.',
    go: '/findings?service=checkout-api',
    goLabel: 'Go to the finding',
    marks: ['case-draft'],
  },
  {
    id: 'came-back',
    title: 'See a fix that didn\'t hold',
    how: 'Open the payments-db finding: the connection pool ran out again, 9 days after it was fixed.',
    go: '/findings?service=payments-db',
    goLabel: 'Go to the finding',
    marks: ['finding:payments-db'],
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
    how: 'Open a search-svc finding: it started after version 1.9.0, which Ops Signals found in the metrics. No CI sent it.',
    go: '/findings?service=search-svc',
    goLabel: 'Go to the finding',
    marks: ['finding:search-svc'],
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
