import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ValidateDataPage } from './ValidateDataPage';
import { api } from '../api/queries';

vi.mock('../api/queries', () => ({
  api: {
    capabilities: vi.fn(),
    prometheusConnections: vi.fn(),
    prometheusLabelValues: vi.fn(),
    prometheusRecordingRules: vi.fn(),
    testPrometheusConnection: vi.fn(),
    previewPrometheus: vi.fn(),
    runPrometheusAnalysis: vi.fn(),
  },
}));

const RULES = [
  { name: 'service:error_rate:percent', query: '100 * avg by (service, env) (error_rate)', group: 'lab-rules', interval_seconds: 15, health: 'ok', source_metrics: ['error_rate'] },
  { name: 'all_services_error_rate_percent', query: '100 * avg(error_rate)', group: 'lab-rules', interval_seconds: 15, health: 'ok', source_metrics: ['error_rate'] },
];

function renderPage() {
  vi.mocked(api.capabilities).mockResolvedValue([]);
  vi.mocked(api.prometheusConnections).mockResolvedValue({
    connections: [{ id: 'local', name: 'Local Prometheus', base_url: 'http://prometheus:9090', configured: true, is_default: true }],
  });
  vi.mocked(api.prometheusRecordingRules).mockResolvedValue({ connection_id: 'local', rules: RULES });
  vi.mocked(api.prometheusLabelValues).mockImplementation(async (label: string, _connectionId?: string, filter?: { match?: string[] }) => {
    if (label === 'service') return { connection_id: 'local', label, values: ['spike-lab'] };
    // The "no service label" lookup: only the rule that sums every service away.
    if (filter?.match?.[0]?.includes('service=""')) return { connection_id: 'local', label, values: ['all_services_error_rate_percent'] };
    return { connection_id: 'local', label, values: ['cpu_usage', 'service:error_rate:percent', 'all_services_error_rate_percent'] };
  });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ValidateDataPage />
    </QueryClientProvider>
  );
}

async function openPrometheusTab() {
  fireEvent.click(await screen.findByRole('tab', { name: 'Prometheus' }));
  await waitFor(() => expect(api.prometheusRecordingRules).toHaveBeenCalledWith('local'));
}

async function pickMetric(name: string) {
  const input = screen.getByPlaceholderText('Select or type metric');
  fireEvent.change(input, { target: { value: name.slice(0, 6) } });
  const listbox = await screen.findByRole('listbox');
  fireEvent.click(within(listbox).getByText(name));
}

describe('ValidateDataPage recording rules', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('tags recording rules in the Metrics list and leaves other metrics plain', async () => {
    renderPage();
    await openPrometheusTab();

    fireEvent.change(screen.getByPlaceholderText('Select or type metric'), { target: { value: 'e' } });
    const listbox = await screen.findByRole('listbox');
    const ruleOption = within(listbox).getByText('service:error_rate:percent').closest('li')!;
    expect(within(ruleOption).getByText('Recording rule')).toBeInTheDocument();
    expect(within(ruleOption).getByText('· lab-rules')).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText('Select or type metric'), { target: { value: 'cpu' } });
    const cpuOption = within(await screen.findByRole('listbox')).getByText('cpu_usage').closest('li')!;
    expect(within(cpuOption).queryByText('Recording rule')).not.toBeInTheDocument();
  });

  it('shows the saved query when a rule is picked', async () => {
    renderPage();
    await openPrometheusTab();
    await pickMetric('service:error_rate:percent');

    const note = await screen.findByTestId('recording-rule-note');
    expect(note).toHaveTextContent('Recording rule in group lab-rules. Prometheus runs this query every 15s and saves the result under this name:');
    expect(note).toHaveTextContent('100 * avg by (service, env) (error_rate)');
    expect(note).toHaveTextContent('Built from error_rate');
    expect(note).not.toHaveTextContent('no service label');
  });

  it('says a rule without the service label can be previewed but not analyzed', async () => {
    renderPage();
    await openPrometheusTab();
    const serviceInput = screen.getByPlaceholderText('Select or type service');
    fireEvent.change(serviceInput, { target: { value: 'spike-lab' } });
    fireEvent.keyDown(serviceInput, { key: 'Escape' });
    await pickMetric('all_services_error_rate_percent');

    const note = await screen.findByTestId('recording-rule-note');
    await waitFor(() => expect(note).toHaveTextContent("This rule adds up all services, so its result doesn't belong to one service and can't be saved as a finding."));
    expect(within(note).queryByRole('button')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run Analysis' })).toBeDisabled();
  });

  it('runs a rule that keeps the service label once a Service is picked', async () => {
    renderPage();
    await openPrometheusTab();
    await pickMetric('service:error_rate:percent');

    expect(await screen.findByTestId('service-needed')).toHaveTextContent('Pick a Service to run the analysis: every finding is saved under one service.');
    expect(screen.getByRole('button', { name: 'Run Analysis' })).toBeDisabled();

    const serviceInput = screen.getByPlaceholderText('Select or type service');
    fireEvent.change(serviceInput, { target: { value: 'spike-lab' } });
    fireEvent.keyDown(serviceInput, { key: 'Escape' });

    await waitFor(() => expect(screen.getByRole('button', { name: 'Run Analysis' })).toBeEnabled());
    expect(screen.queryByTestId('service-needed')).not.toBeInTheDocument();
  });

  it('works as before when the rules request fails', async () => {
    renderPage();
    vi.mocked(api.prometheusRecordingRules).mockRejectedValue(new Error('503 Prometheus connection failed'));
    await openPrometheusTab();
    const serviceInput = screen.getByPlaceholderText('Select or type service');
    fireEvent.change(serviceInput, { target: { value: 'spike-lab' } });
    fireEvent.keyDown(serviceInput, { key: 'Escape' });
    await pickMetric('service:error_rate:percent');

    expect(screen.getByLabelText('PromQL')).toHaveValue('service:error_rate:percent{service="spike-lab"}');
    expect(screen.queryByTestId('recording-rule-note')).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Run Analysis' })).toBeEnabled());
  });

  it('works as before when the connection has no recording rules', async () => {
    renderPage();
    vi.mocked(api.prometheusRecordingRules).mockResolvedValue({ connection_id: 'local', rules: [], message: "Couldn't read recording rules: not found" });
    await openPrometheusTab();
    await pickMetric('cpu_usage');

    expect(screen.queryByTestId('recording-rule-note')).not.toBeInTheDocument();
  });
});
