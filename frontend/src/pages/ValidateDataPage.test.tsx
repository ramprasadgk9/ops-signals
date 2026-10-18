import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ValidateDataPage, describeInterval } from './ValidateDataPage';
import { api } from '../api/queries';

vi.mock('../api/queries', () => ({
  api: {
    capabilities: vi.fn(),
    prometheusConnections: vi.fn(),
    prometheusLabelValues: vi.fn(),
    runCsvValidation: vi.fn(),
    runCsvUpload: vi.fn(),
    findings: vi.fn(),
    createCase: vi.fn(),
    testPrometheusConnection: vi.fn(),
    previewPrometheus: vi.fn(),
    runPrometheusAnalysis: vi.fn(),
  },
}));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ValidateDataPage />
    </QueryClientProvider>
  );
}

describe('ValidateDataPage source modes', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('switches between CSV upload and direct Prometheus controls', async () => {
    vi.mocked(api.capabilities).mockResolvedValue([]);
    vi.mocked(api.prometheusConnections).mockResolvedValue({
      connections: [{ id: 'default', name: 'Default Prometheus', base_url: 'http://prometheus:9090', configured: true }],
    });
    vi.mocked(api.prometheusLabelValues).mockImplementation(async (label: string) => ({
      connection_id: 'default',
      label,
      values: label === 'service' ? ['ruptures-lab', 'trend-lab'] : ['cpu_usage', 'ops_signal_lab_value'],
    }));

    renderPage();

    expect(await screen.findByRole('tab', { name: 'CSV Upload' })).toBeInTheDocument();
    expect(screen.getByText('Choose CSV File')).toBeInTheDocument();
    expect(screen.queryByText('Direct Prometheus')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: 'Prometheus' }));

    expect(await screen.findByText('Direct Prometheus')).toBeInTheDocument();
    expect(screen.getByLabelText('PromQL')).toBeInTheDocument();
    expect(screen.getAllByText('Last 24 hours').length).toBeGreaterThan(0);
    expect(screen.getByText('Preview Data')).toBeInTheDocument();
    expect(api.prometheusLabelValues).toHaveBeenCalledWith('service', 'default');
    expect(api.prometheusLabelValues).toHaveBeenCalledWith('__name__', 'default');
    expect(screen.queryByText('Choose CSV File')).not.toBeInTheDocument();
  });

  it('shows the expected CSV columns for the selected provider and updates when the provider changes', async () => {
    vi.mocked(api.capabilities).mockResolvedValue([]);
    vi.mocked(api.prometheusConnections).mockResolvedValue({ connections: [] });
    vi.mocked(api.prometheusLabelValues).mockResolvedValue({ connection_id: 'default', label: 'service', values: [] });

    renderPage();

    expect(await screen.findByText(/Expected columns for prometheus/)).toBeInTheDocument();
    expect(screen.getByText(/timestamp,metric,value/)).toBeInTheDocument();

    fireEvent.mouseDown(screen.getByText('Prometheus CSV'));
    fireEvent.click(await screen.findByRole('option', { name: 'Datadog CSV' }));

    expect(await screen.findByText(/Expected columns for datadog/)).toBeInTheDocument();
    expect(screen.getByText(/ts_epoch_ms,metric_name,value/)).toBeInTheDocument();
  });

  it('requires all 3 custom column names, warns they are not saved, and sends them with the upload', async () => {
    vi.mocked(api.capabilities).mockResolvedValue([]);
    vi.mocked(api.prometheusConnections).mockResolvedValue({ connections: [] });
    vi.mocked(api.prometheusLabelValues).mockResolvedValue({ connection_id: 'default', label: 'service', values: [] });
    vi.mocked(api.runCsvValidation).mockResolvedValue({
      provider: 'custom',
      source_type: 'csv',
      analyzer_id: 'router',
      service: 'svc',
      metric_name: 'cpu_usage',
      sample_count: 1,
      normalized_preview: [],
      signals: [],
      findings: [],
      analyzer_selection_mode: 'all',
      analyzer_routing: [],
      executed_analyzers: [],
    });

    renderPage();

    fireEvent.mouseDown(await screen.findByText('Prometheus CSV'));
    fireEvent.click(await screen.findByRole('option', { name: 'Custom / Other' }));

    expect(await screen.findByText(/not saved/)).toBeInTheDocument();
    expect(screen.queryByText(/Expected columns for/)).not.toBeInTheDocument();

    const validateButton = screen.getByRole('button', { name: 'Validate Data' });
    expect(validateButton).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/Timestamp column name/), { target: { value: 'event_time' } });
    fireEvent.change(screen.getByLabelText(/Value column name/), { target: { value: 'measurement' } });
    fireEvent.change(screen.getByLabelText(/Metric name column/), { target: { value: 'metric' } });

    const file = new File(['event_time,measurement,metric\n2026-01-01T00:00:00Z,42.5,cpu_usage'], 'custom.csv', { type: 'text/csv' });
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [file] } });

    expect(validateButton).not.toBeDisabled();
    fireEvent.click(validateButton);

    await screen.findByText(/router with 1 samples/);

    const submittedForm = vi.mocked(api.runCsvValidation).mock.calls[0][0];
    expect(submittedForm.get('provider')).toBe('custom');
    expect(submittedForm.get('custom_timestamp_column')).toBe('event_time');
    expect(submittedForm.get('custom_value_column')).toBe('measurement');
    expect(submittedForm.get('custom_metric_name_column')).toBe('metric');
  });

  it('starts with no demo service or metric and sends neither unless the user types one', async () => {
    vi.mocked(api.capabilities).mockResolvedValue([]);
    vi.mocked(api.prometheusConnections).mockResolvedValue({ connections: [] });
    vi.mocked(api.prometheusLabelValues).mockResolvedValue({ connection_id: 'default', label: 'service', values: [] });
    vi.mocked(api.runCsvValidation).mockResolvedValue({
      provider: 'prometheus', source_type: 'csv', analyzer_id: 'router', service: 'uploaded-service', metric_name: 'cpu_usage',
      sample_count: 1, normalized_preview: [], signals: [], findings: [], analyzer_selection_mode: 'all', analyzer_routing: [], executed_analyzers: [],
    });

    renderPage();

    expect(await screen.findByLabelText('Service')).toHaveValue('');
    expect(screen.getByLabelText('Metric')).toHaveValue('');
    const file = new File(['timestamp,metric,value\n2026-01-01T00:00:00Z,cpu_usage,42.5'], 'cpu.csv', { type: 'text/csv' });
    fireEvent.change(document.querySelector('input[type="file"]') as HTMLInputElement, { target: { files: [file] } });
    fireEvent.click(screen.getByRole('button', { name: 'Validate Data' }));
    await waitFor(() => expect(api.runCsvValidation).toHaveBeenCalledTimes(1));
    const untouched = vi.mocked(api.runCsvValidation).mock.calls[0][0];
    expect(untouched.has('service')).toBe(false);
    expect(untouched.has('metric_name')).toBe(false);

    fireEvent.change(screen.getByLabelText('Service'), { target: { value: ' checkout ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Validate Data' }));
    await waitFor(() => expect(api.runCsvValidation).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.runCsvValidation).mock.calls[1][0].get('service')).toBe('checkout');
  });

  it('sends auto by default and shows the detected interval and any warning', async () => {
    vi.mocked(api.capabilities).mockResolvedValue([]);
    vi.mocked(api.prometheusConnections).mockResolvedValue({ connections: [] });
    vi.mocked(api.prometheusLabelValues).mockResolvedValue({ connection_id: 'default', label: 'service', values: [] });
    vi.mocked(api.runCsvValidation).mockResolvedValue({
      provider: 'prometheus',
      source_type: 'csv',
      analyzer_id: 'router',
      service: 'svc',
      metric_name: 'cpu_usage',
      sample_count: 288,
      requested_interval: 'auto',
      interval: '15m',
      warnings: ['Interval 5m leaves 67% of time slots empty for svc / cpu_usage: the data has a point about every 15m.'],
      normalized_preview: [],
      signals: [],
      findings: [],
      analyzer_selection_mode: 'all',
      analyzer_routing: [],
      executed_analyzers: [],
    });

    renderPage();

    expect(await screen.findByLabelText('Interval')).toHaveValue('auto');

    const file = new File(['timestamp,metric,value\n2026-01-01T00:00:00Z,cpu_usage,42.5'], 'cpu.csv', { type: 'text/csv' });
    fireEvent.change(document.querySelector('input[type="file"]') as HTMLInputElement, { target: { files: [file] } });
    fireEvent.click(screen.getByRole('button', { name: 'Validate Data' }));

    expect(await screen.findByText(/288 samples at a 15m interval \(detected from the data\)/)).toBeInTheDocument();
    expect(screen.getByText(/leaves 67% of time slots empty/)).toBeInTheDocument();
    expect(vi.mocked(api.runCsvValidation).mock.calls[0][0].get('interval')).toBe('auto');
  });

  it('says a finished run found nothing, instead of "no findings returned yet" (QA-19)', async () => {
    vi.mocked(api.capabilities).mockResolvedValue([]);
    vi.mocked(api.prometheusConnections).mockResolvedValue({ connections: [] });
    vi.mocked(api.prometheusLabelValues).mockResolvedValue({ connection_id: 'default', label: 'service', values: [] });
    vi.mocked(api.runCsvValidation).mockResolvedValue({
      provider: 'prometheus',
      source_type: 'csv',
      analyzer_id: 'router',
      service: 'svc',
      metric_name: 'cpu_usage',
      sample_count: 288,
      normalized_preview: [],
      signals: [],
      findings: [],
      analyzer_selection_mode: 'all',
      analyzer_routing: [],
      executed_analyzers: [],
    });

    renderPage();

    expect(await screen.findByText('No findings returned yet.')).toBeInTheDocument();
    const file = new File(['timestamp,metric,value\n2026-01-01T00:00:00Z,cpu_usage,42.5'], 'cpu.csv', { type: 'text/csv' });
    fireEvent.change(document.querySelector('input[type="file"]') as HTMLInputElement, { target: { files: [file] } });
    fireEvent.click(screen.getByRole('button', { name: 'Validate Data' }));

    expect(await screen.findByText(/No findings: nothing in this data stood out/)).toBeInTheDocument();
    expect(screen.getByText(/No signals: the analyzers that ran detected nothing/)).toBeInTheDocument();
    expect(screen.queryByText('No findings returned yet.')).not.toBeInTheDocument();
  });

  it('saves a CSV run and creates a case from its finding (QA-33)', async () => {
    vi.mocked(api.capabilities).mockResolvedValue([]);
    vi.mocked(api.prometheusConnections).mockResolvedValue({ connections: [] });
    vi.mocked(api.prometheusLabelValues).mockResolvedValue({ connection_id: 'default', label: 'service', values: [] });
    vi.mocked(api.runCsvUpload).mockResolvedValue({
      analysis_run_id: 'run-1',
      provider: 'generic',
      source_type: 'csv',
      service: 'checkout',
      metric_name: 'cpu_usage',
      sample_count: 288,
      findings_count: 1,
      requested_interval: 'auto',
      interval: '5m',
      warnings: [],
    });
    vi.mocked(api.findings).mockResolvedValue([
      {
        id: 42,
        service: 'checkout',
        metric_name: 'cpu_usage',
        title: 'cpu_usage experienced a persistent baseline shift',
        summary: 'Average fell 43.6%.',
        category: 'behavior_change',
        health_status: 'significant',
        importance_score: 0.55,
      } as Awaited<ReturnType<typeof api.findings>>[number],
    ]);
    vi.mocked(api.createCase).mockResolvedValue({ case_id: 7, finding_id: 42 } as Awaited<ReturnType<typeof api.createCase>>);

    renderPage();

    const file = new File(['timestamp,metric_name,value\n2026-01-01T00:00:00Z,cpu_usage,42.5'], 'cpu.csv', { type: 'text/csv' });
    fireEvent.change(document.querySelector('input[type="file"]') as HTMLInputElement, { target: { files: [file] } });
    fireEvent.click(await screen.findByRole('button', { name: 'Analyze and Save' }));

    expect(await screen.findByText(/Saved: 288 samples at a 5m interval \(detected from the data\), 1 finding\./)).toBeInTheDocument();
    expect(screen.getByText('cpu_usage experienced a persistent baseline shift')).toBeInTheDocument();
    expect(screen.getByText(/Create a case from it below/)).toBeInTheDocument();
    expect(screen.queryByText('No findings returned yet.')).not.toBeInTheDocument();
    expect(api.runCsvValidation).not.toHaveBeenCalled();
    expect(vi.mocked(api.findings).mock.calls[0][2]).toBe('run-1');
    expect(vi.mocked(api.runCsvUpload).mock.calls[0][0].get('interval')).toBe('auto');

    fireEvent.click(screen.getByRole('button', { name: 'Create Case' }));

    expect(await screen.findByRole('link', { name: 'Open Case #7' })).toHaveAttribute('href', '/cases/7');
    expect(vi.mocked(api.createCase).mock.calls[0][0]).toBe(42);
  });
});

describe('describeInterval', () => {
  it('marks a measured interval as detected and leaves a typed one plain', () => {
    expect(describeInterval({ requested_interval: 'auto', interval: '15m' })).toBe(' at a 15m interval (detected from the data)');
    expect(describeInterval({ requested_interval: '5m', interval: '5m' })).toBe(' at a 5m interval');
    expect(describeInterval({})).toBe('');
  });
});

describe('ValidateDataPage clusters', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  function setup({ services, clusters }: { services: string[]; clusters: string[] }) {
    vi.mocked(api.capabilities).mockResolvedValue([]);
    vi.mocked(api.prometheusConnections).mockResolvedValue({
      connections: [{ id: 'mimir-a', name: 'Mimir team-a', configured: true, is_default: true, cluster_label: 'cluster' }],
    });
    vi.mocked(api.prometheusLabelValues).mockImplementation(async (label: string) => ({
      connection_id: 'mimir-a',
      label,
      values: label === 'service' ? services : label === 'cluster' ? clusters : ['ops_signal_lab_value'],
    }));
    vi.mocked(api.runPrometheusAnalysis).mockResolvedValue({
      analysis_run_id: 'run-1', provider: 'prometheus', source_type: 'prometheus', connection_id: 'mimir-a', connection_name: 'Mimir team-a',
      service: 'ruptures-lab', metric_name: 'ops_signal_lab_value', query: '', requested_start: '', requested_end: '', step: '5m', step_seconds: 300,
      sample_count: 0, series_count: 1, findings_count: 0, signal_count: 0, behavior_findings_count: 0, warnings: [],
      analyzer_selection_mode: 'all', analyzer_routing: [], executed_analyzers: [], series: [], signals: [], findings: [],
    });
    renderPage();
    fireEvent.click(screen.getByRole('tab', { name: 'Prometheus' }));
    // The form starts empty; pick the lab series the way a user would.
    if (services.includes('ruptures-lab')) fireEvent.click(screen.getByText('Baseline shift: ruptures-lab'));
  }

  const promql = () => (screen.getByLabelText('PromQL') as HTMLTextAreaElement).value;
  const runButton = () => screen.getByRole('button', { name: 'Run Analysis' });

  it('adds nothing when the series is in one cluster', async () => {
    setup({ services: ['ruptures-lab'], clusters: ['eu'] });

    await waitFor(() => expect(api.prometheusLabelValues).toHaveBeenCalledWith('cluster', 'mimir-a', expect.anything()));
    expect(screen.queryByText('Cluster')).not.toBeInTheDocument();
    expect(promql()).toBe('ops_signal_lab_value{service="ruptures-lab"}');
    expect(runButton()).toBeEnabled();
  });

  it('looks up clusters only for the chosen service and metric, in the chosen time range', async () => {
    setup({ services: ['ruptures-lab'], clusters: [] });

    await waitFor(() => expect(api.prometheusLabelValues).toHaveBeenCalledWith('cluster', 'mimir-a', expect.anything()));
    const filter = vi.mocked(api.prometheusLabelValues).mock.calls.find(([label]) => label === 'cluster')?.[2];
    expect(filter?.match).toEqual(['ops_signal_lab_value{service="ruptures-lab"}']);
    expect(filter?.start).toBeTruthy();
    expect(filter?.end).toBeTruthy();
  });

  it('asks for a cluster before running when the series is in several', async () => {
    setup({ services: ['ruptures-lab'], clusters: ['eu', 'us'] });

    expect(await screen.findByText('ruptures-lab runs in 2 clusters')).toBeInTheDocument();
    expect(screen.getByText('Choose a cluster (eu, us) to run analysis. Preview shows every cluster.')).toBeInTheDocument();
    expect(runButton()).toBeDisabled();
    expect(promql()).toBe('ops_signal_lab_value{service="ruptures-lab"}');

    fireEvent.mouseDown(screen.getByText('Choose a cluster'));
    fireEvent.click(await screen.findByRole('option', { name: 'us' }));

    expect(promql()).toBe('ops_signal_lab_value{service="ruptures-lab",cluster="us"}');
    expect(runButton()).toBeEnabled();
    fireEvent.click(runButton());
    await waitFor(() => expect(api.runPrometheusAnalysis).toHaveBeenCalled());
    expect(vi.mocked(api.runPrometheusAnalysis).mock.calls[0][0].query).toBe('ops_signal_lab_value{service="ruptures-lab",cluster="us"}');
  });

  it('starts with no service or metric, and can only preview or run once a metric is chosen', async () => {
    setup({ services: ['checkout'], clusters: [] });

    await waitFor(() => expect(api.prometheusLabelValues).toHaveBeenCalledWith('service', 'mimir-a'));
    expect(screen.queryByDisplayValue('ruptures-lab')).not.toBeInTheDocument();
    expect(promql()).toBe('');
    expect(runButton()).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Preview Data' })).toBeDisabled();

    fireEvent.mouseDown(screen.getByText('Simple'));
    fireEvent.click(await screen.findByRole('option', { name: 'Advanced PromQL' }));
    fireEvent.change(screen.getByLabelText('PromQL'), { target: { value: 'cpu_usage' } });
    await waitFor(() => expect(runButton()).toBeEnabled());
  });

  it('shows the lab scenarios only when the connection has the lab services', async () => {
    setup({ services: ['checkout', 'payments'], clusters: [] });

    await waitFor(() => expect(api.prometheusLabelValues).toHaveBeenCalledWith('service', 'mimir-a'));
    await waitFor(() => expect(screen.queryByText('Lab Scenarios')).not.toBeInTheDocument());
  });

  it('links the run result to its finding on the Findings page', async () => {
    setup({ services: ['ruptures-lab'], clusters: [] });
    const finding = {
      id: 42, title: 'request_latency_p95 is trending in one direction.', summary: 'Upward trend.', category: 'behavior_change',
      health_status: 'normal', investigation_priority: 3,
    };
    vi.mocked(api.runPrometheusAnalysis).mockResolvedValue({
      analysis_run_id: 'run-1', provider: 'prometheus', source_type: 'prometheus', connection_id: 'mimir-a', connection_name: 'Mimir team-a',
      service: 'ruptures-lab', metric_name: 'ops_signal_lab_value', query: '', requested_start: '', requested_end: '', step: '5m', step_seconds: 300,
      sample_count: 0, series_count: 1, findings_count: 1, signal_count: 0, behavior_findings_count: 0, warnings: [],
      analyzer_selection_mode: 'all', analyzer_routing: [], executed_analyzers: [], series: [], signals: [], findings: [finding],
    } as never);

    await waitFor(() => expect(runButton()).toBeEnabled());
    fireEvent.click(runButton());

    const link = await screen.findByRole('link', { name: 'View in Findings' });
    expect(link).toHaveAttribute('href', '/findings?finding=42');
    expect(screen.getByText(/Finding #42/)).toBeInTheDocument();
  });

  it('keeps the lab scenarios on the mock Prometheus', async () => {
    setup({ services: ['ruptures-lab', 'trend-lab'], clusters: [] });

    await waitFor(() => expect(api.prometheusLabelValues).toHaveBeenCalledWith('service', 'mimir-a'));
    expect(screen.getByText('Lab Scenarios')).toBeInTheDocument();
  });
});
