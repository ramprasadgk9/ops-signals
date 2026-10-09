import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AutonomousDashboardData } from '../autonomous/dashboardModel';
import { getCase, updateCaseInvestigation } from './backendClient';
import type { GrafanaCase } from './contracts';
import { CasesPanel } from './PluginApp';

// PluginApp's Prometheus query path imports @grafana/* (only loadable inside Grafana); CasesPanel
// doesn't use it.
vi.mock('./grafanaPrometheus', () => ({}));
vi.mock('./prometheusFrameNormalizer', () => ({}));
vi.mock('./backendClient', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./backendClient')>()),
  getCase: vi.fn(),
  updateCaseInvestigation: vi.fn(),
}));

const loadCase = vi.mocked(getCase);
const saveInvestigation = vi.mocked(updateCaseInvestigation);

function grafanaCase(overrides: Partial<GrafanaCase> = {}): GrafanaCase {
  return {
    id: 34,
    finding_id: 120,
    analysis_run_id: 'run-1',
    case_title: 'cpu_usage stopped reporting data during the selected time window.',
    case_status: 'open',
    finding_snapshot: {
      id: 120,
      service: 'spike-lab',
      metric_name: 'cpu_usage',
      title: 'cpu_usage stopped reporting data during the selected time window.',
      summary: 'cpu_usage on mock-metrics:9101 stopped reporting for 19 minutes.',
      health_status: 'warning',
      importance_score: 0.71,
      signal_ids: ['s1', 's2', 's3'],
    },
    investigation_status: 'not_started',
    investigation_notes: [],
    root_cause_status: 'unknown',
    root_cause_summary: null,
    root_cause_confidence: null,
    root_cause_verified: false,
    corrective_action: null,
    outcome_status: 'pending',
    outcome_summary: null,
    memory_status: 'not_indexed',
    created_at: '2026-10-06T21:37:00Z',
    updated_at: '2026-10-06T21:37:00Z',
    resolved_at: null,
    ...overrides,
  };
}

const data = {
  casesScope: 'history',
  recentCases: [
    { id: 34, title: 'Case #34 - cpu_usage stopped reporting data during the selected time window.', status: 'open · not_started', meta: 'spike-lab / cpu_usage', updatedAt: '2026-10-06T21:37:00Z', href: '#case-34' },
    { id: 33, title: 'Case #33 - cpu_usage is trending in one direction.', status: 'open · not_started', meta: 'trend-lab / cpu_usage', updatedAt: '2026-10-06T19:41:00Z', href: '#case-33' },
  ],
} as unknown as AutonomousDashboardData;

describe('CasesPanel (Recent Cases from History)', () => {
  beforeEach(() => {
    loadCase.mockReset();
    saveInvestigation.mockReset();
  });

  it('starts collapsed to a one-line summary and expands on Show', () => {
    render(<CasesPanel data={data} backendUrl="http://backend" />);

    expect(screen.getByText('2 cases')).toBeInTheDocument();
    expect(screen.getByText('2 open')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Case #34/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Show cases' }));

    expect(screen.getByRole('button', { name: /Case #34/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Hide cases' })).toHaveAttribute('aria-expanded', 'true');
  });

  it('opens a clicked case in the workflow drawer, showing the finding it was opened from', async () => {
    loadCase.mockResolvedValue(grafanaCase());

    render(<CasesPanel data={data} backendUrl="http://backend" />);
    fireEvent.click(screen.getByRole('button', { name: 'Show cases' }));
    fireEvent.click(screen.getByRole('button', { name: /Case #34/ }));

    expect(await screen.findByRole('heading', { name: 'Investigation' })).toBeInTheDocument();
    expect(loadCase).toHaveBeenCalledWith('http://backend', 34);
    expect(screen.getByText('Case #34')).toBeInTheDocument();
    expect(screen.getByText('cpu_usage on mock-metrics:9101 stopped reporting for 19 minutes.')).toBeInTheDocument();
    expect(screen.getByText('spike-lab')).toBeInTheDocument();
    expect(screen.getByText('cpu_usage')).toBeInTheDocument();
    expect(screen.getByText('Supporting signals').nextElementSibling).toHaveTextContent('3');
    for (const step of ['Investigation', 'Root Cause', 'Resolution', 'Publish Knowledge']) {
      expect(screen.getByRole('button', { name: new RegExp(step) })).toBeInTheDocument();
    }
  });

  it('saves a workflow step and refreshes the overview once the drawer is closed', async () => {
    loadCase.mockResolvedValue(grafanaCase());
    saveInvestigation.mockResolvedValue(grafanaCase({ investigation_status: 'in_progress' }));
    const onCasesChanged = vi.fn();

    render(<CasesPanel data={data} backendUrl="http://backend" onCasesChanged={onCasesChanged} />);
    fireEvent.click(screen.getByRole('button', { name: 'Show cases' }));
    fireEvent.click(screen.getByRole('button', { name: /Case #34/ }));
    fireEvent.click(await screen.findByRole('button', { name: /2\s*Investigation/ }));
    expect(screen.getByLabelText('Investigation status')).toHaveValue('not_started');
    fireEvent.change(screen.getByLabelText('Investigation status'), { target: { value: 'in_progress' } });
    fireEvent.change(screen.getByLabelText('Notes'), { target: { value: 'Prometheus restarted at 20:10' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Case' }));

    expect(await screen.findByText(/Last saved/)).toBeInTheDocument();
    expect(saveInvestigation).toHaveBeenCalledWith('http://backend', 34, { investigation_status: 'in_progress', investigation_note: 'Prometheus restarted at 20:10' });
    expect(onCasesChanged).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: '×' }));
    expect(screen.queryByRole('heading', { name: 'Investigation' })).not.toBeInTheDocument();
    expect(onCasesChanged).toHaveBeenCalledTimes(1);
  });

  it('does not refresh the overview when the drawer is closed without saving', async () => {
    loadCase.mockResolvedValue(grafanaCase());
    const onCasesChanged = vi.fn();

    render(<CasesPanel data={data} backendUrl="http://backend" onCasesChanged={onCasesChanged} />);
    fireEvent.click(screen.getByRole('button', { name: 'Show cases' }));
    fireEvent.click(screen.getByRole('button', { name: /Case #34/ }));
    fireEvent.click(await screen.findByRole('button', { name: '×' }));

    expect(onCasesChanged).not.toHaveBeenCalled();
  });

  it('shows a save failure inside the drawer', async () => {
    loadCase.mockResolvedValue(grafanaCase());
    saveInvestigation.mockRejectedValue(new Error('500'));

    render(<CasesPanel data={data} backendUrl="http://backend" />);
    fireEvent.click(screen.getByRole('button', { name: 'Show cases' }));
    fireEvent.click(screen.getByRole('button', { name: /Case #34/ }));
    fireEvent.click(await screen.findByRole('button', { name: /2\s*Investigation/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Save Case' }));

    expect(await screen.findByText('Could not save investigation update.')).toBeInTheDocument();
    expect(screen.getByText('Not saved')).toBeInTheDocument();
  });

  it('says so when a case cannot be loaded, and keeps the list usable', async () => {
    loadCase.mockRejectedValue(new Error('network'));

    render(<CasesPanel data={data} backendUrl="http://backend" />);
    fireEvent.click(screen.getByRole('button', { name: 'Show cases' }));
    fireEvent.click(screen.getByRole('button', { name: /Case #33/ }));

    expect(await screen.findByText('Could not open case #33. Check the backend connection and retry.')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Investigation' })).not.toBeInTheDocument();
    expect(within(screen.getByRole('button', { name: /Case #34/ })).getByText(/Case #34/)).toBeInTheDocument();
  });
});

describe('CasesPanel cluster', () => {
  beforeEach(() => {
    loadCase.mockReset();
  });

  it("shows the cluster saved in a case's snapshot when it is opened from history", async () => {
    loadCase.mockResolvedValue(grafanaCase({ finding_snapshot: { ...grafanaCase().finding_snapshot, cluster: 'us', connection_id: 'team-a' } }));
    render(<CasesPanel data={data} backendUrl="http://backend" />);
    fireEvent.click(screen.getByRole('button', { name: 'Show cases' }));
    fireEvent.click(screen.getByRole('button', { name: /Case #34/ }));

    expect(await screen.findByRole('heading', { name: 'Investigation' })).toBeInTheDocument();
    expect(screen.getByText('Cluster / connection').nextElementSibling).toHaveTextContent('us');
  });
});
