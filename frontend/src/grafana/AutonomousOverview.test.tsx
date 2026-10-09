import React, { useState } from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { buildAutonomousDashboardData } from '../autonomous/dashboardModel';
import type { Finding, FindingTrust } from '../types';
import { getCase, listCases } from './backendClient';
import type { GrafanaCase } from './contracts';
import { GrafanaAutonomousOverview } from './PluginApp';

// PluginApp's Prometheus query path imports @grafana/* (only loadable inside Grafana).
vi.mock('./grafanaPrometheus', () => ({}));
vi.mock('./prometheusFrameNormalizer', () => ({}));
vi.mock('./backendClient', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./backendClient')>()),
  listCases: vi.fn(),
  getCase: vi.fn(),
  getTicketingStatus: vi.fn(() => Promise.resolve({ enabled: false })),
  getCaseTicket: vi.fn(() => Promise.reject(new Error('none'))),
  getFindingSeenBefore: vi.fn(() => new Promise(() => undefined)),
}));
const cases = vi.mocked(listCases);
const loadCase = vi.mocked(getCase);

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

function Harness({ onCreateCase, findings = FINDINGS, onInvestigateInteractive = () => undefined }: {
  onCreateCase: (finding: Finding) => Promise<number | null>;
  findings?: Finding[];
  onInvestigateInteractive?: (finding: Finding) => void;
}) {
  const [open, setOpen] = useState<Finding | null>(null);
  const data = buildAutonomousDashboardData({ findings, cases: [], analysisRuns: [] });
  const noop = () => undefined;
  return (
    <GrafanaAutonomousOverview
      backendUrl="http://backend"
      data={data}
      findings={findings}
      behaviorFindings={[]}
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
});
