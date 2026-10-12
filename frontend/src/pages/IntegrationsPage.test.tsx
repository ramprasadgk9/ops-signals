import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { IntegrationsPage } from './IntegrationsPage';
import { api } from '../api/queries';
import type { FeatureAvailability, IngestionStatus } from '../types';

vi.mock('../api/queries', () => ({
  api: {
    ingestionStatus: vi.fn(),
    alerts: vi.fn(),
    otlpStatus: vi.fn(),
    sendTestAlert: vi.fn(),
    runCsvUpload: vi.fn(),
    caseImports: vi.fn(async () => []),
    aiStatus: vi.fn(async () => ({ enabled: false, provider: 'ollama', model: null, endpoint: null, api_key_set: null, active: false, issue: null })),
    testAiConnection: vi.fn(),
  },
}));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <IntegrationsPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const status: IngestionStatus = {
  generated_at: '2026-09-26T00:00:00Z',
  has_any_data: true,
  sources: {
    otlp: { endpoint_path: '/api/otlp/v1/metrics', last_received_at: null },
    alertmanager: { endpoint_path: '/api/integrations/alertmanager', enabled: true, token_required: true, last_received_at: new Date().toISOString(), received_24h: 2 },
    prometheus: { configured: false },
  },
};

const otlpStatus = {
  endpoint_path: '/api/otlp/v1/metrics',
  points_received_total: 0,
  points_rejected_total: {},
  backlog_size: 0,
  last_analysis_cycle_duration_seconds: 0,
  last_analysis_cycle_groups_processed: 0,
};

describe('IntegrationsPage', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('shows every way data gets in, with its endpoint and status, and links to received alerts', async () => {
    vi.mocked(api.ingestionStatus).mockResolvedValue(status);
    vi.mocked(api.otlpStatus).mockResolvedValue(otlpStatus);

    renderPage();

    expect(await screen.findByRole('heading', { name: 'Integrations' })).toBeInTheDocument();
    expect(await screen.findByText('Send metrics via OTLP')).toBeInTheDocument();
    expect(screen.getByText('Connect Alertmanager')).toBeInTheDocument();
    expect(screen.getByText('2 alerts received in the last 24h')).toBeInTheDocument();
    // The receiver needs a token here, so the snippet shows where it goes.
    expect(screen.getByText(/credentials: <receiver token>/)).toBeInTheDocument();
    expect(screen.queryByText(/Alert enrichment is off/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send test alert' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'View received alerts →' })).toHaveAttribute('href', '/alerts');
    // One-off analysis is a single line here, not a tile: this page is about ongoing connections.
    expect(within(screen.getByLabelText('One-off analysis')).getByRole('button', { name: 'Load demo data' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Analyze your own CSV' })).toHaveAttribute('href', '/validate-data');
    expect(screen.queryByText('Just exploring?')).not.toBeInTheDocument();
    // No separate OTLP card: its activity lives in the tile, and nothing has arrived yet.
    expect(screen.queryByText('OTLP Ingestion Activity')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('OTLP activity')).not.toBeInTheDocument();
    expect(screen.getAllByText(`${window.location.origin}/api/otlp/v1/metrics`)).toHaveLength(1);
    // Received alerts moved to their own page.
    expect(screen.queryByRole('region', { name: 'Alerts' })).not.toBeInTheDocument();
    expect(api.alerts).not.toHaveBeenCalled();
  });

  it('shows OTLP activity inside the OTLP tile once points arrive, with rejections', async () => {
    vi.mocked(api.ingestionStatus).mockResolvedValue({
      ...status,
      sources: { ...status.sources, otlp: { endpoint_path: '/api/otlp/v1/metrics', last_received_at: new Date().toISOString() } },
    });
    vi.mocked(api.otlpStatus).mockResolvedValue({ ...otlpStatus, points_received_total: 12480, backlog_size: 3, points_rejected_total: { unsupported_type: 312, invalid: 0 } });

    renderPage();

    const activity = await screen.findByLabelText('OTLP activity');
    expect(activity).toHaveTextContent('12,480 points received since the backend started · 3 awaiting analysis');
    expect(activity).toHaveTextContent('Rejected: 312 (unsupported_type)');
    expect(activity).not.toHaveTextContent('invalid');
  });

  it('shows where to send deploy events, with a CI snippet and the last deploy received', async () => {
    vi.mocked(api.ingestionStatus).mockResolvedValue({
      ...status,
      sources: {
        ...status.sources,
        events: {
          endpoint_path: '/api/events', token_required: true, last_received_at: new Date().toISOString(), received_24h: 3,
          last_event: { service: 'checkout', type: 'deploy', version: 'v2.4.71', env: 'prod', timestamp: new Date().toISOString() },
        },
      },
    });
    vi.mocked(api.otlpStatus).mockResolvedValue(otlpStatus);

    renderPage();

    expect(await screen.findByText('Send deploy events')).toBeInTheDocument();
    expect(screen.getByText(`${window.location.origin}/api/events`)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copy deploy events URL' })).toBeInTheDocument();
    const snippet = screen.getByText(/curl -X POST/);
    expect(snippet.textContent).toContain(`curl -X POST ${window.location.origin}/api/events \\`);
    expect(snippet.textContent).toContain('-H "Authorization: Bearer <events token>"');
    expect(snippet.textContent).toContain('"type": "deploy"');
    expect(screen.getByText(/Last: deploy v2\.4\.71 to checkout \(prod\)/)).toHaveTextContent('3 in the last 24h');
    expect(within(screen.getByRole('status', { name: 'Data sources' })).getByText(/^Deploys · /)).toBeInTheDocument();
  });

  it('waits for the first deploy without a token line when none is needed', async () => {
    vi.mocked(api.ingestionStatus).mockResolvedValue({
      ...status,
      sources: { ...status.sources, events: { endpoint_path: '/api/events', token_required: false, last_received_at: null, received_24h: 0, last_event: null } },
    });
    vi.mocked(api.otlpStatus).mockResolvedValue(otlpStatus);

    renderPage();

    expect(await screen.findByText('Waiting for deploys')).toBeInTheDocument();
    expect(screen.getByText(/curl -X POST/).textContent).not.toContain('Authorization');
    expect(screen.queryByText(/^Last:/)).not.toBeInTheDocument();
  });

  it('shows the Prometheus connection, whether it answers, and what uses it', async () => {
    vi.mocked(api.ingestionStatus).mockResolvedValue({
      ...status,
      sources: { ...status.sources, prometheus: { configured: true, url: 'http://prometheus:9090', reachable: true, scheduled_policies: 2, alert_enrichment_enabled: true } },
    });
    vi.mocked(api.otlpStatus).mockResolvedValue(otlpStatus);

    renderPage();

    expect(await screen.findByText('Connected')).toBeInTheDocument();
    expect(screen.getByText('http://prometheus:9090')).toBeInTheDocument();
    const usedBy = screen.getByLabelText('Used by');
    expect(usedBy).toHaveTextContent('Autonomous analysis: 2 policies running on a schedule');
    expect(usedBy).toHaveTextContent('Alert enrichment: on, analyzes the series behind each alert');
    expect(screen.getByRole('link', { name: 'Manage autonomous analysis →' })).toHaveAttribute('href', '/autonomous-monitoring');
  });

  it('says plainly when Prometheus is configured but unreachable', async () => {
    vi.mocked(api.ingestionStatus).mockResolvedValue({
      ...status,
      sources: { ...status.sources, prometheus: { configured: true, url: 'http://prometheus:9090', reachable: false, scheduled_policies: 0, alert_enrichment_enabled: false } },
    });
    vi.mocked(api.otlpStatus).mockResolvedValue(otlpStatus);

    renderPage();

    expect(await screen.findByText('Unreachable')).toBeInTheDocument();
    expect(screen.getByText(/can’t reach this Prometheus/)).toBeInTheDocument();
    expect(screen.getByLabelText('Used by')).toHaveTextContent('Autonomous analysis: not set up yet');
    expect(screen.getByRole('link', { name: 'Set up autonomous analysis →' })).toBeInTheDocument();
  });

  it('keeps the OTLP card usable when the status call fails', async () => {
    vi.mocked(api.ingestionStatus).mockRejectedValue(new Error('network'));
    vi.mocked(api.otlpStatus).mockResolvedValue(otlpStatus);

    renderPage();

    expect(await screen.findByText(/Could not load integration status/)).toBeInTheDocument();
    // Without the tiles, the card is the one place left that shows the endpoint.
    expect(await screen.findByText('OTLP Metrics Ingestion')).toBeInTheDocument();
    expect(screen.getByText(`${window.location.origin}/api/otlp/v1/metrics`)).toBeInTheDocument();
  });
});

describe('IntegrationsPage: what each source unlocks', () => {
  const feature = (
    id: string,
    label: string,
    state: FeatureAvailability['state'],
    needs: FeatureAvailability['needs'] = [],
    better_with: FeatureAvailability['better_with'] = [],
    missing: FeatureAvailability['missing'] = [],
  ): FeatureAvailability => ({ id, label, state, needs, better_with, missing, detail: null });

  const otlpOnly: IngestionStatus = {
    ...status,
    sources: {
      ...status.sources,
      otlp: { endpoint_path: '/api/otlp/v1/metrics', last_received_at: new Date().toISOString() },
      alertmanager: { ...status.sources.alertmanager, enabled: false, last_received_at: null, received_24h: 0 },
      grafana: { configured: false, url: null, reachable: null },
    },
    features: [
      feature('findings', 'Findings and analyzers', 'on'),
      feature('cases', 'Cases and ticketing', 'on'),
      feature('autonomous_analysis', 'Autonomous analysis', 'off', ['prometheus'], [], ['prometheus']),
      feature('alert_enrichment', 'Alert enrichment', 'off', ['alertmanager', 'prometheus'], [], ['alertmanager', 'prometheus']),
      feature('metric_usage', 'Metric Usage', 'off', ['prometheus'], ['grafana'], ['prometheus']),
    ],
  };

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('ends each source tile with what it turns on', async () => {
    vi.mocked(api.ingestionStatus).mockResolvedValue(otlpOnly);
    vi.mocked(api.otlpStatus).mockResolvedValue(otlpStatus);
    renderPage();

    expect(await screen.findByTestId('unlocks-otlp')).toHaveTextContent('Unlocks: Findings and analyzers · Cases and ticketing');
    expect(screen.getByTestId('unlocks-prometheus')).toHaveTextContent(
      'Unlocks: Autonomous analysis · Alert enrichment (with Alertmanager) · Metric Usage'
    );
    expect(screen.getByTestId('unlocks-alertmanager')).toHaveTextContent('Unlocks: Alert enrichment (with Prometheus)');
    expect(screen.getByTestId('unlocks-grafana')).toHaveTextContent('Unlocks: Metric Usage (more complete, with Prometheus)');
  });

  it('adds a Grafana tile with how to connect it', async () => {
    vi.mocked(api.ingestionStatus).mockResolvedValue(otlpOnly);
    vi.mocked(api.otlpStatus).mockResolvedValue(otlpStatus);
    renderPage();

    expect(await screen.findByText('Connect Grafana')).toBeInTheDocument();
    expect(screen.getByText(/Service accounts/)).toBeInTheDocument();
    expect(within(screen.getByRole('status', { name: 'Data sources' })).getByText('Grafana')).toBeInTheDocument();
  });

  it('lists every feature and why it is off in a side panel', async () => {
    vi.mocked(api.ingestionStatus).mockResolvedValue(otlpOnly);
    vi.mocked(api.otlpStatus).mockResolvedValue(otlpStatus);
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: 'What works with my data?' }));

    const table = await screen.findByRole('table', { name: 'Feature availability' });
    expect(within(table).getByTestId('feature-row-findings')).toHaveTextContent('On');
    expect(within(table).getByTestId('feature-row-alert_enrichment')).toHaveTextContent('Needs Alertmanager and a Prometheus-compatible source');
    expect(screen.getByText('2 on')).toBeInTheDocument();
    expect(screen.getByText('3 off')).toBeInTheDocument();
  });

  it('shows the page as before when the backend sends no feature list', async () => {
    vi.mocked(api.ingestionStatus).mockResolvedValue(status);
    vi.mocked(api.otlpStatus).mockResolvedValue(otlpStatus);
    renderPage();

    expect(await screen.findByText('Send metrics via OTLP')).toBeInTheDocument();
    expect(screen.queryByText(/Unlocks:/)).not.toBeInTheDocument();
    expect(screen.queryByText('Connect Grafana')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'What works with my data?' })).not.toBeInTheDocument();
  });
});
