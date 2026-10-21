import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/queries';
import type { BehaviorDefinitionDraft, HistoryPreview as Result, HistoryRun } from '../types';
import { HistoryPreview, runReason, withGaps } from './HistoryPreview';

vi.mock('../api/queries', () => ({
  api: {
    behaviorHistoryServices: vi.fn().mockResolvedValue(['checkout-api', 'payments']),
    behaviorHistoryPreview: vi.fn(),
  },
}));

const draft = {
  id: 'pool',
  title: 'Pool',
  inputs: [
    { alias: 'db_wait', metric_name: 'db_connection_wait_seconds', analyzers: [] },
    { alias: 'db_pool', metric_name: 'db_connections_active', analyzers: [] },
  ],
} as unknown as BehaviorDefinitionDraft;

const run = (overrides: Partial<HistoryRun>): HistoryRun => ({
  analysis_run_id: 'run-new-0123456789', at: '2026-10-21T14:00:00Z', matched: false, missing_inputs: [], blocked_by: [],
  conditions: [], confidence: null, changes: [], overlap_minutes: null, start: null, end: null, ...overrides,
});

const result = (overrides: Partial<Result>): Result => ({
  service: 'checkout-api', since: '2026-10-14T14:00:00Z', verdict: 'fired', reason: null,
  runs_checked: 3, runs_judged: 1, runs_matched: 1,
  conditions: [{ group: 'all', fact: 'db_wait.change.upward', operator: 'equals', value: true, passed_runs: 1 }],
  inputs: [
    { alias: 'db_wait', metric_name: 'db_connection_wait_seconds', analyzers: ['trend'], runs_with_signals: 2 },
    { alias: 'db_pool', metric_name: 'db_connections_active', analyzers: ['trend'], runs_with_signals: 1 },
  ],
  runs: [
    run({
      matched: true, start: '2026-10-21T12:00:00Z', end: '2026-10-21T14:00:00Z', confidence: 1, overlap_minutes: 120,
      changes: [{ alias: 'db_wait', signed_change_percent: 312.4 }, { alias: 'db_pool', signed_change_percent: 40 }],
      conditions: [
        { group: 'all', fact: 'db_wait.change.upward', operator: 'equals', value: true, passed: true, actual: true },
        { group: 'all', fact: 'db_pool.change.signed_change_percent', operator: 'greater_than', value: 30, passed: true, actual: 40 },
      ],
    }),
    run({ analysis_run_id: 'run-mid', missing_inputs: ['db_pool'] }),
    run({ analysis_run_id: 'run-old', blocked_by: ['timing: the metrics did not change at the same time'] }),
  ],
  series: [{ alias: 'db_wait', metric_name: 'db_connection_wait_seconds', points: [] }],
  series_truncated: false,
  ...overrides,
});

function renderPreview(blockedReason: string | null = null) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <HistoryPreview draft={draft} blockedReason={blockedReason} />
    </QueryClientProvider>
  );
}

async function runFor(service: string) {
  const field = screen.getByRole('combobox', { name: 'Service' });
  fireEvent.change(field, { target: { value: service.slice(0, 3) } });
  fireEvent.click(await screen.findByRole('option', { name: service }));
  fireEvent.click(screen.getByRole('button', { name: 'See it on my data' }));
}

describe('HistoryPreview', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('says how often it would have fired, and why each run did or did not match', async () => {
    vi.mocked(api.behaviorHistoryPreview).mockResolvedValue(result({}));
    renderPreview();

    await runFor('checkout-api');

    expect(await screen.findByText(/Would have fired in 1 of 3 runs of checkout-api/)).toBeInTheDocument();
    expect(api.behaviorHistoryPreview).toHaveBeenCalledWith(draft, 'checkout-api', 168);
    expect(screen.getByText(/signals in 1 of 3 runs/)).toBeInTheDocument();
    expect(screen.getByText(/passed in 1 of 1 runs it could be checked in/)).toBeInTheDocument();
    const rows = within(screen.getByRole('table', { name: 'Runs checked' })).getAllByRole('row').slice(1);
    expect(rows.map((row) => within(row).getAllByRole('cell')[3].textContent)).toEqual([
      'Matched',
      'No signal for db_pool: no change, or its analyzers did not run',
      'timing: the metrics did not change at the same time',
    ]);
    expect(screen.getByText('No stored points for this metric on checkout-api in the look-back.')).toBeInTheDocument();
  });

  it('names the most common reason when it never matched', async () => {
    vi.mocked(api.behaviorHistoryPreview).mockResolvedValue(result({ verdict: 'never', runs_matched: 0, reason: 'none of: db_pool.change.upward equals True' }));
    renderPreview();
    await runFor('checkout-api');
    expect(await screen.findByText('none of: db_pool.change.upward equals True')).toBeInTheDocument();
    expect(screen.getByText(/Never matched in 3 runs of checkout-api/)).toBeInTheDocument();
  });

  it('explains a pattern that cannot be checked yet', async () => {
    vi.mocked(api.behaviorHistoryPreview).mockResolvedValue(result({ verdict: 'cant_check', runs_judged: 0, runs_matched: 0, reason: 'no signals for db_pool' }));
    renderPreview();
    await runFor('checkout-api');
    expect(await screen.findByText(/Can't tell yet: no signals for db_pool in any run/)).toBeInTheDocument();
  });

  it('says when the service had no runs', async () => {
    vi.mocked(api.behaviorHistoryPreview).mockResolvedValue(result({ verdict: 'no_runs', runs_checked: 0, runs_judged: 0, runs_matched: 0, runs: [], series: [] }));
    renderPreview();
    await runFor('payments');
    expect(await screen.findByText('No analysis runs of checkout-api in the last 7 days.')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('takes a service that is not in the list', async () => {
    vi.mocked(api.behaviorHistoryPreview).mockResolvedValue(result({}));
    renderPreview();
    fireEvent.change(screen.getByRole('combobox', { name: 'Service' }), { target: { value: 'billing-worker' } });
    fireEvent.click(screen.getByRole('button', { name: 'See it on my data' }));
    await screen.findByText(/Would have fired/);
    expect(api.behaviorHistoryPreview).toHaveBeenCalledWith(draft, 'billing-worker', 168);
  });

  it('waits for every signal to point at a metric', () => {
    renderPreview('Pick your metric for Consumer lag rising first (step 2).');
    const button = screen.getByRole('button', { name: 'See it on my data' });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('title', 'Pick your metric for Consumer lag rising first (step 2).');
  });
});

describe('HistoryPreview services and run details', () => {
  afterEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.behaviorHistoryServices).mockResolvedValue(['checkout-api', 'payments']);
  });

  it('suggests only the services where the pattern\'s metrics changed', async () => {
    renderPreview();
    await screen.findByText(/the 2 services where these metrics changed/);
    expect(api.behaviorHistoryServices).toHaveBeenCalledWith(['db_connection_wait_seconds', 'db_connections_active']);
  });

  it('fills in the service when only one fits', async () => {
    vi.mocked(api.behaviorHistoryServices).mockResolvedValue(['checkout-api']);
    renderPreview();
    await vi.waitFor(() => expect(screen.getByRole('combobox', { name: 'Service' })).toHaveValue('checkout-api'));
    expect(screen.getByRole('button', { name: 'See it on my data' })).toBeEnabled();
  });

  it('says so when the metrics changed nowhere', async () => {
    vi.mocked(api.behaviorHistoryServices).mockResolvedValue([]);
    renderPreview();
    expect(await screen.findByText(/did not change on any service in the last 30 days/)).toBeInTheDocument();
  });

  it('opens a run to show what changed, each condition and how sure', async () => {
    vi.mocked(api.behaviorHistoryPreview).mockResolvedValue(result({}));
    renderPreview();
    await runFor('checkout-api');
    await screen.findByText(/Would have fired/);

    const toggle = screen.getAllByRole('button', { name: /^Details for run/ })[0];
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('db_wait went up 312% · db_pool went up 40%')).toBeInTheDocument();
    expect(screen.getByText('✓ db_wait is rising')).toBeInTheDocument();
    expect(screen.getByText('✓ db_pool went up by more than 30% (was 40)')).toBeInTheDocument();
    expect(screen.getByText('Changed at the same time for 120 minutes.')).toBeInTheDocument();
    expect(screen.getByText('Confidence: 100%')).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole('button', { name: /^Details for run/ })[1]);
    expect(screen.getByText(/Nothing to check in this run: no signal for db_pool/)).toBeInTheDocument();
    expect(screen.queryByText('Confidence: 100%')).not.toBeInTheDocument();
  });
});

describe('runReason', () => {
  it('prefers the missing inputs, then the first blocker', () => {
    expect(runReason(run({ missing_inputs: ['a', 'b'], blocked_by: ['x'] }))).toBe('No signal for a, b: no change, or its analyzers did not run');
    expect(runReason(run({ blocked_by: ['x', 'y'] }))).toBe('x');
  });
});

describe('withGaps', () => {
  it('breaks the line where no data was stored', () => {
    const since = Date.parse('2026-10-21T00:00:00Z');
    const until = since + 240 * 60_000; // one-minute slices
    const rows = withGaps([['2026-10-21T00:00:00Z', 1], ['2026-10-21T00:01:00Z', 2], ['2026-10-21T00:10:00Z', 3]], since, until);
    expect(rows.map((row) => row.value)).toEqual([1, 2, null, 3]);
  });
});
