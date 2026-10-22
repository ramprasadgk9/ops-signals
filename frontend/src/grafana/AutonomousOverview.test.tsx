import React, { useState } from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { buildAutonomousDashboardData } from '../autonomous/dashboardModel';
import type { BehaviorFinding, Finding, FindingTrust } from '../types';
import { getCase, listCases, listPrometheusConnections } from './backendClient';
import type { GrafanaCase } from './contracts';
import { GrafanaAutonomousOverview } from './PluginApp';

// PluginApp's Prometheus query path imports @grafana/* (only loadable inside Grafana).
vi.mock('./grafanaPrometheus', () => ({}));
vi.mock('./prometheusFrameNormalizer', () => ({}));
vi.mock('./backendClient', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./backendClient')>()),
  listCases: vi.fn(),
  getCase: vi.fn(),
  listPrometheusConnections: vi.fn(),
  getTicketingStatus: vi.fn(() => Promise.resolve({ enabled: false })),
  getCaseTicket: vi.fn(() => Promise.reject(new Error('none'))),
  getFindingSeenBefore: vi.fn(() => new Promise(() => undefined)),
}));
const cases = vi.mocked(listCases);
const loadCase = vi.mocked(getCase);
const connections = vi.mocked(listPrometheusConnections);

function trust(group: FindingTrust['group'], tier: FindingTrust['tier'], badge: FindingTrust['badge']): FindingTrust {
  return { group, tier, badge, moved: null, checks: [], tested: null, service: { real: 0, answered: 0, min_answers: 5 }, your_answer: null };
}

function finding(overrides: Partial<Finding>): Finding {
  return {
    id: 1,
    service: 'trend-lab',
    metric_name: 'error_rate',
    title: 'error_rate experienced a persistent baseline shift',
    summary: 'A structural change was detected.',
    category: 'behavior_change',
    health_status: 'warning',
    importance_score: 0.5,
    investigation_priority: 1,
    signal_ids: [],
    comparison_json: {},
    analysis_run_id: 'run-1',
    created_at: '2026-10-09T05:00:00Z',
    ...overrides,
  };
}

const SHIFT = trust('level_change_agree', 'needs_attention', 'strong');
// Shaped like the real trend-lab data: error_rate stepped up (seen in two runs, still showing), also
// stopped reporting and showed a weak pattern; p95 latency stepped up earlier; cpu only trended.
const FINDINGS = [
  finding({ id: 6523, importance_score: 0.88, trust: SHIFT, created_at: '2026-10-09T05:00:00Z', comparison_json: { previous_mean: 0.006, current_mean: 0.0463, change_percent: 671.06 } }),
  finding({ id: 6400, importance_score: 0.8, trust: SHIFT, analysis_run_id: 'run-0', created_at: '2026-10-08T17:30:00Z' }),
  finding({ id: 6501, title: 'error_rate stopped reporting data', category: 'data_quality', importance_score: 0.84, trust: trust('data_problem', 'needs_attention', 'data_problem') }),
  finding({ id: 6502, title: 'error_rate has unusual activity', importance_score: 0.84, trust: trust('pattern', 'context', null) }),
  finding({ id: 6519, metric_name: 'p95_latency_ms', title: 'p95_latency_ms experienced a persistent baseline shift', importance_score: 0.81, trust: trust('level_change_single', 'needs_attention', 'moderate'), created_at: '2026-10-09T01:00:00Z', comparison_json: { previous_mean: 388, current_mean: 417, change_percent: 7.39 } }),
  finding({ id: 6511, metric_name: 'cpu_usage', title: 'cpu_usage is trending in one direction.', importance_score: 0.66, trust: trust('pattern', 'context', null) }),
];

function grafanaCase(id: number, findingId: number): GrafanaCase {
  return {
    id, finding_id: findingId, analysis_run_id: 'run-1', case_title: `Case for ${findingId}`, case_status: 'open',
    finding_snapshot: { id: findingId, service: 'trend-lab', metric_name: 'error_rate', title: `Case for ${findingId}` },
    investigation_status: 'not_started', investigation_notes: [], root_cause_status: 'unknown', root_cause_summary: null,
    root_cause_confidence: null, root_cause_verified: false, corrective_action: null, outcome_status: 'pending',
    outcome_summary: null, memory_status: 'not_indexed', created_at: '2026-10-09T02:00:00Z', updated_at: '2026-10-09T02:00:00Z', resolved_at: null,
  };
}

function Harness({ onCreateCase, findings = FINDINGS, onInvestigateInteractive = () => undefined, clusters, onClusterFilter, behaviorFindings = [] }: {
  onCreateCase: (finding: Finding) => Promise<number | null>;
  behaviorFindings?: BehaviorFinding[];
  findings?: Finding[];
  onInvestigateInteractive?: (finding: Finding) => void;
  clusters?: string[];
  onClusterFilter?: (cluster: string | null) => void;
}) {
  const [open, setOpen] = useState<Finding | null>(null);
  const data = buildAutonomousDashboardData({ findings, cases: [], analysisRuns: [] });
  const noop = () => undefined;
  return (
    <GrafanaAutonomousOverview
      backendUrl="http://backend"
      data={data}
      findings={findings}
      clusters={clusters}
      clusterFilter={null}
      onClusterFilter={onClusterFilter}
      behaviorFindings={behaviorFindings}
      state="ready"
      context={{}}
      endpointErrors={[]}
      onRetry={noop}
      investigationFinding={open}
      investigationMode="investigate"
      caseError=""
      isCreatingCase={false}
      askState={{ question: '', answer: null, isLoading: false, error: '', setQuestion: noop, ask: async () => undefined }}
      findingsLookupState={{
        window: '24h', query: '', service: '', metricName: '', findings: [], isLoading: false, error: '',
        setWindow: noop, setQuery: noop, setService: noop, setMetricName: noop, search: async () => undefined, askAboutFinding: async () => undefined,
      }}
      onOpenInvestigation={(next) => setOpen(next)}
      onInvestigateInteractive={onInvestigateInteractive}
      onCloseInvestigation={() => setOpen(null)}
      onCreateCase={onCreateCase}
    />
  );
}

async function renderOverview(props: Partial<React.ComponentProps<typeof Harness>> = {}) {
  render(<Harness onCreateCase={vi.fn()} {...props} />);
  // Settles the service's case lookup.
  await screen.findByRole('button', { name: 'Open case #31 ▸' });
}

describe('GrafanaAutonomousOverview symptom triage', () => {
  beforeEach(() => {
    cases.mockReset().mockResolvedValue([grafanaCase(31, 6519)]);
    connections.mockReset().mockResolvedValue({ connections: [{ id: 'default', name: 'Default Prometheus', configured: true, is_default: true }] });
    loadCase.mockReset().mockImplementation(async (_url, id) => grafanaCase(id, id === 31 ? 6519 : 6523));
  });

  it('sorts symptoms into needs attention (one row per metric), data problems and background', async () => {
    await renderOverview();

    const triage = screen.getByTestId('symptom-triage');
    expect(within(triage).getByText("trend-lab: what's going on")).toBeInTheDocument();
    expect(within(triage).getByText('2 metrics need attention')).toBeInTheDocument();
    expect(triage).toHaveTextContent('1 of 2 has a case');
    const rows = within(triage).getAllByTestId('triage-attention');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('error_rate');
    expect(rows[0]).toHaveTextContent('stepped up 0.006 → 0.046');
    expect(rows[0]).toHaveTextContent('+671%');
    expect(rows[0]).toHaveTextContent('Ongoing for 12 h');
    expect(rows[0]).toHaveTextContent('2 runs');
    expect(rows[0]).toHaveTextContent('Also on this metric: unusual activity (weak)');
    expect(rows[1]).toHaveTextContent('p95_latency_ms');
    expect(rows[1]).toHaveTextContent('stepped up 388 → 417');
    expect(rows[1]).toHaveTextContent(/^.*Seen .* to .*1 run/);
    expect(within(triage).getByTestId('triage-data')).toHaveTextContent('1 metric stopped reporting or froze');
    expect(within(triage).getByTestId('triage-background')).toHaveTextContent('2 weaker signals');
    expect(within(triage).queryByTestId('triage-background-item')).not.toBeInTheDocument();
    expect(screen.getByText(/2 metrics on trend-lab need attention\. Primary concern: error_rate stepped up 0\.006 → 0\.046 \(\+671%\)/)).toBeInTheDocument();
    expect(cases).toHaveBeenCalledWith('http://backend', { service: 'trend-lab', limit: 200 });
  });

  it('shows a clicked row right under the top card, above coverage and run history', async () => {
    await renderOverview();

    fireEvent.click(screen.getByRole('button', { name: 'Look at p95_latency_ms level change' }));

    const panel = await screen.findByText('Needs attention · p95_latency_ms on trend-lab');
    const coverage = screen.getByText('Coverage Details');
    expect(panel.compareDocumentPosition(coverage) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('opens a data problem or a background signal in the panel too', async () => {
    await renderOverview();

    fireEvent.click(screen.getByRole('button', { name: 'Look at error_rate data gap' }));
    expect(await screen.findByText('Data problem · error_rate on trend-lab')).toBeInTheDocument();

    fireEvent.click(within(screen.getByTestId('triage-background')).getByRole('button', { name: 'Show' }));
    fireEvent.click(screen.getByRole('button', { name: 'Look at cpu_usage trend' }));
    expect(await screen.findByText('Background signal · cpu_usage on trend-lab')).toBeInTheDocument();
  });

  it('creates a case from a row, opens it in the drawer, and then offers Open case', async () => {
    const onCreateCase = vi.fn(async () => 37);
    await renderOverview({ onCreateCase });

    const errorRow = screen.getAllByTestId('triage-attention')[0];
    fireEvent.click(within(errorRow).getByRole('button', { name: 'Create case' }));

    expect(await screen.findByRole('heading', { name: 'Investigation' })).toBeInTheDocument();
    expect(onCreateCase).toHaveBeenCalledWith(FINDINGS[0]);
    expect(loadCase).toHaveBeenCalledWith('http://backend', 37);
    fireEvent.click(screen.getByRole('button', { name: '×' }));
    expect(within(screen.getAllByTestId('triage-attention')[0]).getByRole('button', { name: 'Open case #37 ▸' })).toBeInTheDocument();
    expect(screen.getByTestId('symptom-triage')).toHaveTextContent('2 of 2 have a case');
  });

  it('opens an existing case without creating another', async () => {
    const onCreateCase = vi.fn();
    await renderOverview({ onCreateCase });

    fireEvent.click(screen.getByRole('button', { name: 'Open case #31 ▸' }));

    expect(await screen.findByRole('heading', { name: 'Investigation' })).toBeInTheDocument();
    expect(onCreateCase).not.toHaveBeenCalled();
    expect(loadCase).toHaveBeenCalledWith('http://backend', 31);
  });

  it("shows another service's finding in place from Service Priorities, without leaving the page", async () => {
    const toInteractive = vi.fn();
    const checkout = finding({ id: 7001, service: 'checkout', metric_name: 'http_requests_total', title: 'http_requests_total dropped', importance_score: 0.7 });
    await renderOverview({ findings: [...FINDINGS, checkout], onInvestigateInteractive: toInteractive });

    fireEvent.click(screen.getByRole('button', { name: 'Investigate checkout' }));

    expect(await screen.findByRole('heading', { name: 'http_requests_total dropped' })).toBeInTheDocument();
    expect(toInteractive).not.toHaveBeenCalled();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Open in Interactive Analysis' }));
    });
    expect(toInteractive).toHaveBeenCalledWith(checkout);
  });

  it('keeps clusters apart and says which cluster and connection a finding came from', async () => {
    connections.mockResolvedValue({ connections: [
      { id: 'default', name: 'Default Prometheus', configured: true, is_default: true },
      { id: 'team-a', name: 'Team A (Mimir)', configured: true },
    ] });
    const onCreateCase = vi.fn(async () => 40);
    const onClusterFilter = vi.fn();
    const inCluster = (cluster: string, id: number, importance: number) =>
      finding({ id, cluster, connection_id: 'team-a', importance_score: importance, trust: SHIFT, comparison_json: { previous_mean: 1, current_mean: 3, change_percent: 200 } });
    render(<Harness onCreateCase={onCreateCase} findings={[inCluster('us', 8001, 0.9), inCluster('eu', 8002, 0.6)]} clusters={['eu', 'us']} onClusterFilter={onClusterFilter} />);

    const rows = await screen.findAllByTestId('triage-attention');
    expect(rows).toHaveLength(2);
    expect(await within(rows[0]).findByText('us · Team A (Mimir)')).toBeInTheDocument();
    expect(within(rows[1]).getByText('eu · Team A (Mimir)')).toBeInTheDocument();

    fireEvent.click(within(screen.getByRole('group', { name: 'Cluster' })).getByRole('button', { name: 'us' }));
    expect(onClusterFilter).toHaveBeenCalledWith('us');

    fireEvent.click(screen.getByRole('button', { name: 'Look at error_rate in eu level change' }));
    expect(await screen.findByText('Needs attention · error_rate in eu on trend-lab')).toBeInTheDocument();
    expect(screen.getByText('Prometheus connection').nextElementSibling).toHaveTextContent('Team A (Mimir)');

    fireEvent.click(within(rows[1]).getByRole('button', { name: 'Create case' }));
    expect(await screen.findByRole('heading', { name: 'Investigation' })).toBeInTheDocument();
    expect(screen.getByText('Cluster / connection').nextElementSibling).toHaveTextContent('eu · Team A (Mimir)');
  });

  it('shows no cluster chips for single-cluster data', async () => {
    await renderOverview();

    expect(screen.queryByRole('group', { name: 'Cluster' })).not.toBeInTheDocument();
  });
});

// A rule that matched error_rate and p95 latency together in run-1 on trend-lab.
const LATENCY_AND_ERRORS: BehaviorFinding = {
  id: 77, behavior_id: 'b', definition_id: 'latency_error_cascade', definition_version: 1,
  title: 'Possible cascading failure', summary: 'Latency and errors rose together.', category: 'availability', severity: 'high',
  service: 'trend-lab', analysis_run_id: 'run-1',
  input_metrics_json: { latency: 'p95_latency_ms', errors: 'error_rate' },
  facts_json: {
    latency: { ruptures: { present: true, signed_change_percent: 7.4 } },
    errors: { ruptures: { present: true, signed_change_percent: 671 } },
  },
  evidence_json: [], matched_conditions_json: [{ passed: true }, { passed: true }], confidence: 1,
  correlation_json: { matched: true, overlap_minutes: 42 }, case_id: null, occurrence_count: 1,
  last_seen_at: '2026-10-09T05:00:00Z', created_at: '2026-10-09T05:00:00Z',
};

describe('GrafanaAutonomousOverview behavior matches', () => {
  beforeEach(() => {
    cases.mockReset().mockResolvedValue([grafanaCase(31, 6519)]);
    connections.mockReset().mockResolvedValue({ connections: [{ id: 'default', name: 'Default Prometheus', configured: true, is_default: true }] });
  });

  it('says which symptoms are one problem, and jumps to the match', async () => {
    const scrolled = vi.fn();
    Element.prototype.scrollIntoView = scrolled;
    await renderOverview({ behaviorFindings: [LATENCY_AND_ERRORS] });

    const rows = within(screen.getByTestId('symptom-triage')).getAllByTestId('triage-attention');
    expect(rows.map((row) => within(row).queryByTestId('symptom-part-of')?.textContent ?? null)).toEqual([
      'Part of: Possible cascading failure · 2 metrics',
      'Part of: Possible cascading failure · 2 metrics',
    ]);

    fireEvent.click(within(rows[1]).getByTestId('symptom-part-of'));
    expect(scrolled).toHaveBeenCalled();
    // The chip is not the row: clicking it does not select that symptom.
    expect(rows[1]).toHaveAttribute('aria-pressed', 'false');

    const match = screen.getByTestId('plugin-behavior-finding');
    expect(match).toHaveAttribute('id', 'plugin-behavior-77');
    expect(within(match).getAllByTestId('plugin-behavior-metric').map((metric) => metric.textContent)).toEqual([
      expect.stringContaining('p95_latency_ms'),
      expect.stringContaining('error_rate'),
    ]);
  });

  it('gives no chip to a symptom from another run', async () => {
    await renderOverview({ behaviorFindings: [{ ...LATENCY_AND_ERRORS, analysis_run_id: 'run-9' }] });
    expect(screen.queryByTestId('symptom-part-of')).not.toBeInTheDocument();
  });
});

describe('GrafanaAutonomousOverview layout of what is going on', () => {
  beforeEach(() => {
    cases.mockReset().mockResolvedValue([]);
    loadCase.mockReset();
  });

  const stopped = (id: number, metric: string, at: string, overrides: Partial<Finding> = {}) => finding({
    id, metric_name: metric, title: `${metric} stopped reporting data`, category: 'data_quality', importance_score: 0.7,
    trust: trust('data_problem', 'needs_attention', 'data_problem'), created_at: at, ...overrides,
  });

  it('lists a metric that stopped several times as one chip, and the connection once', async () => {
    connections.mockReset().mockResolvedValue({ connections: [
      { id: 'default', name: 'Default Prometheus', configured: true, is_default: true },
      { id: 'labs', name: 'Local Prometheus (labs)', configured: true },
    ] });
    const labs = { connection_id: 'labs', analysis_run_id: undefined } as Partial<Finding>;
    render(<Harness onCreateCase={vi.fn()} findings={[
      finding({ id: 1, importance_score: 0.9, trust: SHIFT, ...labs, analysis_run_id: 'run-a' }),
      stopped(2, 'up', '2026-10-21T08:00:00Z', { ...labs, analysis_run_id: 'run-b' }),
      stopped(3, 'up', '2026-10-21T20:40:00Z', { ...labs, analysis_run_id: 'run-c', title: 'up froze at one value' }),
      stopped(4, 'process_cpu_seconds_total', '2026-10-21T20:57:00Z', { ...labs, analysis_run_id: 'run-d' }),
    ]} />);

    const data = await screen.findByTestId('triage-data');
    expect(data).toHaveTextContent('2 metrics stopped reporting or froze');
    expect(await screen.findByText('All from Local Prometheus (labs)')).toBeInTheDocument();
    const chips = within(data).getAllByTestId('triage-data-metric');
    expect(chips.map((chip) => chip.textContent)).toEqual([
      expect.stringMatching(/^process_cpu_seconds_total · /),
      expect.stringMatching(/^up · 2 episodes, latest · /),
    ]);
    expect(screen.queryByText(/\(Local Prometheus \(labs\)\)/)).not.toBeInTheDocument();
  });

  it('leads with a named service, and calls metrics with no service label that', async () => {
    connections.mockReset().mockResolvedValue({ connections: [] });
    render(<Harness onCreateCase={vi.fn()} findings={[
      finding({ id: 1, service: undefined, metric_name: 'process_resident_memory_bytes', importance_score: 0.95, trust: SHIFT }),
      finding({ id: 2, service: 'orders-consumer', metric_name: 'kafka_consumergroup_lag', importance_score: 0.6, trust: SHIFT }),
    ]} />);
    expect(await screen.findByText("orders-consumer: what's going on")).toBeInTheDocument();
    expect(screen.getByText('No service label')).toBeInTheDocument();
    expect(screen.queryByText(/^unknown$/)).not.toBeInTheDocument();
  });

  it('explains a service-less lead when nothing has a service', async () => {
    connections.mockReset().mockResolvedValue({ connections: [] });
    render(<Harness onCreateCase={vi.fn()} findings={[finding({ id: 1, service: undefined, importance_score: 0.9, trust: SHIFT })]} />);
    expect(await screen.findByText("No service label: what's going on")).toBeInTheDocument();
    expect(screen.getByText(/These metrics have no/)).toBeInTheDocument();
  });
});
