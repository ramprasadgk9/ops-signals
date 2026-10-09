import React, { useState } from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { buildAutonomousDashboardData } from '../autonomous/dashboardModel';
import type { Finding } from '../types';
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
    created_at: '2026-10-09T01:00:00Z',
    ...overrides,
  };
}

// Four findings on trend-lab: error_rate seen in two runs, so three symptoms.
const FINDINGS = [
  finding({ id: 6523, importance_score: 0.88 }),
  finding({ id: 6400, importance_score: 0.8, analysis_run_id: 'run-0' }),
  finding({ id: 6519, metric_name: 'p95_latency_ms', title: 'p95_latency_ms spiked', category: 'spike', importance_score: 0.81 }),
  finding({ id: 6511, metric_name: 'cpu_usage', title: 'cpu_usage is trending upward', category: 'trend', importance_score: 0.66 }),
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

describe('GrafanaAutonomousOverview case flow', () => {
  beforeEach(() => {
    cases.mockReset().mockResolvedValue([grafanaCase(31, 6519)]);
    loadCase.mockReset().mockImplementation(async (_url, id) => grafanaCase(id, id === 31 ? 6519 : 6523));
  });

  it('counts symptoms with repeats folded and shows which ones have a case', async () => {
    render(<Harness onCreateCase={vi.fn()} />);

    expect(screen.getByText(/3 symptoms on trend-lab/)).toBeInTheDocument();
    const list = screen.getByTestId('related-symptoms');
    expect(await within(list).findByText('Case #31')).toBeInTheDocument();
    expect(within(list).getByText('1 of 3 have a case')).toBeInTheDocument();
    expect(within(list).getByText('seen in 2 runs')).toBeInTheDocument();
    expect(cases).toHaveBeenCalledWith('http://backend', { service: 'trend-lab', limit: 200 });
  });

  it('shows a clicked symptom right under the top card, above coverage and run history', async () => {
    render(<Harness onCreateCase={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Look at p95_latency_ms' }));

    const panel = await screen.findByText('Symptom 2 of 3 on trend-lab');
    const coverage = screen.getByText('Coverage Details');
    expect(panel.compareDocumentPosition(coverage) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getAllByRole('button', { name: 'Open case #31 ▸' })).toHaveLength(2);
  });

  it('creates a case for the selected symptom, opens it in the drawer, and then offers Open case', async () => {
    const onCreateCase = vi.fn(async () => 37);
    render(<Harness onCreateCase={onCreateCase} />);
    await screen.findByText('Case #31');

    fireEvent.click(screen.getByRole('button', { name: 'Create case' }));

    expect(await screen.findByRole('heading', { name: 'Investigation' })).toBeInTheDocument();
    expect(onCreateCase).toHaveBeenCalledWith(FINDINGS[0]);
    expect(loadCase).toHaveBeenCalledWith('http://backend', 37);
    fireEvent.click(screen.getByRole('button', { name: '×' }));
    expect(screen.getAllByRole('button', { name: 'Open case #37 ▸' }).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: 'Create case' })).not.toBeInTheDocument();
    expect(within(screen.getByTestId('related-symptoms')).getByText('2 of 3 have a case')).toBeInTheDocument();
  });

  it('opens an existing case without creating another', async () => {
    const onCreateCase = vi.fn();
    render(<Harness onCreateCase={onCreateCase} />);
    fireEvent.click(screen.getByRole('button', { name: 'Look at p95_latency_ms' }));

    fireEvent.click((await screen.findAllByRole('button', { name: 'Open case #31 ▸' }))[0]);

    expect(await screen.findByRole('heading', { name: 'Investigation' })).toBeInTheDocument();
    expect(onCreateCase).not.toHaveBeenCalled();
    expect(loadCase).toHaveBeenCalledWith('http://backend', 31);
  });

  it("shows another service's finding in place from Service Priorities, without leaving the page", async () => {
    const toInteractive = vi.fn();
    const checkout = finding({ id: 7001, service: 'checkout', metric_name: 'http_requests_total', title: 'http_requests_total dropped', importance_score: 0.7 });
    render(<Harness onCreateCase={vi.fn()} findings={[...FINDINGS, checkout]} onInvestigateInteractive={toInteractive} />);

    fireEvent.click(screen.getByRole('button', { name: 'Investigate checkout' }));

    expect(await screen.findByRole('heading', { name: 'http_requests_total dropped' })).toBeInTheDocument();
    expect(toInteractive).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Open in Interactive Analysis' }));
    expect(toInteractive).toHaveBeenCalledWith(checkout);
  });
});
