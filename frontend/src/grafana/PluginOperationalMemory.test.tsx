import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { CoverageReport, RecurringProblemsResponse } from '../types';
import { getMemoryStats, getMonitoringCoverage, getRecurringProblems } from './backendClient';
import { PluginOperationalMemory } from './PluginOperationalMemory';

vi.mock('./backendClient', () => ({
  getMemoryStats: vi.fn(),
  getRecurringProblems: vi.fn(),
  getMonitoringCoverage: vi.fn(),
}));
const stats = vi.mocked(getMemoryStats);
const recurring = vi.mocked(getRecurringProblems);
const coverage = vi.mocked(getMonitoringCoverage);

function problems(overrides: Partial<RecurringProblemsResponse> = {}): RecurringProblemsResponse {
  return {
    available: true,
    window_days: 90,
    min_occurrences: 3,
    group_by: 'symptom',
    group_similarity: 0.8,
    cases_considered: 40,
    sampled: false,
    problems: [
      {
        name: 'Checkout connection pool exhaustion',
        named_by: 'central_case',
        central_case_id: 3,
        occurrences: 4,
        services: ['checkout'],
        verified_root_causes: 1,
        open_cases: 1,
        causes: [{ case_id: 3, root_cause: 'Pool size too small', fix: 'Raised pool to 50', verified: true }],
        cases: [{ case_id: 3, title: 'Pool exhausted at peak', service: 'checkout', origin: 'detected', case_status: 'resolved', rca_verified: true, similarity_to_central: 1 }],
      },
    ],
    ...overrides,
  };
}

function report(overrides: Partial<CoverageReport> = {}): CoverageReport {
  return {
    available: true,
    window_days: 365,
    incidents_considered: 2,
    counts: { detected: 1, missed: 1 },
    services: [],
    incidents: [
      { case_id: 20, title: 'Payments outage March', service: 'payments', status: 'missed', label: 'Missed', explanation: 'Payments was analysed and nothing was flagged.', evidence: [], seen_elsewhere: 0 },
      { case_id: 21, title: 'Checkout slow April', service: 'checkout', status: 'detected', label: 'Detected', explanation: 'A latency finding was raised.', evidence: [], seen_elsewhere: 0 },
    ],
    ...overrides,
  };
}

describe('PluginOperationalMemory', () => {
  beforeEach(() => {
    stats.mockReset().mockResolvedValue({ generated_at: '', enabled: true, status: 'healthy', indexed_cases: 12, not_indexed_cases: 3, stale_cases: 1, error_cases: 0, total_cases: 16, source: 'qdrant' });
    recurring.mockReset().mockResolvedValue(problems());
    coverage.mockReset().mockResolvedValue(report());
  });

  it('shows memory in one line, a recurring problem with its cause, fix and next step, and coverage gaps', async () => {
    render(<PluginOperationalMemory backendUrl="http://backend" onOpenCase={vi.fn()} />);

    expect(screen.getByText('Recurring problems')).toBeInTheDocument();
    expect(await screen.findByTestId('plugin-memory-stats')).toHaveTextContent('12 past cases published · 3 not published · 1 changed since publishing');
    const problem = await screen.findByTestId('plugin-recurring-problem');
    expect(problem).toHaveTextContent('Checkout connection pool exhaustion');
    expect(problem).toHaveTextContent('4 times in 90 days');
    expect(problem).toHaveTextContent('Cause (verified): Pool size too small — Fix: Raised pool to 50');
    expect(within(problem).getByTestId('plugin-recurring-next-step')).toHaveTextContent('Worth a lasting fix.');
    expect(screen.getByText(/40 cases from the last 90 days compared/)).toBeInTheDocument();
    const gaps = await screen.findAllByTestId('plugin-coverage-incident');
    expect(gaps).toHaveLength(1);
    expect(gaps[0]).toHaveTextContent('Payments outage March');
  });

  it('opens a case from a recurring problem or a coverage gap', async () => {
    const onOpenCase = vi.fn();
    render(<PluginOperationalMemory backendUrl="http://backend" onOpenCase={onOpenCase} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Show 4 cases' }));
    fireEvent.click(screen.getByRole('button', { name: 'Pool exhausted at peak' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Payments outage March' }));

    expect(onOpenCase).toHaveBeenNthCalledWith(1, 3);
    expect(onOpenCase).toHaveBeenNthCalledWith(2, 20);
  });

  it('reloads recurring problems grouped by cause', async () => {
    render(<PluginOperationalMemory backendUrl="http://backend" onOpenCase={vi.fn()} />);
    await screen.findByTestId('plugin-recurring-problem');

    fireEvent.click(screen.getByRole('button', { name: 'By cause' }));

    expect(recurring).toHaveBeenLastCalledWith('http://backend', 90, 'cause');
    expect(await screen.findByTestId('plugin-recurring-problem')).toBeInTheDocument();
  });

  it('shows why memory features are unavailable', async () => {
    stats.mockResolvedValue({ generated_at: '', enabled: false, status: 'disabled', indexed_cases: 0, not_indexed_cases: 0, stale_cases: 0, error_cases: 0, total_cases: 0, source: 'none' });
    recurring.mockResolvedValue(problems({ available: false, reason: 'Operational memory is turned off.', problems: [] }));
    coverage.mockResolvedValue(report({ available: false, reason: 'Import past incidents to see coverage.', incidents: [] }));
    render(<PluginOperationalMemory backendUrl="http://backend" onOpenCase={vi.fn()} />);

    expect(await screen.findByText('Memory is turned off on this backend.')).toBeInTheDocument();
    expect(await screen.findByText('Operational memory is turned off.')).toBeInTheDocument();
    expect(await screen.findByText('Import past incidents to see coverage.')).toBeInTheDocument();
  });

  it('says all is up to date when nothing needs attention', async () => {
    stats.mockResolvedValue({ generated_at: '', enabled: true, status: 'healthy', indexed_cases: 26, not_indexed_cases: 0, stale_cases: 0, error_cases: 0, total_cases: 26, source: 'qdrant' });
    render(<PluginOperationalMemory backendUrl="http://backend" onOpenCase={vi.fn()} />);

    expect(await screen.findByTestId('plugin-memory-stats')).toHaveTextContent('✓ 26 past cases published · all up to date');
  });

  it('asks for imports in one line when no past incident is imported, and opens a case to record a missing cause', async () => {
    const onOpenCase = vi.fn();
    const [problem] = problems().problems;
    recurring.mockResolvedValue(problems({ problems: [{ ...problem, causes: [], cases: [{ ...problem.cases[0], case_status: 'open' }] }] }));
    coverage.mockResolvedValue(report({ reason: 'No past incidents imported in this window.', incidents: [], incidents_considered: 0, counts: {} }));
    render(<PluginOperationalMemory backendUrl="http://backend" onOpenCase={onOpenCase} />);

    expect(await screen.findByTestId('plugin-monitoring-coverage')).toHaveTextContent('Did your monitoring catch past incidents?');
    expect(screen.queryByText('Monitoring coverage')).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole('button', { name: 'Add a cause' }));
    expect(onOpenCase).toHaveBeenCalledWith(3);
  });
});
