import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { BehaviorIntelligencePage } from './BehaviorIntelligencePage';
import { api } from '../api/queries';
import type { BehaviorDefinition, BehaviorFinding, BehaviorPatternSuggestion, CatalogPattern } from '../types';

vi.mock('../api/queries', () => ({
  api: {
    behaviorDefinitions: vi.fn().mockResolvedValue([]),
    behaviorCatalog: vi.fn().mockResolvedValue([]),
    behaviorFindings: vi.fn(),
    createCaseFromBehavior: vi.fn(),
    behaviorSuggestions: vi.fn().mockResolvedValue([]),
    mineBehaviorSuggestions: vi.fn(),
    promoteBehaviorSuggestion: vi.fn(),
    dismissBehaviorSuggestion: vi.fn(),
    // Nobody signed in: nothing is locked, as on a fresh install.
    me: vi.fn().mockRejectedValue(new Error('no sign-in')),
    behaviorFacts: vi.fn().mockResolvedValue([]),
    metricAnalyzerSamples: vi.fn().mockResolvedValue([]),
    behaviorAvailableMetrics: vi.fn().mockResolvedValue([]),
    validateBehaviorDefinition: vi.fn(),
    dryRunBehaviorDefinition: vi.fn(),
    saveBehaviorDefinitionToPack: vi.fn(),
    behaviorHistoryServices: vi.fn().mockResolvedValue([]),
    behaviorHistoryPreview: vi.fn(),
  },
}));

function behavior(overrides: Partial<BehaviorFinding> = {}): BehaviorFinding {
  return {
    id: 1,
    behavior_id: 'memory-leak-1',
    definition_id: 'memory_leak',
    definition_version: 1,
    title: 'Memory leak driving resource degradation',
    summary: 'Sustained upward memory trend was accompanied by increased CPU throttling.',
    category: 'resource_constraint',
    severity: 'critical',
    service: 'payments-service',
    input_metrics_json: { memory: 'memory_usage', throttling: 'cpu_throttled_seconds' },
    facts_json: {},
    evidence_json: ['memory.trend.direction'],
    matched_conditions_json: [],
    confidence: 0.88,
    correlation_json: {},
    case_id: null,
    occurrence_count: 1,
    last_seen_at: '2026-09-08T00:00:00Z',
    created_at: '2026-09-08T00:00:00Z',
    ...overrides,
  };
}

function LocationProbe() {
  return <div data-testid="location">{useLocation().search}</div>;
}

function renderPage(url = '/') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/" element={<><BehaviorIntelligencePage /><LocationProbe /></>} />
          <Route path="/cases/:id" element={<div>Case details page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('BehaviorIntelligencePage', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('lets an uncased behavior be turned into a case and navigates to it', async () => {
    vi.mocked(api.behaviorFindings).mockResolvedValue([behavior()]);
    vi.mocked(api.createCaseFromBehavior).mockResolvedValue({
      case_id: 77,
      behavior_finding_id: 1,
      case_status: 'open',
      memory_status: 'not_indexed',
    });

    renderPage();

    const createButton = await screen.findByRole('button', { name: 'Create Case' });
    fireEvent.click(createButton);

    expect(await screen.findByText('Case details page')).toBeInTheDocument();
    expect(api.createCaseFromBehavior).toHaveBeenCalledWith(1);
  });

  it('shows a View Case link instead, once a behavior already has one', async () => {
    vi.mocked(api.behaviorFindings).mockResolvedValue([behavior({ case_id: 42 })]);

    renderPage();

    expect(await screen.findByRole('link', { name: 'View Case' })).toHaveAttribute('href', '/cases/42');
    expect(screen.queryByRole('button', { name: 'Create Case' })).not.toBeInTheDocument();
  });
});

const rule = (overrides: Partial<BehaviorDefinition> = {}): BehaviorDefinition => ({
  id: 'pool_exhaustion',
  enabled: true,
  version: 2,
  title: 'Database connection pool exhaustion',
  description: 'Detects high connection wait times.',
  scope: { service: '*' },
  inputs: [
    { alias: 'db_wait', metric_name: 'db_connection_wait_seconds', analyzers: ['trend', 'ruptures'] },
    { alias: 'db_pool', metric_name: 'db_connections_active', analyzers: ['trend'] },
  ],
  conditions: { all: [{ fact: 'db_wait.change.upward', operator: 'equals', value: true }], any: [] },
  correlation: { max_time_gap: '30m', minimum_overlap: '5m' },
  output: { category: 'resource_constraint', severity: 'critical', title: 'Database connection pool exhaustion', summary: 'Pool filling up.' },
  source_file: '/app/config/behavior_definitions.d/core.yml',
  ...overrides,
});

describe('BehaviorIntelligencePage detected tab', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('shows the selected behavior with each metric and why it matched', async () => {
    const pool = behavior({
      id: 5,
      title: 'Database connection pool exhaustion',
      definition_id: 'pool_exhaustion',
      input_metrics_json: { db_wait: 'db_connection_wait_seconds', db_pool: 'db_connections_active' },
      facts_json: {
        db_wait: { ruptures: { present: true, signed_change_percent: 131.5 } },
        db_pool: { ruptures: { present: true, signed_change_percent: 49 } },
      },
      correlation_json: { matched: true, overlap_minutes: 110 },
      last_seen_at: new Date().toISOString(),
    });
    vi.mocked(api.behaviorFindings).mockResolvedValue([behavior(), pool]);

    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: 'Database connection pool exhaustion' }));
    const metrics = within(screen.getByLabelText('Metrics in this pattern'));
    expect(metrics.getByText('db_connection_wait_seconds')).toBeInTheDocument();
    expect(metrics.getByText('+132%')).toBeInTheDocument();
    expect(screen.getByText('Both at the same time · overlapped 110 min')).toBeInTheDocument();
    expect(screen.queryByText('Direction')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'View on Findings' })).toHaveAttribute('href', '/findings?window=6h&pattern=5');
  });

  it('says a behavior last seen long ago is quiet, and that Findings no longer lists it', async () => {
    vi.mocked(api.behaviorFindings).mockResolvedValue([behavior({ last_seen_at: '2026-01-01T00:00:00Z' })]);

    renderPage();

    expect(await screen.findByText('Quiet')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'View on Findings' })).toBeDisabled();
  });

  it('explains an empty list and points to the patterns', async () => {
    vi.mocked(api.behaviorFindings).mockResolvedValue([]);
    vi.mocked(api.behaviorDefinitions).mockResolvedValue([rule()]);

    renderPage();

    expect(await screen.findByText('No behaviors detected yet')).toBeInTheDocument();
    expect(screen.getByText(/1 pattern is active/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'See the patterns' }));
    expect(await screen.findByText('Active in your setup (1)')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('?tab=patterns');
  });
});

describe('BehaviorIntelligencePage patterns tab', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('lists each pattern with what it needs and when it last fired', async () => {
    vi.mocked(api.behaviorDefinitions).mockResolvedValue([rule(), rule({ id: 'benign_maintenance', title: 'Scheduled batch maintenance', inputs: [{ alias: 'batch', metric_name: 'batch_jobs_active' }] })]);
    vi.mocked(api.behaviorFindings).mockResolvedValue([behavior({ definition_id: 'pool_exhaustion', last_seen_at: new Date().toISOString() })]);

    renderPage('/?tab=patterns');

    const table = within(await screen.findByRole('table'));
    expect(table.getByText('trend, ruptures')).toBeInTheDocument();
    expect(table.getByText('any analyzer')).toBeInTheDocument();
    expect(table.getByText('just now')).toBeInTheDocument();
    expect(table.getByText('Never')).toBeInTheDocument();
    expect(table.getAllByText('core.yml · v2')).toHaveLength(2);
  });

  it('opens a copy of a rule in the builder, and closes it again', async () => {
    vi.mocked(api.behaviorDefinitions).mockResolvedValue([rule()]);
    vi.mocked(api.behaviorFindings).mockResolvedValue([]);

    renderPage('/?tab=patterns');

    fireEvent.click(await screen.findByRole('button', { name: 'Edit copy' }));
    expect(await screen.findByText('Editing a copy of core.yml · saving never changes the original')).toBeInTheDocument();
    expect(screen.getByLabelText('Id')).toHaveValue('pool_exhaustion_copy');
    expect(screen.getByTestId('location')).toHaveTextContent('builder=rule%3Apool_exhaustion');

    fireEvent.click(screen.getByRole('button', { name: 'Close builder' }));
    expect(screen.getByTestId('location')).not.toHaveTextContent('builder');
  });

  it('turns a suggestion into a pattern in the builder', async () => {
    const suggestion: BehaviorPatternSuggestion = {
      id: 9,
      service: 'checkout-api',
      metric_a: 'request_latency_p95',
      metric_b: 'error_rate',
      co_occurrence_count: 4,
      metric_a_occasions: 5,
      metric_b_occasions: 6,
      correlation_strength: 0.8,
      sample_analysis_run_ids: [],
      draft_definition_json: {
        id: 'suggested_latency_errors',
        title: 'Latency with errors',
        inputs: [{ alias: 'a', metric_name: 'request_latency_p95' }, { alias: 'b', metric_name: 'error_rate' }],
        conditions: { all: [{ fact: 'a.anomaly.present', operator: 'equals', value: true }] },
        correlation: { max_time_gap: '10m' },
        output: { severity: 'medium', title: 'Latency with errors' },
      },
      draft_yaml_text: '',
      status: 'pending',
      created_at: '2026-10-21T00:00:00Z',
    };
    vi.mocked(api.behaviorDefinitions).mockResolvedValue([]);
    vi.mocked(api.behaviorFindings).mockResolvedValue([]);
    vi.mocked(api.behaviorSuggestions).mockResolvedValue([suggestion]);

    renderPage('/?tab=patterns');

    fireEvent.click(await screen.findByRole('button', { name: 'Turn into pattern' }));
    expect(await screen.findByText('From a suggestion on checkout-api')).toBeInTheDocument();
    expect(screen.getByLabelText('Id')).toHaveValue('suggested_latency_errors');
  });

  it('opens a blank builder from the old Lab link target', async () => {
    vi.mocked(api.behaviorFindings).mockResolvedValue([]);

    renderPage('/?tab=patterns&builder=new');

    expect(await screen.findByRole('button', { name: 'Close builder' })).toBeInTheDocument();
    expect(screen.getByLabelText('Id')).toHaveValue('');
  });

  it('lets a viewer see the patterns but not change them', async () => {
    vi.mocked(api.me).mockResolvedValue({ signed_in: true, name: 'v', role: 'Viewer', via: 'proxy', groups: [], granted_by: null, mode: 'proxy', problem: null });
    vi.mocked(api.behaviorDefinitions).mockResolvedValue([rule()]);
    vi.mocked(api.behaviorFindings).mockResolvedValue([]);

    renderPage('/?tab=patterns&builder=new');

    expect(await screen.findByText('You can see every pattern. Ask an Ops Signals admin to add or change one.')).toBeInTheDocument();
    expect(screen.getByText('Database connection pool exhaustion')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Edit copy' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'New pattern' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Close builder' })).not.toBeInTheDocument();
  });
});

const consumerTemplate: CatalogPattern = {
  key: 'consumer_falling_behind',
  rule: null,
  name: 'Consumer falling behind',
  area: 'Queues',
  meaning: 'Messages arrive faster than your consumers can process them.',
  why: 'Lag jumps during every traffic burst and then clears.',
  check_first: 'Consumer restarts or rebalances.',
  proof: 'common',
  scenarios: [],
  signals: [
    { alias: 'lag', label: 'Consumer lag rising', shape: 'rising', metric_hint: 'consumer_lag', keywords: ['consumer', 'lag'], analyzers: ['trend', 'baseline_shift', 'ruptures'] },
    { alias: 'produced', label: 'Incoming messages rising', shape: 'rising', metric_hint: 'messages_in_rate', keywords: ['messages', 'incoming'], analyzers: ['trend', 'baseline_shift', 'ruptures'] },
  ],
  draft: {
    id: 'consumer_falling_behind',
    title: 'Consumer falling behind',
    inputs: [
      { alias: 'lag', metric_name: 'consumer_lag', analyzers: ['trend', 'baseline_shift', 'ruptures'] },
      { alias: 'produced', metric_name: 'messages_in_rate', analyzers: ['trend', 'baseline_shift', 'ruptures'] },
    ],
    conditions: { all: [{ fact: 'lag.change.upward', operator: 'equals', value: true }, { fact: 'produced.change.upward', operator: 'equals', value: true }], any: [] },
    correlation: { max_time_gap: '30m', minimum_overlap: '5m' },
    output: { severity: 'high', title: 'Consumer falling behind' },
  },
};
const diskTemplate: CatalogPattern = { ...consumerTemplate, key: 'disk_filling_up', name: 'Disk filling up', area: 'Storage' };

describe('BehaviorIntelligencePage known patterns', () => {
  beforeEach(() => {
    // Back to nobody signed in: an earlier test signs in a viewer, and clearAllMocks keeps that.
    vi.mocked(api.me).mockRejectedValue(new Error('no sign-in'));
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('shows each shipped rule with its proof', async () => {
    vi.mocked(api.behaviorDefinitions).mockResolvedValue([rule(), rule({ id: 'server_slow', title: 'Possible server performance degradation' })]);
    vi.mocked(api.behaviorFindings).mockResolvedValue([]);
    vi.mocked(api.behaviorCatalog).mockResolvedValue([
      { ...consumerTemplate, key: 'server_slow', rule: 'server_slow', proof: 'tested', scenarios: ['behavior_server_slow_v1'], signals: [], draft: null },
      { ...consumerTemplate, key: 'pool_exhaustion', rule: 'pool_exhaustion', proof: 'shipped', signals: [], draft: null },
    ]);

    renderPage('/?tab=patterns');

    const table = within(await screen.findByRole('table'));
    expect(await table.findByText('Tested here')).toBeInTheDocument();
    expect(table.getByText('Shipped rule')).toBeInTheDocument();
    expect(screen.queryByText('Start from a known pattern')).not.toBeInTheDocument();
  });

  it('lists templates by area and opens one in the builder to pick metrics', async () => {
    vi.mocked(api.behaviorDefinitions).mockResolvedValue([]);
    vi.mocked(api.behaviorFindings).mockResolvedValue([]);
    vi.mocked(api.behaviorCatalog).mockResolvedValue([consumerTemplate, diskTemplate]);
    vi.mocked(api.behaviorAvailableMetrics).mockResolvedValue(['kafka_consumergroup_lag', 'kafka_topic_messages_in_rate', 'cpu_usage']);

    renderPage('/?tab=patterns');

    expect(await screen.findByText('Start from a known pattern')).toBeInTheDocument();
    expect(screen.getByText('Disk filling up')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Queues' }));
    expect(screen.queryByText('Disk filling up')).not.toBeInTheDocument();
    expect(within(screen.getByLabelText('Signals of Consumer falling behind')).getByText('Consumer lag rising')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Use this pattern' }));
    expect(await screen.findByText('From the known pattern “Consumer falling behind” · pick your metric for each signal')).toBeInTheDocument();
    expect(screen.getByLabelText('Id')).toHaveValue('consumer_falling_behind');
    expect(screen.getByTestId('location')).toHaveTextContent('builder=catalog%3Aconsumer_falling_behind');

    // Both signals start on a generic name: the test waits until each points at a stored metric.
    expect(await screen.findByText('Pick your metric for Consumer lag rising, Incoming messages rising first (step 2).')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'kafka_consumergroup_lag' }));
    fireEvent.click(screen.getByRole('button', { name: 'kafka_topic_messages_in_rate' }));
    expect(screen.getAllByText('Matched to a metric Ops Signals has stored.')).toHaveLength(2);
    expect(screen.queryByText(/Pick your metric for/)).not.toBeInTheDocument();
  });

  it('shows a viewer the templates without Use this pattern', async () => {
    vi.mocked(api.me).mockResolvedValue({ signed_in: true, name: 'v', role: 'Viewer', via: 'proxy', groups: [], granted_by: null, mode: 'proxy', problem: null });
    vi.mocked(api.behaviorDefinitions).mockResolvedValue([]);
    vi.mocked(api.behaviorFindings).mockResolvedValue([]);
    vi.mocked(api.behaviorCatalog).mockResolvedValue([consumerTemplate]);

    renderPage('/?tab=patterns');

    expect(await screen.findByText('Consumer falling behind')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Use this pattern' })).not.toBeInTheDocument();
  });
});
