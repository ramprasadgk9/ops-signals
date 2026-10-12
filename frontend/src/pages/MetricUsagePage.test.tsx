import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { MetricUsagePage } from './MetricUsagePage';
import { api } from '../api/queries';
import type { IngestionStatus, MetricUsageItem, MetricUsageResponse, MetricUsageSnapshot } from '../types';

vi.mock('../api/queries', () => ({
  api: { metricUsage: vi.fn(), metricUsageHistory: vi.fn(), grafanaStatus: vi.fn(), runMetricUsageCheck: vi.fn(), createCase: vi.fn(), ingestionStatus: vi.fn() },
}));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter><MetricUsagePage /></MemoryRouter>
    </QueryClientProvider>
  );
}

const item = (metric: string, overrides: Partial<MetricUsageItem> = {}): MetricUsageItem => ({
  metric, status: 'watched', connections: ['default'], usages: [], via_recording_rules: [],
  problem_findings: 0, latest_finding_id: null, analyzed: true, series: null, ...overrides,
});

const snapshot = (overrides: Partial<MetricUsageSnapshot> = {}): MetricUsageSnapshot => ({
  id: 'snap-1', trigger: 'schedule', status: 'completed', created_at: new Date().toISOString(), duration_ms: 60, error: null,
  metrics_total: 299, watched: 8, blind_spots: 1, unwatched: 284, missing: 0, watched_percent: 2.7,
  series_total: 728, series_unwatched: 600,
  sources: {
    grafana: { configured: true, dashboards_read: 2, dashboards_excluded: ['Scratch / Old test board'], alert_rules_read: 2 },
    prometheus: [{ id: 'default', name: 'Default Prometheus', metrics: 299, rule_groups: 0 }],
    unresolved_queries: [], warnings: [],
  },
  ...overrides,
});

const response = (overrides: Partial<MetricUsageResponse> = {}): MetricUsageResponse => ({
  enabled: true, interval_hours: 6, grafana_configured: true, snapshot: snapshot(), last_failure: null,
  items: [
    item('demo_request_latency_ms', { status: 'blind_spot', problem_findings: 26, latest_finding_id: 4101, series: 1200 }),
    item('error_rate', {
      problem_findings: 42,
      usages: [
        { kind: 'dashboard', location: 'Production / API Health / Error rate' },
        { kind: 'alert_rule', location: 'Production / Checkout error rate high' },
      ],
    }),
  ],
  items_total: 2,
  cost: null,
  ...overrides,
});

describe('MetricUsagePage', () => {
  afterEach(() => vi.clearAllMocks());
  beforeEach(() => vi.mocked(api.metricUsageHistory).mockResolvedValue([]));

  it('shows the totals, the blind spot first with actions, and where watched metrics are watched', async () => {
    vi.mocked(api.metricUsage).mockResolvedValue(response());
    vi.mocked(api.grafanaStatus).mockResolvedValue({ configured: true, url: 'http://localhost:3000', reachable: true, version: '13.1.0', message: 'Connected' });
    renderPage();

    const tiles = await screen.findByTestId('metric-usage-tiles');
    expect(within(tiles).getByText('299')).toBeInTheDocument();
    expect(within(tiles).getByText('2.7% on a dashboard or alert')).toBeInTheDocument();

    const blind = within(screen.getByTestId('metric-usage-section-blind_spot'));
    expect(blind.getByText('demo_request_latency_ms')).toBeInTheDocument();
    expect(blind.getByText('No dashboard · no alert')).toBeInTheDocument();
    expect(blind.getByText('26 problems · 24h')).toBeInTheDocument();
    expect(blind.getByRole('link', { name: 'View finding' })).toHaveAttribute('href', '/findings?finding=4101');
    expect(blind.getByRole('button', { name: 'Create case' })).toBeInTheDocument();
    expect(blind.getByText('1,200 series')).toBeInTheDocument();
    expect(screen.getByTestId('metric-usage-value')).toHaveTextContent('26 problemsnobody would have seen');

    const watched = within(screen.getByTestId('metric-usage-section-watched'));
    expect(watched.getByText('Production / API Health / Error rate')).toBeInTheDocument();
    expect(watched.getByText('Alert: Checkout error rate high')).toBeInTheDocument();
    expect(watched.queryByRole('button', { name: 'Create case' })).toBeNull();

    expect(await screen.findByText(/Grafana connected/)).toBeInTheDocument();
    expect(screen.getByText(/2 dashboards and 2 alert rules read · 1 skipped/)).toBeInTheDocument();
    // The missing section only appears when something is missing.
    expect(screen.queryByTestId('metric-usage-section-missing')).toBeNull();
  });

  it('opens a row to explain it', async () => {
    vi.mocked(api.metricUsage).mockResolvedValue(response());
    vi.mocked(api.grafanaStatus).mockResolvedValue({ configured: true, url: 'http://localhost:3000', reachable: true, message: 'Connected' });
    renderPage();

    fireEvent.click(await screen.findByText('demo_request_latency_ms'));
    const details = await screen.findByTestId('metric-usage-details');
    expect(details).toHaveTextContent('26 problem findings in the last 24h, and nothing shows this metric');
    expect(details).toHaveTextContent('Analyzed by Ops Signals in the last 7 days');
  });

  it('says where a missing metric is when its panels read another connection', async () => {
    vi.mocked(api.metricUsage).mockResolvedValue(response({
      snapshot: snapshot({ missing: 1 }),
      items: [item('checkout_latency', { status: 'missing', connections: ['team-a'], usages: [{ kind: 'dashboard', location: 'Team B / Checkout / Latency' }] })],
    }));
    vi.mocked(api.grafanaStatus).mockResolvedValue({ configured: true, url: null, reachable: true, message: 'Connected' });
    renderPage();

    fireEvent.click(await screen.findByText('checkout_latency'));
    expect(await screen.findByTestId('metric-usage-details')).toHaveTextContent('Only in team-a, not in what its panels and alerts read');
  });

  it('loads the unwatched metrics only when that section is opened', async () => {
    vi.mocked(api.metricUsage)
      .mockResolvedValueOnce(response())
      .mockResolvedValueOnce(response({ items: [item('go_goroutines', { status: 'unwatched' })], items_total: 284 }));
    vi.mocked(api.grafanaStatus).mockResolvedValue({ configured: true, url: null, reachable: true, message: 'Connected' });
    renderPage();

    const section = await screen.findByTestId('metric-usage-section-unwatched');
    expect(api.metricUsage).toHaveBeenCalledTimes(1);
    fireEvent.click(within(section).getByRole('button', { name: /Not watched, no problems/ }));
    expect(await within(section).findByText('go_goroutines')).toBeInTheDocument();
    expect(api.metricUsage).toHaveBeenLastCalledWith(['unwatched'], 200);
    expect(within(section).getByText(/Showing the first 1 of 284/)).toBeInTheDocument();
  });

  it('warns about a failed check while still showing the last good one', async () => {
    vi.mocked(api.metricUsage).mockResolvedValue(response({
      last_failure: snapshot({ id: 'snap-2', status: 'failed', error: 'Grafana refused /api/search (401): check the token\'s role' }),
    }));
    vi.mocked(api.grafanaStatus).mockResolvedValue({ configured: true, url: 'http://localhost:3000', reachable: false, message: 'Grafana refused /api/health (401)' });
    renderPage();

    expect(await screen.findByTestId('metric-usage-failure')).toHaveTextContent('failed: Grafana refused /api/search (401)');
    expect(screen.getByTestId('metric-usage-failure')).toHaveTextContent('Showing the last good check.');
    expect(screen.getByText(/Grafana unreachable/)).toBeInTheDocument();
  });

  it('explains how to connect Grafana and that no check ran yet', async () => {
    vi.mocked(api.metricUsage).mockResolvedValue(response({ enabled: false, grafana_configured: false, snapshot: null, items: [], items_total: 0 }));
    vi.mocked(api.grafanaStatus).mockResolvedValue({ configured: false, url: null, reachable: false, message: 'Grafana is not connected.' });
    renderPage();

    expect(await screen.findByText('No check has run yet')).toBeInTheDocument();
    expect(screen.getByTestId('grafana-line')).toHaveTextContent('Service accounts');
  });

  it('runs a check now and reloads', async () => {
    vi.mocked(api.metricUsage).mockResolvedValue(response());
    vi.mocked(api.grafanaStatus).mockResolvedValue({ configured: true, url: null, reachable: true, message: 'Connected' });
    vi.mocked(api.runMetricUsageCheck).mockResolvedValue(snapshot());
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: 'Run now' }));
    await waitFor(() => expect(api.runMetricUsageCheck).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(api.metricUsage).toHaveBeenCalledTimes(2));
  });

  it('explains what it needs instead of an empty page when no Prometheus-compatible source is connected', async () => {
    vi.mocked(api.ingestionStatus).mockResolvedValue(withMetricUsage('off'));
    vi.mocked(api.metricUsage).mockResolvedValue(response({ enabled: false, grafana_configured: false, snapshot: null, items: [], items_total: 0 }));
    vi.mocked(api.grafanaStatus).mockResolvedValue({ configured: false, url: null, reachable: false, message: 'Grafana is not connected.' });
    renderPage();

    expect(await screen.findByText('Find blind spots and metrics nobody uses')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Run now' })).not.toBeInTheDocument();
    expect(screen.queryByText('No check has run yet')).not.toBeInTheDocument();
    expect(screen.queryByTestId('grafana-line')).not.toBeInTheDocument();
  });

  it('still shows the last check when the source has since been disconnected', async () => {
    vi.mocked(api.ingestionStatus).mockResolvedValue(withMetricUsage('off'));
    vi.mocked(api.metricUsage).mockResolvedValue(response());
    vi.mocked(api.grafanaStatus).mockResolvedValue({ configured: true, url: null, reachable: true, message: 'Connected' });
    renderPage();

    expect(await screen.findByTestId('metric-usage-tiles')).toBeInTheDocument();
    expect(await screen.findByText(/is off until you connect/)).toBeInTheDocument();
  });

  it('shows the page as before when the feature is on', async () => {
    vi.mocked(api.ingestionStatus).mockResolvedValue(withMetricUsage('on'));
    vi.mocked(api.metricUsage).mockResolvedValue(response());
    vi.mocked(api.grafanaStatus).mockResolvedValue({ configured: true, url: null, reachable: true, message: 'Connected' });
    renderPage();

    expect(await screen.findByTestId('metric-usage-tiles')).toBeInTheDocument();
    expect(screen.queryByTestId('feature-needs-source')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run now' })).toBeInTheDocument();
  });
});

function withMetricUsage(state: 'on' | 'off'): IngestionStatus {
  return {
    generated_at: new Date().toISOString(),
    has_any_data: true,
    sources: {
      otlp: { endpoint_path: '/api/otlp/v1/metrics', last_received_at: null },
      alertmanager: { endpoint_path: '/api/integrations/alertmanager', enabled: false, token_required: false, last_received_at: null, received_24h: 0 },
      prometheus: { configured: state === 'on' },
    },
    features: [{ id: 'metric_usage', label: 'Metric Usage', state, missing: state === 'off' ? ['prometheus'] : [], detail: null }],
  };
}
