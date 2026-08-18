import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AutonomousMonitoringDashboard } from './AutonomousMonitoringDashboard';
import type { AutonomousDashboardData } from './dashboardModel';

const data: AutonomousDashboardData = {
  summary: {
    metricsDiscovered: 12,
    candidatesSelected: 4,
    findingsGenerated: 2,
    casesOpen: 1,
    executed: 4,
    skipped: 1,
    failed: 0,
  },
  selection: {
    title: 'Metric Selection',
    discovered: 12,
    selected: 4,
    excluded: 8,
    reductionPercent: 66.666,
    selectedLabel: 'Selected by monitoring policy',
    screeningEnabled: false,
    reasons: [],
  },
  topFindings: [
    {
      id: 7,
      rank: 1,
      severity: 'significant',
      service: 'checkout',
      metric: 'latency',
      behavior: 'Behavior Change',
      importance: 0.94,
      firstObserved: '2026-08-13T17:21:00Z',
      href: '/findings?window=24h',
    },
  ],
  behaviorDistribution: [{ label: 'Behavior Change', count: 2 }],
  executionRows: [{ id: 'run-1', scope: 'checkout', metrics: '4 metrics', status: 'completed', completed: '2026-08-13T17:21:00Z' }],
  recentCases: [{ id: 12, title: 'Case #12 - checkout latency degradation', status: 'open · not_started', meta: 'checkout / latency', updatedAt: '2026-08-13T17:23:00Z', href: '/cases/12' }],
  behaviorFindingCount: 0,
  casesScope: 'history',
};

describe('AutonomousMonitoringDashboard', () => {
  it('renders overview sections and top finding navigation', () => {
    render(<AutonomousMonitoringDashboard data={data} context={{ datasource: 'Prometheus', timeWindow: 'Last 24 hours' }} state="ready" />);

    expect(screen.getByText('Autonomous Monitoring Overview')).toBeInTheDocument();
    expect(screen.getByText('Top Findings by Importance')).toBeInTheDocument();
    expect(screen.getByText('Metric Selection')).toBeInTheDocument();
    expect(screen.getByText(/Screening not enabled/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'latency' })).toHaveAttribute('href', '/findings?window=24h');
    expect(screen.getByRole('link', { name: /Case #12/ })).toHaveAttribute('href', '/cases/12');
  });

  it('renders a first-run empty state before autonomous analysis completes', () => {
    render(<AutonomousMonitoringDashboard data={data} context={{ datasource: 'Prometheus' }} state="idle" />);

    expect(screen.getByText('No autonomous analysis has been completed yet.')).toBeInTheDocument();
    expect(screen.getByText('Metrics selected')).toBeInTheDocument();
    expect(screen.queryByText('Top Findings by Importance')).not.toBeInTheDocument();
  });

  it('renders autonomous run progress without showing dashboard rows', () => {
    render(<AutonomousMonitoringDashboard data={data} context={{ datasource: 'Prometheus' }} state="loading" />);

    expect(screen.getByText('Running Autonomous Analysis...')).toBeInTheDocument();
    expect(screen.getByText('Building metric plan')).toBeInTheDocument();
    expect(screen.queryByText('Top Findings by Importance')).not.toBeInTheDocument();
  });

  it('renders a friendly error state', () => {
    render(<AutonomousMonitoringDashboard data={data} context={{ datasource: 'Prometheus' }} state="error" error="Autonomous summary unavailable." />);

    expect(screen.getByText('Autonomous summary unavailable.')).toBeInTheDocument();
    expect(screen.queryByText(/Failed to fetch/)).not.toBeInTheDocument();
  });
});
