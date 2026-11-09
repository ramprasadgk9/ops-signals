import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Chip } from '@mui/material';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/queries';
import type { DemoInfo } from '../types';
import { AiLabel } from './AiLabel';
import { DemoBanner } from './DemoBanner';
import { DemoTurnedOff } from './DemoTurnedOff';
import { ThingsToTry } from './ThingsToTry';
import { DEMO_STEPS, demoSteps, loadProgress, resetText, stepDoneBy, turnedOffReason } from './demo';
import { markDemoStep } from './events';

vi.mock('../api/queries', () => ({ api: { demo: vi.fn(), findings: vi.fn(), createCase: vi.fn(), aiStatus: vi.fn() } }));

const DEMO: DemoInfo = {
  enabled: true,
  resets_at: '2026-10-30T12:00:00Z',
  reset_hours: 2,
  run_yourself_url: 'https://example.test/run',
  ai: 'recorded',
  ai_model: 'gemma3:4b',
  samples: [],
};

function Where() {
  return <span data-testid="where">{useLocation().pathname + useLocation().search}</span>;
}

function renderWith(ui: React.ReactNode, path = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes><Route path="*" element={<>{ui}<Where /></>} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function memoryStorage(): Storage {
  const items = new Map<string, string>();
  return {
    get length() { return items.size; },
    clear: () => items.clear(),
    getItem: (key: string) => items.get(key) ?? null,
    key: (index: number) => [...items.keys()][index] ?? null,
    removeItem: (key: string) => { items.delete(key); },
    setItem: (key: string, value: string) => { items.set(key, value); },
  };
}

beforeEach(() => {
  vi.stubGlobal('localStorage', memoryStorage());
  vi.mocked(api.demo).mockResolvedValue(DEMO);
  vi.mocked(api.findings).mockResolvedValue([
    { id: 41, service: 'checkout-api', metric_name: 'http_requests_per_second', health_status: 'normal' },
    { id: 42, service: 'checkout-api', metric_name: 'request_latency_p95', health_status: 'significant' },
  ] as never);
  vi.mocked(api.createCase).mockResolvedValue({ case_id: 7 } as never);
  vi.mocked(api.aiStatus).mockResolvedValue({ active: false } as never);
});

describe('demo helpers', () => {
  it('ticks a step off by its page or its mark', () => {
    const [alert, overview] = DEMO_STEPS;
    expect(stepDoneBy(alert, { page: '/alerts' })).toBe(true);
    expect(stepDoneBy(alert, { page: '/alerts/42' })).toBe(true);
    expect(stepDoneBy(alert, { page: '/alerts-old' })).toBe(false);
    expect(stepDoneBy(overview, { mark: 'handoff' })).toBe(true);
    expect(stepDoneBy(overview, { page: '/' })).toBe(false);
  });

  it('asks only for what this site can do: no AI step without AI', () => {
    const caseWith = demoSteps(true).find((step) => step.id === 'case')!;
    const caseWithout = demoSteps(false).find((step) => step.id === 'case')!;
    expect(caseWith.title).toBe('Make a case and draft a root cause');
    expect(stepDoneBy(caseWith, { mark: 'case-draft' })).toBe(true);
    expect(caseWithout.title).toBe('Make a case');
    expect(caseWithout.how).not.toMatch(/Draft from case/);
    expect(stepDoneBy(caseWithout, { mark: 'case-created' })).toBe(true);
    expect(stepDoneBy(caseWithout, { mark: 'case-draft' })).toBe(false);
    // Investigate needs AI and has nothing to do without it, so it's left out; every other step is
    // the same either way, in the same order.
    expect(demoSteps(true).map((step) => step.id)).toEqual(DEMO_STEPS.map((step) => step.id));
    expect(demoSteps(true)).toHaveLength(11);
    expect(demoSteps(false).map((step) => step.id)).toEqual(DEMO_STEPS.filter((step) => step.id !== 'investigate').map((step) => step.id));
    expect(demoSteps(false).filter((step) => step.id !== 'case')).toEqual(DEMO_STEPS.filter((step) => step.id !== 'case' && step.id !== 'investigate'));
  });

  it('says when the site resets', () => {
    const now = Date.parse('2026-10-30T10:48:00Z');
    expect(resetText('2026-10-30T12:00:00Z', now)).toBe('Resets in 1 h 12 min');
    expect(resetText('2026-10-30T12:00:00Z', Date.parse('2026-10-30T11:00:00Z'))).toBe('Resets in 1 h');
    expect(resetText('2026-10-30T12:00:00Z', Date.parse('2026-10-30T11:51:30Z'))).toBe('Resets in 9 min');
    expect(resetText('2026-10-30T12:00:00Z', Date.parse('2026-10-30T12:01:00Z'))).toBe('Resets in a moment');
    expect(resetText(null)).toBeNull();
  });

  it('knows which pages are view-only', () => {
    expect(turnedOffReason('/integrations')).toMatch(/view-only/);
    expect(turnedOffReason('/experiments/pyod-outlier-lab')).toMatch(/off here/);
    expect(turnedOffReason('/findings')).toBeNull();
  });

  it('starts over after a reset', () => {
    window.localStorage.setItem('ops-signals.demo.progress', JSON.stringify({ period: 'before', done: ['alert'], hidden: true }));
    expect(loadProgress('before').done).toEqual(['alert']);
    expect(loadProgress('after')).toEqual({ period: 'after', done: [], hidden: false });
  });
});

describe('Things to try', () => {
  it('shows nothing outside demo mode', async () => {
    vi.mocked(api.demo).mockResolvedValue({ ...DEMO, enabled: false, tour: false });
    renderWith(<><ThingsToTry /><DemoBanner /></>);
    await waitFor(() => expect(api.demo).toHaveBeenCalled());
    expect(screen.queryByTestId('demo-guide')).toBeNull();
    expect(screen.queryByTestId('demo-banner')).toBeNull();
  });

  it('shows on its own with the tour on, without the demo banner or view-only notices', async () => {
    vi.mocked(api.demo).mockResolvedValue({ ...DEMO, enabled: false, tour: true, resets_at: null });
    renderWith(<><ThingsToTry /><DemoBanner /><DemoTurnedOff /></>, '/integrations');
    expect(await screen.findByTestId('demo-guide')).toHaveTextContent('Things to try');
    expect(screen.queryByTestId('demo-banner')).toBeNull();
    expect(screen.queryByTestId('demo-turned-off')).toBeNull();
  });

  it('ticks off the page you open and the thing you do, and takes you to the next step', async () => {
    renderWith(<ThingsToTry />, '/alerts');
    expect(await screen.findByTestId('demo-guide')).toHaveTextContent('1 of 10');
    expect(screen.getByTestId('demo-step-alert')).toHaveAttribute('data-done', 'true');

    act(() => markDemoStep('handoff'));
    expect(screen.getByTestId('demo-guide')).toHaveTextContent('2 of 10');

    // The button opens today's finding itself, where the step happens, not just the list.
    fireEvent.click(screen.getByRole('button', { name: 'Open the finding' }));
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/findings?service=checkout-api&finding=42'));
    expect(api.findings).toHaveBeenCalledWith('checkout-api');
    act(() => markDemoStep('finding:checkout-api'));
    expect(screen.getByTestId('demo-step-pods')).toHaveAttribute('data-done', 'true');

    // Step 4 creates the case itself and opens it on Root Cause. With AI off (the plain demo) there is
    // no Draft from case, so making the case is the step (the API client marks it once it exists).
    expect(screen.getByTestId('demo-step-case')).toHaveTextContent('Make a case');
    expect(screen.getByTestId('demo-step-case')).not.toHaveTextContent('draft a root cause');
    fireEvent.click(screen.getByRole('button', { name: 'Create the case' }));
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/cases/7?tab=root-cause'));
    expect(api.createCase).toHaveBeenCalledWith(42);
    act(() => markDemoStep('case-created'));
    expect(screen.getByTestId('demo-step-case')).toHaveAttribute('data-done', 'true');
    expect(screen.getByTestId('demo-guide')).toHaveTextContent('4 of 10');
    expect(JSON.parse(window.localStorage.getItem('ops-signals.demo.progress') ?? '{}').done).toEqual(['alert', 'overview', 'pods', 'case']);
    // The next step's button shows, so the guide doesn't stick on step 4.
    expect(screen.getByRole('button', { name: 'Open the finding' })).toBeInTheDocument();
  });

  it('with AI on, step 4 asks for a drafted root cause and only Draft from case ticks it', async () => {
    vi.mocked(api.aiStatus).mockResolvedValue({ active: true } as never);
    window.localStorage.setItem('ops-signals.demo.progress', JSON.stringify({ period: DEMO.resets_at, done: ['alert', 'overview', 'pods'], hidden: false }));
    renderWith(<ThingsToTry />);
    await waitFor(() => expect(screen.getByTestId('demo-step-case')).toHaveTextContent('Make a case and draft a root cause'));

    act(() => markDemoStep('case-created'));
    expect(screen.getByTestId('demo-step-case')).not.toHaveAttribute('data-done');
    act(() => markDemoStep('case-draft'));
    expect(screen.getByTestId('demo-step-case')).toHaveAttribute('data-done', 'true');
  });

  it('with AI on, Investigate follows the pods step: it opens the finding and starting one ticks it', async () => {
    vi.mocked(api.aiStatus).mockResolvedValue({ active: true } as never);
    window.localStorage.setItem('ops-signals.demo.progress', JSON.stringify({ period: DEMO.resets_at, done: ['alert', 'overview', 'pods'], hidden: false }));
    renderWith(<ThingsToTry />);
    await waitFor(() => expect(screen.getByTestId('demo-guide')).toHaveTextContent('3 of 11'));
    expect(screen.getByTestId('demo-step-investigate')).toHaveTextContent('click Investigate');

    fireEvent.click(screen.getByRole('button', { name: 'Open the finding' }));
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/findings?service=checkout-api&finding=42'));
    // Opening the finding isn't the step; starting the investigation is.
    act(() => markDemoStep('finding:checkout-api'));
    expect(screen.getByTestId('demo-step-investigate')).not.toHaveAttribute('data-done');
    act(() => markDemoStep('investigate'));
    expect(screen.getByTestId('demo-step-investigate')).toHaveAttribute('data-done', 'true');
    expect(screen.getByTestId('demo-guide')).toHaveTextContent('4 of 11');
  });

  it('with AI off, there is no Investigate step', async () => {
    renderWith(<ThingsToTry />);
    expect(await screen.findByTestId('demo-guide')).toHaveTextContent('0 of 10');
    expect(screen.queryByTestId('demo-step-investigate')).toBeNull();
  });

  it('hides to one button that keeps the count, and the banner opens it again', async () => {
    renderWith(<><DemoBanner /><ThingsToTry /></>, '/alerts');
    fireEvent.click(await screen.findByRole('button', { name: 'Hide' }));
    expect(screen.getByTestId('demo-guide-pill')).toHaveTextContent('Things to try · 1 of 10');

    fireEvent.click(screen.getByRole('button', { name: 'Things to try' }));
    expect(screen.getByTestId('demo-guide')).toBeInTheDocument();
  });
});

describe('demo banner, notices and recorded AI', () => {
  it('says it is a demo and links to running it yourself', async () => {
    renderWith(<DemoBanner />);
    expect(await screen.findByTestId('demo-banner')).toHaveTextContent('Nothing here is real');
    expect(screen.getByRole('link', { name: /Run it yourself/ })).toHaveAttribute('href', 'https://example.test/run');
  });

  it('marks a view-only page with the reason', async () => {
    renderWith(<DemoTurnedOff />, '/integrations');
    expect(await screen.findByTestId('demo-turned-off')).toHaveTextContent('Turned off in the demo.');
  });

  it('labels AI text as a recorded example, and leaves it alone elsewhere', async () => {
    renderWith(<AiLabel suffix=" · not saved"><Chip label="AI draft · not saved" /></AiLabel>);
    expect(await screen.findByTestId('ai-recorded')).toHaveTextContent('Recorded example · not saved');

    vi.mocked(api.demo).mockResolvedValue({ ...DEMO, ai: 'live' });
    renderWith(<AiLabel><Chip label="AI" data-testid="plain-ai" /></AiLabel>);
    expect(await screen.findByTestId('plain-ai')).toHaveTextContent('AI');
  });
});

describe('a step that opens something on its page', () => {
  it('goes to the Overview and asks Shift handoff to open', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const opened = vi.fn();
    window.addEventListener('ops-signals:demo-open-handoff', opened);
    renderWith(<ThingsToTry />, '/alerts');
    fireEvent.click(await screen.findByRole('button', { name: 'Open Shift handoff' }));
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent(/^\/$/));
    await act(async () => { vi.advanceTimersByTime(400); });
    expect(opened).toHaveBeenCalled();
    window.removeEventListener('ops-signals:demo-open-handoff', opened);
    vi.useRealTimers();
  });
});

describe('the guide and panels', () => {
  it('shrinks to its button while a finding\'s details or a dialog is open', async () => {
    renderWith(<ThingsToTry />, '/alerts');
    expect(await screen.findByTestId('demo-guide')).toBeInTheDocument();

    const panel = document.createElement('div');
    panel.className = 'MuiDrawer-root MuiDrawer-modal';
    act(() => { document.body.appendChild(panel); });
    expect(await screen.findByTestId('demo-guide-pill')).toHaveTextContent('1 of 10');

    act(() => { panel.remove(); });
    expect(await screen.findByTestId('demo-guide')).toBeInTheDocument();
  });
});
