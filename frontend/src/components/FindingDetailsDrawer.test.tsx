import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { FindingDetailsDrawer } from './FindingDetailsDrawer';
import { api } from '../api/queries';
import type { Finding } from '../types';

vi.mock('../api/queries', () => ({
  api: {
    analysisRun: vi.fn(),
    timeseries: vi.fn(),
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
    expect(api.timeseries).toHaveBeenCalledWith('test-otlp-service', 'cpu_usage', 'c06d17a3dd9143ef8ebd8c454031fd89');
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
});
