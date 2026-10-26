import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SetupCheckPage } from './SetupCheckPage';
import { api } from '../api/queries';
import { ApiError } from '../api/client';
import type { SetupCheckResult } from '../utils/setupCheck';

vi.mock('../api/queries', () => ({
  api: {
    setupCheck: vi.fn(),
    testPrometheusConnection: vi.fn(),
    sendTestAlert: vi.fn(),
  },
}));

const RESULT: SetupCheckResult = {
  generated_at: '2026-10-19T14:02:31Z',
  version: '0.5.0',
  checks: [
    { id: 'backend', group: 'required', status: 'ok', title: 'Backend', detail: 'Answering · version 0.5.0' },
    {
      id: 'connection:mimir-eu',
      group: 'required',
      status: 'fail',
      title: 'Metrics: mimir-eu',
      detail: 'Login rejected (401). The token for this connection is missing or wrong.',
      tried: 'GET https://mimir-eu.internal/prometheus/api/v1/status/buildinfo\n-> 401 unauthorized',
      cause: 'The connection has no token.',
      fix: ['Get a read-only token.', 'Restart the backend, then check again.'],
      snippet: '- id: mimir-eu\n  bearer_token: ${MIMIR_EU_TOKEN}',
      docs: 'docs/standalone-prometheus-analysis.md',
      action: 'test_connection',
      connection_id: 'mimir-eu',
    },
    { id: 'first_analysis', group: 'recommended', status: 'warn', title: 'First analysis', detail: 'Nothing analyzed yet.', action: 'run_analysis' },
    { id: 'alerts', group: 'optional', status: 'off', title: 'Alerts receiver', detail: 'Off.', docs: 'docs/alert-enrichment.md' },
    {
      id: 'analyzer_overrides', group: 'optional', status: 'warn', title: 'Per-service analyzer settings',
      detail: '1 override in 1 file in use · 1 file skipped', action: 'how_to_set', docs: 'docs/configuration.md',
      fix: ['checkout-team.yml skipped: a value is out of range. Its services run on the default settings.', 'Copy the example file.'],
      snippet: 'overrides:\n  payments_memory_trend: {}',
    },
  ],
};

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/setup-check']}>
        <Routes>
          <Route path="/setup-check" element={<SetupCheckPage />} />
          <Route path="/validate-data" element={<p>New Analysis page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('SetupCheckPage', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('groups the checks and sums them up', async () => {
    vi.mocked(api.setupCheck).mockResolvedValue(RESULT);
    renderPage();

    const needed = await screen.findByRole('region', { name: 'Needed to start' });
    expect(within(needed).getByText('Backend')).toBeInTheDocument();
    expect(within(needed).getByText('Metrics: mimir-eu')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Optional' })).getByText('Alerts receiver')).toBeInTheDocument();
    expect(screen.getByText('1 of 2')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Needs fixing' })).toBeInTheDocument();
  });

  it('opens what was tried, the cause and the fix', async () => {
    vi.mocked(api.setupCheck).mockResolvedValue(RESULT);
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: 'How to fix: Metrics: mimir-eu' }));
    expect(screen.getByText(/-> 401 unauthorized/)).toBeInTheDocument();
    expect(screen.getByText('The connection has no token.')).toBeInTheDocument();
    expect(screen.getByText('Get a read-only token.')).toBeInTheDocument();
    expect(screen.getByText(/bearer_token: \$\{MIMIR_EU_TOKEN\}/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'standalone-prometheus-analysis.md' })).toHaveAttribute(
      'href',
      'https://github.com/ramprasadgk9/ops-signals/blob/main/docs/standalone-prometheus-analysis.md'
    );
  });

  it("tests one connection again from its row", async () => {
    vi.mocked(api.setupCheck).mockResolvedValue(RESULT);
    vi.mocked(api.testPrometheusConnection).mockResolvedValue({ available: true, latency_ms: 42, message: 'Connection successful' });
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: 'Test Metrics: mimir-eu' }));
    expect(await screen.findByText('Connected in 42 ms')).toBeInTheDocument();
    expect(api.testPrometheusConnection).toHaveBeenCalledWith('mimir-eu');
  });

  it('takes "Run first analysis" to New Analysis', async () => {
    vi.mocked(api.setupCheck).mockResolvedValue(RESULT);
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: 'Run first analysis' }));
    expect(await screen.findByText('New Analysis page')).toBeInTheDocument();
  });

  it('links an optional check with no steps to its guide', async () => {
    vi.mocked(api.setupCheck).mockResolvedValue(RESULT);
    renderPage();

    expect(await screen.findByRole('link', { name: 'Guide' })).toHaveAttribute('href', 'https://github.com/ramprasadgk9/ops-signals/blob/main/docs/alert-enrichment.md');
  });

  it('shows a failed Backend check when the check itself fails', async () => {
    vi.mocked(api.setupCheck).mockRejectedValue(new ApiError(502, 'Bad Gateway'));
    renderPage();

    expect(await screen.findByText('The backend answered with an error (502).')).toBeInTheDocument();
    expect(screen.getByText('0 of 1')).toBeInTheDocument();
  });

  it('copies a plain-text report', async () => {
    vi.mocked(api.setupCheck).mockResolvedValue(RESULT);
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    renderPage();

    await screen.findByRole('region', { name: 'Needed to start' });
    fireEvent.click(screen.getByRole('button', { name: 'Copy report' }));
    expect(await screen.findByText(/^Copied\./)).toBeInTheDocument();
    expect(writeText.mock.calls[0][0]).toContain('[FAIL] Metrics: mimir-eu: Login rejected (401).');
  });
});

describe('SetupCheckPage per-service analyzer settings', () => {
  afterEach(() => vi.clearAllMocks());

  it('opens "How to set" with what was skipped, the steps and the example file', async () => {
    vi.mocked(api.setupCheck).mockResolvedValue(RESULT);
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: 'How to set: Per-service analyzer settings' }));

    expect(screen.getByText('checkout-team.yml skipped: a value is out of range. Its services run on the default settings.')).toBeInTheDocument();
    expect(screen.getByText('Copy the example file.')).toBeInTheDocument();
    expect(screen.getByText(/payments_memory_trend/)).toBeInTheDocument();
  });
});
