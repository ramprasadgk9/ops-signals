import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { FindingDetailsDrawer } from './FindingDetailsDrawer';
import { api } from '../api/queries';
import type { Finding, Signal } from '../types';

vi.mock('../api/queries', () => ({
  api: {
    analysisRun: vi.fn(),
    timeseries: vi.fn(),
    signalsByRunIds: vi.fn(async () => []),
    findingSeenBefore: vi.fn(),
  },
}));

function renderDrawer(finding: Finding) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <FindingDetailsDrawer open finding={finding} signals={[]} onClose={() => {}} />
    </QueryClientProvider>
  );
}

const otlpFinding: Finding = {
  id: 41,
  service: 'test-otlp-service',
  metric_name: 'cpu_usage',
  title: 'cpu_usage is trending in one direction.',
  summary: 'trend',
  category: 'behavior_change',
  health_status: 'significant',
  importance_score: 0.78,
  investigation_priority: 2,
  signal_ids: [],
  comparison_json: {},
  analysis_run_id: 'c06d17a3dd9143ef8ebd8c454031fd89',
  created_at: '2026-09-22T17:47:07Z',
};

describe('FindingDetailsDrawer ingested data section', () => {
  it('shows an OTLP badge and the run id for an otel-sourced finding', async () => {
    vi.mocked(api.analysisRun).mockResolvedValue({
      id: 'c06d17a3dd9143ef8ebd8c454031fd89',
      source_type: 'otel',
      provider: 'otel',
      service: 'test-otlp-service',
      metric_name: 'cpu_usage',
      start_time: '2026-09-21T17:47:00Z',
      end_time: '2026-09-22T17:47:00Z',
      sample_count: 288,
      status: 'completed',
      created_at: '2026-09-22T17:47:07Z',
    });
    vi.mocked(api.timeseries).mockResolvedValue([
      { timestamp: '2026-09-22T17:40:00Z', value: 70, service: 'test-otlp-service', metric_name: 'cpu_usage', analysis_run_id: 'c06d17a3dd9143ef8ebd8c454031fd89' },
      { timestamp: '2026-09-22T17:45:00Z', value: 82, service: 'test-otlp-service', metric_name: 'cpu_usage', analysis_run_id: 'c06d17a3dd9143ef8ebd8c454031fd89' },
    ]);

    renderDrawer(otlpFinding);

    expect(await screen.findByText('OTLP')).toBeInTheDocument();
    expect(screen.getByText(/288 points/)).toBeInTheDocument();
    expect(screen.getByText(/c06d17a3/)).toBeInTheDocument();
    expect(api.timeseries).toHaveBeenCalledWith('test-otlp-service', 'cpu_usage', 'c06d17a3dd9143ef8ebd8c454031fd89', undefined);
  });

  it('shows the cluster and charts only that cluster for a multi-cluster finding', async () => {
    vi.mocked(api.analysisRun).mockResolvedValue({
      id: 'run-eu',
      source_type: 'prometheus',
      provider: 'prometheus',
      service: 'checkout',
      metric_name: 'cpu_usage',
      start_time: '2026-09-21T00:00:00Z',
      end_time: '2026-09-22T00:00:00Z',
      sample_count: 100,
      status: 'completed',
      created_at: '2026-09-22T17:47:07Z',
    });
    vi.mocked(api.timeseries).mockResolvedValue([]);

    renderDrawer({ ...otlpFinding, service: 'checkout', analysis_run_id: 'run-eu', cluster: 'eu' });

    expect(await screen.findByText('Cluster')).toBeInTheDocument();
    expect(screen.getByText('eu')).toBeInTheDocument();
    expect(api.timeseries).toHaveBeenCalledWith('checkout', 'cpu_usage', 'run-eu', 'eu');
  });

  it('labels a prometheus-sourced finding distinctly from an OTLP one', async () => {
    vi.mocked(api.analysisRun).mockResolvedValue({
      id: 'run-prom-1',
      source_type: 'prometheus',
      provider: 'prometheus',
      service: 'checkout',
      metric_name: 'cpu_usage',
      start_time: '2026-09-21T00:00:00Z',
      end_time: '2026-09-22T00:00:00Z',
      sample_count: 100,
      status: 'completed',
      created_at: '2026-09-22T17:47:07Z',
    });
    vi.mocked(api.timeseries).mockResolvedValue([]);

    renderDrawer({ ...otlpFinding, service: 'checkout', analysis_run_id: 'run-prom-1' });

    expect(await screen.findByText('Prometheus')).toBeInTheDocument();
    expect(screen.queryByText('OTLP')).not.toBeInTheDocument();
  });

  it('shows a message instead of a chart when the run has no raw points', async () => {
    vi.mocked(api.analysisRun).mockResolvedValue({
      id: 'c06d17a3dd9143ef8ebd8c454031fd89',
      source_type: 'otel',
      provider: 'otel',
      service: 'test-otlp-service',
      metric_name: 'cpu_usage',
      start_time: '2026-09-21T17:47:00Z',
      end_time: '2026-09-22T17:47:00Z',
      sample_count: 0,
      status: 'completed',
      created_at: '2026-09-22T17:47:07Z',
    });
    vi.mocked(api.timeseries).mockResolvedValue([]);

    renderDrawer(otlpFinding);

    expect(await screen.findByText('No raw points found for this analysis run.')).toBeInTheDocument();
  });
});

describe('FindingDetailsDrawer drill-down breakdown', () => {
  const breakdown = {
    status: 'ok',
    label: 'pod',
    mode: 'share',
    spread: 'concentrated',
    direction: 'up',
    parts_total: 6,
    parts_changed: 1,
    top: [
      { value: 'checkout-x2', before: 0.2, after: 3.57, change: 3.37, relative_change: 16.85, share: 0.91, moved: true, new: false, gone: false },
      { value: 'checkout-a1', before: 0.2, after: 0.21, change: 0.01, relative_change: 0.05, share: 0.09, moved: false, new: false, gone: false },
    ],
    others: null,
  };

  it('shows where the change came from when the finding has a breakdown', () => {
    renderDrawer({ ...otlpFinding, analysis_run_id: undefined, comparison_json: { breakdown } });

    expect(screen.getByText('Where the change came from')).toBeInTheDocument();
    expect(screen.getAllByText('1 of 6 pods').length).toBeGreaterThan(0);
    expect(screen.getByText('91% of the increase comes from pod checkout-x2, 1 of 6 pods.')).toBeInTheDocument();
  });

  it('leaves the breakdown out of the raw comparison view', () => {
    renderDrawer({ ...otlpFinding, analysis_run_id: undefined, comparison_json: { change_percent: 308, breakdown } });

    const raw = screen.getByText(/"change_percent": 308/);
    expect(raw.textContent).not.toContain('checkout-x2');
  });

  it('shows nothing new for a finding without a breakdown', () => {
    renderDrawer({ ...otlpFinding, analysis_run_id: undefined });

    expect(screen.queryByText('Where the change came from')).not.toBeInTheDocument();
    expect(screen.queryByText(/Breakdown by pod not available/)).not.toBeInTheDocument();
  });

  it('says why an OTLP finding has no pod breakdown, and names its source', () => {
    renderDrawer({ ...otlpFinding, analysis_run_id: undefined, source: 'otlp', category: 'behavior_change' });

    expect(screen.getByTestId('breakdown-source-note')).toHaveTextContent("Breakdown by pod isn't available for OTLP data yet");
    expect(screen.getByText('Data source')).toBeInTheDocument();
  });

  it('adds no source note for Prometheus findings or data-quality findings', () => {
    const { unmount } = renderDrawer({ ...otlpFinding, analysis_run_id: undefined, source: 'prometheus', category: 'behavior_change' });
    expect(screen.queryByTestId('breakdown-source-note')).not.toBeInTheDocument();
    unmount();

    renderDrawer({ ...otlpFinding, analysis_run_id: undefined, source: 'otlp', category: 'data_quality' });
    expect(screen.queryByTestId('breakdown-source-note')).not.toBeInTheDocument();
  });
});

describe('FindingDetailsDrawer evidence', () => {
  const signal = (id: string, analyzer: string, extra: Partial<Signal> = {}): Signal => ({
    id,
    signal_type: analyzer === 'pyod_outlier' ? 'anomaly' : analyzer,
    analyzer_id: analyzer,
    metric_name: 'http_errors_total',
    service: 'cart',
    severity: 'high',
    importance_score: 0.85,
    evidence: {},
    analysis_run_id: 'run-cart-1',
    ...extra,
  } as Signal);

  it("loads the finding's own run signals when the page passed none (finding opened from a link)", async () => {
    vi.mocked(api.analysisRun).mockResolvedValue({
      id: 'run-cart-1',
      source_type: 'prometheus',
      provider: 'prometheus',
      service: 'cart',
      metric_name: 'http_errors_total',
      start_time: '2026-09-30T00:00:00Z',
      end_time: '2026-10-01T00:00:00Z',
      sample_count: 288,
      status: 'completed',
      created_at: '2026-10-01T02:18:27Z',
    });
    vi.mocked(api.timeseries).mockResolvedValue([]);
    vi.mocked(api.signalsByRunIds).mockResolvedValue([
      signal('s-ruptures', 'ruptures'),
      signal('s-trend', 'trend', { importance_score: 0.98 }),
      signal('s-pyod', 'pyod_outlier', { severity: 'medium', importance_score: 0.26, evidence: { finding_rule_matched: false } }),
    ]);

    renderDrawer({
      ...otlpFinding,
      service: 'cart',
      metric_name: 'http_errors_total',
      analysis_run_id: 'run-cart-1',
      signal_ids: ['s-ruptures', 's-pyod', 's-trend'],
    });

    expect(await screen.findByText('2 supporting signals detected')).toBeInTheDocument();
    expect(api.signalsByRunIds).toHaveBeenCalledWith(['run-cart-1']);
    expect(screen.queryByText('No problem-signals matched.')).not.toBeInTheDocument();
  });
});

describe('FindingDetailsDrawer deploys', () => {
  const breakdown = {
    status: 'ok',
    label: 'pod',
    mode: 'share',
    spread: 'partial',
    direction: 'up',
    parts_total: 6,
    parts_changed: 2,
    new_parts: 2,
    top: [
      { value: 'cart-8c2-q1', before: null, after: 1.4, change: 1.4, relative_change: 12, share: 0.52, moved: true, new: true, gone: false },
      { value: 'cart-8c2-w7', before: null, after: 1.3, change: 1.3, relative_change: 11, share: 0.48, moved: true, new: true, gone: false },
    ],
    others: null,
  };
  const changes = {
    status: 'matched',
    service: 'cart',
    anchor: '2026-10-01T14:10:00Z',
    window_before_minutes: 30,
    window_after_minutes: 5,
    matches: [{ id: 7, event_type: 'deploy', version: 'v1.4.2', description: null, author: null, url: null, timestamp: '2026-10-01T14:06:00Z', minutes_before_anchor: 4 }],
    pods: { status: 'linked', method: 'pod_start_time', event_id: 7, label: 'pod', parts: ['cart-8c2-q1', 'cart-8c2-w7'], new_parts: 2, old_parts_running: 4, old_parts_gone: 0, rollout_minutes: 15 },
  };

  it('shows the deploy chip, links the new pods to it and lists it under What changed', () => {
    renderDrawer({ ...otlpFinding, service: 'cart', analysis_run_id: undefined, comparison_json: { breakdown }, changes });

    expect(screen.getByText('After deploy v1.4.2')).toBeInTheDocument();
    expect(screen.getByTestId('breakdown-deploy-link').textContent).toContain('These 2 new pods started with deploy v1.4.2');
    expect(screen.getByText(/The change is on the pods from deploy v1.4.2/)).toBeInTheDocument();
    expect(screen.getByTestId('finding-what-changed').textContent).toContain('Started 4 min after deploy v1.4.2');
  });

  it('tags a deploy Ops Signals found in Prometheus, and explains it on hover', async () => {
    const found = { ...changes.matches[0], source: 'ops-signals:build_info', description: 'Found automatically: version changed from 1.4.1 to 1.4.2 (build_info metric).' };
    renderDrawer({ ...otlpFinding, service: 'cart', analysis_run_id: undefined, comparison_json: { breakdown }, changes: { ...changes, matches: [found] } });

    const whatChangedItem = screen.getByTestId('finding-what-changed');
    const tag = within(whatChangedItem).getByLabelText(/^Found automatically\. Ops Signals found this deploy in Prometheus: version changed from 1\.4\.1 to 1\.4\.2/);
    expect(tag).toHaveTextContent('Found automatically');
    expect(screen.getByText('After deploy v1.4.2')).toBeInTheDocument();
  });

  it('has no tag for a deploy CI sent', () => {
    renderDrawer({ ...otlpFinding, service: 'cart', analysis_run_id: undefined, comparison_json: { breakdown }, changes });
    expect(screen.queryByText('Found automatically')).not.toBeInTheDocument();
  });

  it('says no deploys were recorded instead of showing nothing', () => {
    renderDrawer({ ...otlpFinding, service: 'cart', analysis_run_id: undefined, comparison_json: { breakdown }, changes: { status: 'no_events_for_service', service: 'cart' } });

    expect(screen.getByTestId('finding-what-changed').textContent).toContain('No deploys or other changes have been recorded for cart yet.');
    expect(screen.queryByTestId('breakdown-deploy-link')).not.toBeInTheDocument();
    expect(screen.getByText(/looks like a rollout in progress/)).toBeInTheDocument();
  });

  it('renders as before when the backend sends no changes', () => {
    renderDrawer({ ...otlpFinding, analysis_run_id: undefined, comparison_json: { breakdown } });

    expect(screen.queryByTestId('finding-what-changed')).not.toBeInTheDocument();
    expect(screen.queryByText(/^After /)).not.toBeInTheDocument();
  });
});

describe('FindingDetailsDrawer seen before', () => {
  it('warns at the top when the finding is back soon after a fix', async () => {
    vi.mocked(api.analysisRun).mockResolvedValue(null as never);
    vi.mocked(api.timeseries).mockResolvedValue([]);
    vi.mocked(api.findingSeenBefore).mockResolvedValue({
      finding_id: 41, available: true, service: 'test-otlp-service', matches: [],
      came_back: { case_id: 25, title: 'CPU pinned after release', fixed_at: '2026-10-24T15:10:00', days: 3, fix: 'Rolled back the release.' },
    });

    renderDrawer(otlpFinding);

    const banner = await screen.findByTestId('fix-came-back');
    expect(banner).toHaveTextContent('This came back 3 days after it was fixed.');
    expect(within(banner).getByRole('link', { name: '#25 CPU pinned after release' })).toHaveAttribute('href', '/cases/25');
    expect(banner).toHaveTextContent('Fix then: Rolled back the release.');
    // AI status unknown here, so no AI button.
    expect(within(banner).queryByRole('button')).not.toBeInTheDocument();
  });

  it('lists past cases on the same service first, including imported postmortems', async () => {
    vi.mocked(api.analysisRun).mockResolvedValue(null as never);
    vi.mocked(api.timeseries).mockResolvedValue([]);
    vi.mocked(api.findingSeenBefore).mockResolvedValue({
      finding_id: 41,
      available: true,
      service: 'test-otlp-service',
      matches: [
        { case_id: 9, title: 'Payments CPU leak', similarity_score: 0.62, strength: 'possible', same_service: false, service: 'payments', origin: 'detected' },
        {
          case_id: 25, title: 'CPU pinned after release', similarity_score: 0.48, strength: 'possible', same_service: true,
          service: 'test-otlp-service', origin: 'imported', source: 'jira', source_id: 'OPS-101',
          root_cause_summary: 'Schema validation on every call', corrective_action: 'Cached the schema',
        },
      ],
    });

    renderDrawer(otlpFinding);

    const panel = await screen.findByTestId('seen-before');
    const rows = await within(panel).findAllByTestId('past-case-match');
    expect(rows).toHaveLength(1);
    expect(within(rows[0]).getByText('CPU pinned after release')).toHaveAttribute('href', '/cases/25');
    expect(within(rows[0]).getByText('Possible match · 48%')).toBeInTheDocument();
    expect(within(rows[0]).getByText('Imported · jira OPS-101')).toBeInTheDocument();
    expect(within(rows[0]).getByText('Cached the schema')).toBeInTheDocument();
    expect(within(panel).getByRole('button', { name: 'Show 1 match on other services' })).toBeInTheDocument();
    expect(api.findingSeenBefore).toHaveBeenCalledWith(41);
  });

  it('explains when memory is off', async () => {
    vi.mocked(api.analysisRun).mockResolvedValue(null as never);
    vi.mocked(api.timeseries).mockResolvedValue([]);
    vi.mocked(api.findingSeenBefore).mockResolvedValue({
      finding_id: 41, available: false, reason: 'Operational memory is not enabled, so past cases can\'t be searched.', matches: [],
    });

    renderDrawer(otlpFinding);

    expect(await screen.findByText(/Operational memory is not enabled/)).toBeInTheDocument();
  });

  it('shows the tested rate the card no longer shows', async () => {
    renderDrawer({
      ...otlpFinding,
      trust: {
        group: 'level_change_single', tier: 'needs_attention', badge: 'moderate', checks: ['change'],
        tested: { real: 0.67, checked: 503, random: 0.6, dataset: 'RCAEval RE1', data_kind: 'microservice', fits_metric: true },
        service: { real: 0, answered: 0, min_answers: 5 }, your_answer: null,
      },
    });

    expect(await screen.findByText('In testing')).toBeInTheDocument();
    expect(screen.getByText('67% were real')).toBeInTheDocument();
    expect(screen.getByText('503 checked in tests')).toBeInTheDocument();
  });
});

describe('FindingDetailsDrawer custom settings', () => {
  it('shows each changed setting next to its default, and who set it and why', async () => {
    vi.mocked(api.analysisRun).mockResolvedValue(undefined as never);
    vi.mocked(api.timeseries).mockResolvedValue([]);
    vi.mocked(api.findingSeenBefore).mockResolvedValue({ finding_id: 41, available: false, matches: [] } as never);
    renderDrawer({
      ...otlpFinding,
      custom_settings: {
        settings: [{ analyzer_id: 'trend', analyzer: 'Trend Analysis', path: 'finding_rules.min_slope_percent', label: 'Smallest steady climb or drop that counts', value: 5, default: 10 }],
        overrides: [{ id: 'payments_memory', file: 'payments-team.yml', reason: 'Memory grows slowly here.' }],
      },
    });

    const box = within(await screen.findByTestId('finding-custom-settings-box'));
    expect(box.getByText('Found with custom settings')).toBeInTheDocument();
    const row = box.getByText('Trend Analysis: Smallest steady climb or drop that counts').closest('tr')!;
    expect(within(row).getByText('5')).toBeInTheDocument();
    expect(within(row).getByText('10')).toBeInTheDocument();
    expect(box.getByText('Memory grows slowly here.')).toBeInTheDocument();
    expect(box.getByText('Override payments_memory in payments-team.yml')).toBeInTheDocument();
  });

  it('shows no box for a finding on the default settings', () => {
    renderDrawer(otlpFinding);
    expect(screen.queryByTestId('finding-custom-settings-box')).not.toBeInTheDocument();
  });
});
