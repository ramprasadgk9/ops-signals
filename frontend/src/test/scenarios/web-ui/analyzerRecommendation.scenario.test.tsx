import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import { api } from '../../../api/queries';
import type { AnalyzerRecommendation, MetricAnalyzerRecommendation, MetricSample } from '../../../types';
import { AnalyzerRecommendationPage } from '../../../pages/AnalyzerRecommendationPage';

vi.mock('../../../api/queries', () => ({
  api: {
    metricAnalyzerSamples: vi.fn(),
    metricAnalyzerEvaluate: vi.fn(),
  },
}));

Object.assign(navigator, { clipboard: { writeText: vi.fn() } });

function renderPage(path = '/analyzer-recommendation') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <AnalyzerRecommendationPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const samples: MetricSample[] = [
  { service: 'payments-api', metric_name: 'process_resident_memory_bytes', analysis_run_id: 'run-new', sample_count: 1440, start_time: '2026-10-24T00:00:00Z', end_time: '2026-10-31T00:00:00Z' },
  // An older run of the same metric: listed once, from the newest run.
  { service: 'payments-api', metric_name: 'process_resident_memory_bytes', analysis_run_id: 'run-old', sample_count: 700, start_time: '2026-10-17T00:00:00Z', end_time: '2026-10-24T00:00:00Z' },
  { service: 'checkout', metric_name: 'http_latency_ms', analysis_run_id: 'run-c', sample_count: 300, start_time: '2026-10-30T00:00:00Z', end_time: '2026-10-31T00:00:00Z' },
];

function pick(overrides: Partial<AnalyzerRecommendation>): AnalyzerRecommendation {
  return {
    analyzer_id: 'trend',
    display_name: 'Trend Analysis',
    recommendation: 'recommended',
    fitness_score: 0.82,
    decision_confidence: 0.71,
    summary: 'Router: strong steady slope.',
    evidence: { reasons: ['Steady climb across the window.'], warnings: [] },
    requirements: [],
    warnings: [],
    parameters_tested: {},
    description: 'Spots slow, steady climbs or drops. Example: memory grows every hour.',
    available: true,
    last_run: 'ran',
    last_run_reason: 'Picked by the router for this series.',
    ...overrides,
  };
}

const result: MetricAnalyzerRecommendation = {
  sample: samples[0],
  profile: {
    sample_count: 1440, start_time: samples[0].start_time, end_time: samples[0].end_time, regular_sampling: true, missing_ratio: 0,
    duplicate_timestamps: 0, constant_value_ratio: 0, mean: 1, stddev: 1, minimum: 0, maximum: 2, variance: 1, trend_slope: 1,
    trend_strength: 0.6, seasonality_strength: 0, sparsity: 0, metric_behavior: 'gauge',
  },
  recommendations: [
    pick({}),
    pick({ analyzer_id: 'pyod_outlier', display_name: 'PyOD Outlier', recommendation: 'optional', description: "Flags short, sharp spikes that don't fit the usual range.", last_run: 'skipped' }),
    pick({ analyzer_id: 'stumpy', display_name: 'STUMPY', recommendation: 'not_recommended', description: 'Finds a stretch that looks unlike the rest of the series.', last_run: 'ran' }),
    pick({ analyzer_id: 'prophet', display_name: 'Prophet', recommendation: 'rejected', description: 'Forecasts the expected value.', last_run: null }),
    pick({ analyzer_id: 'kats', display_name: 'Kats', recommendation: 'recommended', description: null, available: false, last_run: null }),
  ],
  not_scored: [
    { analyzer_id: 'seasonal_anomaly', display_name: 'Seasonal Anomaly', description: 'Compares each value with what is normal for that time of day or week.' },
    { analyzer_id: 'baseline_shift', display_name: 'Baseline Shift', description: null },
  ],
  ai_opinion: { available: false, recommended: [], not_recommended: [], caveats: [], diverges_from_router: false },
};

async function chooseMemoryMetric() {
  fireEvent.mouseDown(await screen.findByLabelText('Metric'));
  fireEvent.click(await screen.findByRole('option', { name: /process_resident_memory_bytes/ }));
}

describe('Which analyzer fits my metric?', () => {
  afterEach(() => vi.clearAllMocks());

  it('asks only for a metric, lists each analyzed metric once, and checks its latest run', async () => {
    vi.mocked(api.metricAnalyzerSamples).mockResolvedValue(samples);
    vi.mocked(api.metricAnalyzerEvaluate).mockResolvedValue(result);
    renderPage();

    expect(await screen.findByRole('heading', { name: 'Which analyzer fits my metric?' })).toBeInTheDocument();
    // Nothing is shown before a question is asked: no YAML, no empty advisor.
    expect(screen.queryByText(/analyzers\.yaml/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Chat Advisor/)).not.toBeInTheDocument();
    const button = screen.getByRole('button', { name: 'Find the right analyzer' });
    expect(button).toBeDisabled();

    fireEvent.mouseDown(screen.getByLabelText('Metric'));
    expect(await screen.findAllByRole('option', { name: /process_resident_memory_bytes/ })).toHaveLength(1);
    fireEvent.click(screen.getByRole('option', { name: /process_resident_memory_bytes/ }));
    expect(screen.getByText(/Uses the latest analysis of process_resident_memory_bytes on payments-api: 1440 readings/)).toBeInTheDocument();

    fireEvent.click(button);
    await waitFor(() => expect(api.metricAnalyzerEvaluate).toHaveBeenCalledWith('payments-api', 'process_resident_memory_bytes', 'run-new'));
  });

  it('groups picks into plain columns with what each looks for and whether it ran, and keeps unbuilt tools out of them', async () => {
    vi.mocked(api.metricAnalyzerSamples).mockResolvedValue(samples);
    vi.mocked(api.metricAnalyzerEvaluate).mockResolvedValue(result);
    renderPage();
    await chooseMemoryMetric();
    fireEvent.click(screen.getByRole('button', { name: 'Find the right analyzer' }));

    const good = await screen.findByRole('region', { name: 'Good fit' });
    expect(within(good).getByText('Trend Analysis')).toBeInTheDocument();
    expect(within(good).getByText(/Spots slow, steady climbs/)).toBeInTheDocument();
    expect(within(good).getByText('Ran last time')).toBeInTheDocument();
    expect(within(good).getByRole('link', { name: 'Try in Labs' })).toHaveAttribute('href', '/experiments/trend-lab');
    expect(within(good).queryByText('Kats')).not.toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Can help' })).getByText("Didn't run last time")).toBeInTheDocument();
    const notAFit = screen.getByRole('region', { name: 'Not a fit' });
    expect(within(notAFit).getByText('STUMPY')).toBeInTheDocument();
    // Rejected lands in a column too: no rating is ever dropped.
    expect(within(notAFit).getByText('Prophet')).toBeInTheDocument();
    expect(screen.getByText(/aren't built into Ops Signals, so they can't run here/)).toBeInTheDocument();
    expect(screen.getByTestId('not-built-in-kats')).toHaveTextContent('Kats (good fit)');

    // Registered analyzers the router never scores are named, with why they're not in a column.
    const notScored = screen.getByTestId('not-scored');
    expect(notScored).toHaveTextContent(/Not scored by the router, so they run only when analysis is set to run every analyzer/);
    expect(within(notScored).getByRole('link', { name: 'Seasonal Anomaly' })).toHaveAttribute(
      'href',
      '/analyzer-settings?service=payments-api&metric=process_resident_memory_bytes&analyzer=seasonal_anomaly',
    );
    expect(within(notScored).getByRole('link', { name: 'Baseline Shift' })).toBeInTheDocument();

    // Statistics live in a tooltip, not on the card.
    expect(screen.queryByText(/Fitness 82%/)).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'See what runs on payments-api' })).toHaveAttribute(
      'href',
      '/analyzer-settings?service=payments-api&metric=process_resident_memory_bytes',
    );
  });

  it('offers a per-service setting only for analyzers that ran here but are not a fit', async () => {
    vi.mocked(api.metricAnalyzerSamples).mockResolvedValue(samples);
    vi.mocked(api.metricAnalyzerEvaluate).mockResolvedValue(result);
    renderPage();
    await chooseMemoryMetric();
    fireEvent.click(screen.getByRole('button', { name: 'Find the right analyzer' }));

    expect(await screen.findByText(/STUMPY ran on this metric but doesn't suit it/)).toBeInTheDocument();
    const snippet = screen.getByText(/disabled: \[stumpy\]/);
    expect(snippet.textContent).toContain('service: "payments-api"');
    expect(snippet.textContent).toContain('metric: "process_resident_memory_bytes"');
    expect(snippet.textContent).not.toContain('prophet');
    fireEvent.click(screen.getByRole('button', { name: 'Copy setting' }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(expect.stringContaining('disabled: [stumpy]'));
  });

  it('shows the AI second opinion apart from the columns, with analyzer names', async () => {
    vi.mocked(api.metricAnalyzerSamples).mockResolvedValue(samples);
    vi.mocked(api.metricAnalyzerEvaluate).mockResolvedValue({
      ...result,
      ai_opinion: {
        available: true, best_analyzer_id: 'pyod_outlier', rationale: 'Short bursts matter more here.', recommended: [], not_recommended: [],
        caveats: ['Confirm with a longer window.'], diverges_from_router: true, router_top_analyzer_id: 'trend',
      },
    });
    renderPage();
    await chooseMemoryMetric();
    fireEvent.click(screen.getByRole('button', { name: 'Find the right analyzer' }));

    expect(await screen.findByText('Second opinion')).toBeInTheDocument();
    expect(screen.getByText(/disagrees with the top pick above \(Trend Analysis\)/)).toBeInTheDocument();
    expect(screen.getByText('Best pick: PyOD Outlier')).toBeInTheDocument();
    expect(screen.getByText('Confirm with a longer window.')).toBeInTheDocument();
  });

  it('finds a metric by its service name too', async () => {
    vi.mocked(api.metricAnalyzerSamples).mockResolvedValue(samples);
    renderPage();
    const input = await screen.findByLabelText('Metric');
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: 'checkout' } });
    expect(await screen.findByRole('option', { name: /http_latency_ms/ })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /process_resident_memory_bytes/ })).not.toBeInTheDocument();
  });

  it('picks the metric from a link, and points to New Analysis when nothing is analyzed yet', async () => {
    vi.mocked(api.metricAnalyzerSamples).mockResolvedValue(samples);
    const { unmount } = renderPage('/analyzer-recommendation?service=checkout&metric=http_latency_ms');
    expect(await screen.findByDisplayValue('http_latency_ms')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Find the right analyzer' })).toBeEnabled();
    unmount();

    vi.mocked(api.metricAnalyzerSamples).mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText(/No metric has been analyzed yet/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'New Analysis' })).toHaveAttribute('href', '/validate-data');
  });
});
