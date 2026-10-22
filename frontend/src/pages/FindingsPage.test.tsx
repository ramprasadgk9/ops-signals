import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { FindingsPage } from './FindingsPage';
import { api } from '../api/queries';
import type { BehaviorFinding, Finding, FindingTrust } from '../types';

vi.mock('../api/queries', () => ({
  api: {
    findings: vi.fn(),
    overviewSummary: vi.fn(),
    signalsByRunIds: vi.fn(),
    getFinding: vi.fn(),
    analysisRun: vi.fn(),
    timeseries: vi.fn(),
    alerts: vi.fn(),
    metricUsageLookup: vi.fn(),
    findingFeedback: vi.fn(),
    behaviorFindings: vi.fn(),
  },
}));

const finding: Finding = {
  id: 7,
  service: 'checkout-api',
  metric_name: 'latency_p95',
  title: 'Latency shift on checkout-api',
  summary: 'p95 up',
  category: 'behavior_change',
  health_status: 'critical',
  importance_score: 0.9,
  investigation_priority: 1,
  signal_ids: [],
  comparison_json: {},
  created_at: '2026-09-20T00:00:00Z',
};

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.search}</div>;
}

function renderAt(url: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/findings" element={<><FindingsPage /><LocationProbe /></>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('FindingsPage deep link', () => {
  beforeEach(() => {
    // An older finding: outside the 24h list, which is exactly why the deep link fetches it itself.
    vi.mocked(api.findings).mockResolvedValue([]);
    vi.mocked(api.overviewSummary).mockResolvedValue({
      generated_at: '2026-09-26T00:00:00Z',
      window: '24h',
      active_findings: 0,
      open_cases: 0,
      behavior_changes: 0,
      impacted_services: 0,
      memory_items: 0,
      severity_trend: [],
      category_breakdown: [],
    });
    vi.mocked(api.alerts).mockResolvedValue([]);
    vi.mocked(api.metricUsageLookup).mockResolvedValue({});
    vi.mocked(api.behaviorFindings).mockResolvedValue([]);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('opens the linked finding and drops the parameter when the drawer closes', async () => {
    vi.mocked(api.getFinding).mockResolvedValue(finding);

    renderAt('/findings?finding=7');

    expect(await screen.findByRole('heading', { name: 'Latency shift on checkout-api' })).toBeInTheDocument();
    expect(api.getFinding).toHaveBeenCalledWith(7);

    fireEvent.keyDown(screen.getByRole('presentation'), { key: 'Escape' });
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(/^$/));
  });

  it('says so when the linked finding does not exist, and still shows the list', async () => {
    vi.mocked(api.getFinding).mockRejectedValue(new Error('404'));

    renderAt('/findings?finding=999');

    expect(await screen.findByText('Finding #999 could not be found.')).toBeInTheDocument();
    expect(screen.getByText('No findings returned for this window.')).toBeInTheDocument();
  });

  it('ignores a malformed finding parameter', async () => {
    renderAt('/findings?finding=abc');

    expect(await screen.findByText('No findings returned for this window.')).toBeInTheDocument();
    expect(api.getFinding).not.toHaveBeenCalled();
  });
});

describe('FindingsPage category legend', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('explains each category in plain words', async () => {
    vi.mocked(api.findings).mockResolvedValue([]);
    vi.mocked(api.alerts).mockResolvedValue([]);
    vi.mocked(api.overviewSummary).mockResolvedValue({
      generated_at: '2026-09-26T00:00:00Z',
      window: '24h',
      active_findings: 3,
      open_cases: 0,
      behavior_changes: 1,
      impacted_services: 1,
      memory_items: 0,
      severity_trend: [],
      category_breakdown: [
        { category: 'data_quality', count: 679 },
        { category: 'behavior_change', count: 168 },
        { category: 'unusual_activity', count: 108 },
      ],
    });

    renderAt('/findings');

    expect(await screen.findByText('Data Quality')).toBeInTheDocument();
    expect(screen.getByText('The metric stopped reporting or froze at one value')).toBeInTheDocument();
    expect(screen.getByText('The metric moved to a new normal level, or is steadily trending')).toBeInTheDocument();
    expect(screen.getByText('Short spikes or dips that don’t fit the usual pattern')).toBeInTheDocument();
  });
});

describe('FindingsPage cluster filter', () => {
  const inCluster = (id: number, cluster: string | null): Finding => ({ ...finding, id, cluster, title: `Latency shift in ${cluster ?? 'single cluster'}` });

  beforeEach(() => {
    vi.mocked(api.overviewSummary).mockResolvedValue({
      generated_at: '2026-09-26T00:00:00Z',
      window: '24h',
      active_findings: 2,
      open_cases: 0,
      behavior_changes: 0,
      impacted_services: 1,
      memory_items: 0,
      severity_trend: [],
      category_breakdown: [],
    });
    vi.mocked(api.alerts).mockResolvedValue([]);
    vi.mocked(api.signalsByRunIds).mockResolvedValue([]);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('shows each cluster on its finding and filters by cluster', async () => {
    vi.mocked(api.findings).mockResolvedValue([inCluster(1, 'eu'), inCluster(2, 'us')]);

    renderAt('/findings');

    expect(await screen.findByText('checkout-api · latency_p95 · eu')).toBeInTheDocument();
    expect(screen.getByText('checkout-api · latency_p95 · us')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'us' }));

    await waitFor(() => expect(screen.queryByText('Latency shift in eu')).not.toBeInTheDocument());
    expect(screen.getByText('Latency shift in us')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('cluster=us');

    fireEvent.click(screen.getByRole('button', { name: 'All clusters' }));
    expect(await screen.findByText('Latency shift in eu')).toBeInTheDocument();
  });

  it('hides the cluster filter for single-cluster data', async () => {
    vi.mocked(api.findings).mockResolvedValue([inCluster(1, null)]);

    renderAt('/findings');

    expect(await screen.findByText('checkout-api · latency_p95')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'All clusters' })).not.toBeInTheDocument();
  });
});

describe('FindingsPage source filter', () => {
  const from = (id: number, source: string | null): Finding => ({ ...finding, id, source, title: `Shift from ${source ?? 'unknown'}` });

  beforeEach(() => {
    vi.mocked(api.overviewSummary).mockResolvedValue({
      generated_at: '2026-09-26T00:00:00Z',
      window: '24h',
      active_findings: 2,
      open_cases: 0,
      behavior_changes: 0,
      impacted_services: 1,
      memory_items: 0,
      severity_trend: [],
      category_breakdown: [],
    });
    vi.mocked(api.alerts).mockResolvedValue([]);
    vi.mocked(api.signalsByRunIds).mockResolvedValue([]);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('marks findings that did not come from Prometheus and filters by source', async () => {
    vi.mocked(api.findings).mockResolvedValue([from(1, 'prometheus'), from(2, 'otlp')]);

    renderAt('/findings');

    expect(await screen.findByText('checkout-api · latency_p95 · via OTLP')).toBeInTheDocument();
    expect(screen.getByText('checkout-api · latency_p95')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'OTLP' }));

    await waitFor(() => expect(screen.queryByText('Shift from prometheus')).not.toBeInTheDocument());
    expect(screen.getByText('Shift from otlp')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('source=otlp');

    fireEvent.click(screen.getByRole('button', { name: 'All sources' }));
    expect(await screen.findByText('Shift from prometheus')).toBeInTheDocument();
  });

  it('hides the source filter when every finding has the same source', async () => {
    vi.mocked(api.findings).mockResolvedValue([from(1, 'otlp'), from(2, 'otlp')]);

    renderAt('/findings');

    expect(await screen.findByText('Shift from otlp')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'All sources' })).not.toBeInTheDocument();
  });
});

describe('FindingsPage search and sort', () => {
  const make = (id: number, service: string, metric: string, createdAt: string, importance: number): Finding => ({
    ...finding, id, service, metric_name: metric, title: `Finding ${id}`, created_at: createdAt, importance_score: importance,
  });

  beforeEach(() => {
    vi.mocked(api.overviewSummary).mockResolvedValue({
      generated_at: '2026-09-26T00:00:00Z',
      window: '24h',
      active_findings: 0,
      open_cases: 0,
      behavior_changes: 0,
      impacted_services: 0,
      memory_items: 0,
      severity_trend: [],
      category_breakdown: [],
    });
    vi.mocked(api.alerts).mockResolvedValue([]);
    vi.mocked(api.signalsByRunIds).mockResolvedValue([]);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  const titles = () => screen.getAllByText(/^Finding \d+$/).map((element) => element.textContent);

  it('lists the latest first, and sorts by importance on request', async () => {
    vi.mocked(api.findings).mockResolvedValue([
      make(1, 'checkout', 'cpu_usage', '2026-10-04T08:00:00Z', 0.9),
      make(2, 'payments', 'error_rate', '2026-10-04T10:00:00Z', 0.2),
      make(3, 'search', 'request_latency_p95', '2026-10-04T09:00:00Z', 0.5),
    ]);

    renderAt('/findings');

    await screen.findByText('Finding 1');
    expect(titles()).toEqual(['Finding 2', 'Finding 3', 'Finding 1']);

    fireEvent.mouseDown(screen.getByRole('combobox', { name: 'Sort by' }));
    fireEvent.click(await screen.findByRole('option', { name: 'Most important' }));

    await waitFor(() => expect(titles()).toEqual(['Finding 1', 'Finding 3', 'Finding 2']));
    expect(screen.getByTestId('location')).toHaveTextContent('sort=importance');
  });

  it('searches by service, metric or finding number and keeps the search in the URL', async () => {
    vi.mocked(api.findings).mockResolvedValue([
      make(1, 'checkout', 'cpu_usage', '2026-10-04T08:00:00Z', 0.9),
      make(57, 'checkout', 'request_latency_p95', '2026-10-04T10:00:00Z', 0.2),
      make(3, 'payments', 'error_rate', '2026-10-04T09:00:00Z', 0.5),
    ]);

    renderAt('/findings');
    const search = await screen.findByRole('textbox', { name: 'Search findings' });

    fireEvent.change(search, { target: { value: 'checkout' } });
    await waitFor(() => expect(titles()).toEqual(['Finding 57', 'Finding 1']));
    expect(screen.getByText('Showing 2 of 2 · 3 in window')).toBeInTheDocument();

    fireEvent.change(search, { target: { value: 'latency' } });
    await waitFor(() => expect(titles()).toEqual(['Finding 57']));

    fireEvent.change(search, { target: { value: '#57' } });
    await waitFor(() => expect(titles()).toEqual(['Finding 57']));
    expect(screen.getByTestId('location')).toHaveTextContent('q=%2357');
  });

  it('offers to open a finding number that is outside the window', async () => {
    vi.mocked(api.findings).mockResolvedValue([make(1, 'checkout', 'cpu_usage', '2026-10-04T08:00:00Z', 0.9)]);
    vi.mocked(api.getFinding).mockResolvedValue({ ...finding, id: 400, title: 'An older finding' });

    renderAt('/findings?q=%23400');

    expect(await screen.findByText('No findings in this window match "#400".')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Open finding #400' }));

    expect(await screen.findByRole('heading', { name: 'An older finding' })).toBeInTheDocument();
    expect(api.getFinding).toHaveBeenCalledWith(400);
  });

  it('shows a finding repeated across runs once, and lists each run on request', async () => {
    const repeat = (id: number, createdAt: string): Finding => ({
      ...finding, id, service: 'checkout', metric_name: 'request_latency_p95', cluster: 'eu', title: 'Latency trending up', created_at: createdAt,
    });
    vi.mocked(api.findings).mockResolvedValue([
      repeat(1, '2026-10-04T08:00:00Z'),
      repeat(2, '2026-10-04T10:00:00Z'),
      repeat(3, '2026-10-04T09:00:00Z'),
      make(4, 'payments', 'error_rate', '2026-10-04T07:00:00Z', 0.5),
    ]);

    renderAt('/findings');

    expect(await screen.findByText('Seen in 3 runs')).toBeInTheDocument();
    expect(screen.getAllByText('Latency trending up')).toHaveLength(1);
    expect(screen.getByText('Showing 2 of 2 (4 findings, repeats grouped)')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Seen in 3 runs'));

    await waitFor(() => expect(screen.getAllByText('Latency trending up')).toHaveLength(3));
    expect(screen.queryByText('Finding 4')).not.toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('group=off');
    expect(screen.getByRole('checkbox', { name: 'Group repeats' })).not.toBeChecked();

    fireEvent.click(screen.getByRole('checkbox', { name: 'Group repeats' }));
    await waitFor(() => expect(screen.getAllByText('Latency trending up')).toHaveLength(1));
  });

  it('shows every finding, a page at a time', async () => {
    vi.mocked(api.findings).mockResolvedValue(
      Array.from({ length: 25 }, (_, index) => make(index + 1, 'checkout', 'cpu_usage', `2026-10-04T${String(index % 24).padStart(2, '0')}:00:00Z`, 0.5)),
    );

    renderAt('/findings');

    expect(await screen.findByText('Showing 20 of 25')).toBeInTheDocument();
    expect(titles()).toHaveLength(20);
    fireEvent.click(screen.getByRole('button', { name: 'Show 5 more' }));
    await waitFor(() => expect(titles()).toHaveLength(25));
    expect(screen.queryByRole('button', { name: /more$/ })).not.toBeInTheDocument();
  });
});

describe('FindingsPage metric usage tag', () => {
  it('tags each finding with whether a dashboard or alert watches its metric', async () => {
    vi.mocked(api.findings).mockResolvedValue([finding]);
    vi.mocked(api.overviewSummary).mockResolvedValue({
      generated_at: '2026-09-26T00:00:00Z', window: '24h', active_findings: 1, open_cases: 0, behavior_changes: 0,
      impacted_services: 1, memory_items: 0, severity_trend: [], category_breakdown: [],
    });
    vi.mocked(api.alerts).mockResolvedValue([]);
    vi.mocked(api.metricUsageLookup).mockResolvedValue({
      latency_p95: {
        metric: 'latency_p95', status: 'blind_spot', connections: ['default'], usages: [], via_recording_rules: [],
        problem_findings: 3, latest_finding_id: 7, analyzed: true, series: null,
      },
    });
    renderAt('/findings');

    expect(await screen.findByText('Not on any dashboard or alert')).toBeInTheDocument();
    expect(api.metricUsageLookup).toHaveBeenCalledWith(['latency_p95']);
  });
});

describe('FindingsPage trust', () => {
  const trust = (overrides: Partial<FindingTrust>): FindingTrust => ({
    group: 'level_change_agree', tier: 'needs_attention', badge: 'strong', checks: ['change', 'pyod_outlier'],
    tested: { real: 0.91, checked: 266, random: 0.6, dataset: 'RCAEval RE1', data_kind: 'microservice', fits_metric: true, measured_at: '2026-10-08' },
    service: { real: 0, answered: 0, min_answers: 5 }, your_answer: null, ...overrides,
  });

  beforeEach(() => {
    vi.mocked(api.overviewSummary).mockResolvedValue({
      generated_at: '2026-09-26T00:00:00Z', window: '24h', active_findings: 2, open_cases: 0, behavior_changes: 0,
      impacted_services: 1, memory_items: 0, severity_trend: [], category_breakdown: [],
    });
    vi.mocked(api.alerts).mockResolvedValue([]);
    vi.mocked(api.metricUsageLookup).mockResolvedValue({});
    vi.mocked(api.findings).mockResolvedValue([
      { ...finding, id: 1, title: 'Latency moved to a new level', trust: trust({}) },
      {
        ...finding, id: 2, title: 'CPU looked unusual', category: 'unusual_activity',
        trust: trust({ group: 'spike', tier: 'context', badge: null, checks: ['pyod_outlier'], tested: null }),
      },
    ]);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('lists findings that need attention with their tested rate, and folds context away', async () => {
    renderAt('/findings');

    expect(await screen.findByText('Latency moved to a new level')).toBeInTheDocument();
    expect(screen.getByText('Strong evidence')).toBeInTheDocument();
    expect(screen.getByText('91% were real')).toBeInTheDocument();
    expect(screen.getByText('266 checked in tests')).toBeInTheDocument();
    expect(screen.getByText('Not yet')).toBeInTheDocument();
    expect(screen.getByText('Showing 1 of 1 · 1 context only')).toBeInTheDocument();
    expect(screen.queryByText('CPU looked unusual')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Context only \(1\)/ }));

    expect(await screen.findByText('CPU looked unusual')).toBeInTheDocument();
    // A context finding can be answered, but shows no tested rate: it was no better than chance.
    expect(screen.getAllByText('91% were real')).toHaveLength(1);
    expect(screen.getAllByText('Was this real?')).toHaveLength(2);
  });

  it('saves the answer to "Was this real?"', async () => {
    vi.mocked(api.findingFeedback).mockResolvedValue({ ...finding, id: 1 });
    renderAt('/findings');

    await screen.findByText('Latency moved to a new level');
    fireEvent.click(screen.getByRole('button', { name: 'Real problem' }));

    await waitFor(() => expect(api.findingFeedback).toHaveBeenCalledWith(1, 'real_problem'));
  });

  it('lists a kind of finding the team confirmed under Needs attention, saying why', async () => {
    vi.mocked(api.findings).mockResolvedValue([
      {
        ...finding, id: 3, title: 'CPU looked unusual on checkout', category: 'unusual_activity',
        trust: trust({ group: 'spike', tier: 'needs_attention', badge: 'team_confirmed', moved: 'up', tested: null, service: { real: 4, answered: 6, min_answers: 5 } }),
      },
    ]);
    renderAt('/findings');

    expect(await screen.findByText('CPU looked unusual on checkout')).toBeInTheDocument();
    expect(screen.getByText('Confirmed by your team')).toBeInTheDocument();
    expect(screen.getByText('Moved to Needs attention: your team said 4 of 6 findings like this on checkout-api were real.')).toBeInTheDocument();
    expect(screen.getByText('4 of 6 were real')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Context only/ })).not.toBeInTheDocument();
  });
});

describe('FindingsPage combined patterns', () => {
  const emptySummary = {
    generated_at: '2026-10-21T00:00:00Z',
    window: '24h' as const,
    active_findings: 2,
    open_cases: 0,
    behavior_changes: 1,
    impacted_services: 1,
    memory_items: 0,
    severity_trend: [],
    category_breakdown: [],
  };
  const trend = (change: number) => ({
    trend: { present: true, direction: 'upward', change_percent: change },
    baseline_shift: { present: false },
    ruptures: { present: false },
    anomaly: { present: false },
    signal: { window_start: null, window_end: null },
  });
  const pool = (extra: Partial<BehaviorFinding> = {}): BehaviorFinding => ({
    id: 3,
    behavior_id: 'pool_exhaustion:1:run-1',
    definition_id: 'pool_exhaustion',
    definition_version: 1,
    title: 'Database connection pool exhaustion',
    summary: 'Database connection pool reached saturation with surging connection wait times.',
    category: 'resource_constraint',
    severity: 'critical',
    service: 'checkout-api',
    analysis_run_id: 'run-1',
    input_metrics_json: { db_wait: 'db_connection_wait_seconds', db_pool: 'db_connections_active' },
    facts_json: { db_wait: trend(85), db_pool: trend(40) },
    evidence_json: [],
    matched_conditions_json: [{ passed: true }, { passed: true }],
    confidence: 1,
    correlation_json: { matched: true, overlap_minutes: 35 },
    case_id: null,
    occurrence_count: 1,
    last_seen_at: new Date().toISOString(),
    created_at: new Date().toISOString(),
    ...extra,
  });
  const waitFinding: Finding = { ...finding, id: 11, metric_name: 'db_connection_wait_seconds', title: 'Wait time is climbing', analysis_run_id: 'run-1' };
  const otherFinding: Finding = { ...finding, id: 12, metric_name: 'cpu_usage', title: 'CPU is climbing', analysis_run_id: 'run-1' };

  beforeEach(() => {
    vi.mocked(api.findings).mockResolvedValue([waitFinding, otherFinding]);
    vi.mocked(api.overviewSummary).mockResolvedValue(emptySummary);
    vi.mocked(api.signalsByRunIds).mockResolvedValue([]);
    vi.mocked(api.alerts).mockResolvedValue([]);
    vi.mocked(api.metricUsageLookup).mockResolvedValue({});
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('shows the pattern with each metric, why it matched, and tags the finding it was made from', async () => {
    vi.mocked(api.behaviorFindings).mockResolvedValue([pool()]);

    renderAt('/findings');

    expect(await screen.findByText('Combined patterns (1)')).toBeInTheDocument();
    expect(screen.getByText('Combined pattern · 2 metrics')).toBeInTheDocument();
    const metrics = within(screen.getByLabelText('Metrics in this pattern'));
    expect(metrics.getByText('db_connection_wait_seconds')).toBeInTheDocument();
    expect(metrics.getByText('db_connections_active')).toBeInTheDocument();
    expect(metrics.getAllByText('Slowly rising')).toHaveLength(2);
    expect(metrics.getByText('+85%')).toBeInTheDocument();
    expect(screen.getByText('Both at the same time · overlapped 35 min')).toBeInTheDocument();
    expect(screen.getByText('2 of 2 conditions passed')).toBeInTheDocument();
    expect(screen.getByText('Made from these 1 findings')).toBeInTheDocument();
    // Only the finding on one of the rule's metrics carries the tag.
    expect(screen.getAllByText('Part of: Database connection pool exhaustion')).toHaveLength(1);
  });

  it('leaves out patterns last seen before the window', async () => {
    vi.mocked(api.behaviorFindings).mockResolvedValue([pool({ id: 4, last_seen_at: '2026-01-01T00:00:00Z' })]);
    renderAt('/findings');
    expect(await screen.findByText('Wait time is climbing')).toBeInTheDocument();
    expect(screen.queryByText(/Combined patterns/)).not.toBeInTheDocument();
  });

  it('hides patterns the search does not match', async () => {
    vi.mocked(api.behaviorFindings).mockResolvedValue([pool()]);
    renderAt('/findings?q=payments');
    expect(await screen.findByText('No findings in this window match "payments".')).toBeInTheDocument();
    expect(screen.queryByText(/Combined patterns/)).not.toBeInTheDocument();
  });

  it('shows only Behavior Intelligence findings, and keeps the choice in the URL', async () => {
    vi.mocked(api.behaviorFindings).mockResolvedValue([pool()]);
    renderAt('/findings');

    expect(await screen.findByText('CPU is climbing')).toBeInTheDocument();
    fireEvent.click(within(screen.getByLabelText('Filter by kind')).getByText('Behavior Intelligence'));

    await waitFor(() => expect(screen.queryByText('CPU is climbing')).not.toBeInTheDocument());
    // The card in the list plus the pattern's "Made from" chip.
    expect(screen.getAllByText('Wait time is climbing')).toHaveLength(2);
    expect(screen.getByText('Combined patterns (1)')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('only=patterns');
  });

  it('finds a pattern and its findings by the rule id', async () => {
    vi.mocked(api.behaviorFindings).mockResolvedValue([pool()]);
    renderAt('/findings?q=pool_exhaustion');
    expect(await screen.findByText('Combined patterns (1)')).toBeInTheDocument();
    // The findings it was made from match too: the card in the list plus the "Made from" chip.
    expect(screen.getAllByText('Wait time is climbing')).toHaveLength(2);
    expect(screen.queryByText('CPU is climbing')).not.toBeInTheDocument();
  });

  it('hides the kind filter when no finding is part of a pattern', async () => {
    vi.mocked(api.behaviorFindings).mockResolvedValue([]);
    renderAt('/findings');
    expect(await screen.findByText('Wait time is climbing')).toBeInTheDocument();
    expect(screen.queryByLabelText('Filter by kind')).not.toBeInTheDocument();
  });

  it('renders the page as before when the behaviors read fails', async () => {
    vi.mocked(api.behaviorFindings).mockRejectedValue(new Error('down'));
    renderAt('/findings');
    expect(await screen.findByText('Wait time is climbing')).toBeInTheDocument();
    expect(screen.queryByText(/Combined patterns/)).not.toBeInTheDocument();
  });
});
