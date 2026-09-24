import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import { api } from '../../../api/queries';
import type { AnalyzerRecommendationChatResponse } from '../../../types';
import { AnalyzerRecommendationPage } from '../../../pages/AnalyzerRecommendationPage';

vi.mock('../../../api/queries', () => ({
  api: {
    metricAnalyzerSamples: vi.fn(),
    metricAnalyzerChat: vi.fn(),
  },
}));

Object.assign(navigator, {
  clipboard: {
    writeText: vi.fn(),
  },
});

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AnalyzerRecommendationPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const preliminaryResponse: AnalyzerRecommendationChatResponse = {
  conversation_id: 'conv-1',
  stale: true,
  response_type: 'analyzer_recommendation',
  recommendation_mode: 'preliminary',
  context_hash: 'hash-1',
  context_version: 1,
  normalized_goals: [],
  assistant_message: {
    headline: 'Preliminary recommendation based on metric context.',
    summary: 'This recommendation is based on metric context and operational goals.',
    context_used: ['metric_name', 'metric_description'],
    next_action: 'Review the evidence or upload a representative sample.',
  },
  recommendations: [
    {
      analyzer_id: 'trend',
      display_name: 'Trend Analyzer',
      recommendation: 'recommended',
      fitness_score: 0.78,
      decision_confidence: 0.9,
      summary: 'Matches gradual growth behavior.',
      evidence: { slope: 0.12 },
      requirements: [],
      warnings: [],
      parameters_tested: {},
    },
    {
      analyzer_id: 'baseline_shift',
      display_name: 'Baseline Shift',
      recommendation: 'conditional',
      fitness_score: 0.52,
      decision_confidence: 0.78,
      summary: 'Needs historical sample to confirm a step change.',
      evidence: { sample_mode: 'preliminary' },
      requirements: ['historical sample'],
      warnings: [],
      parameters_tested: {},
    },
    {
      analyzer_id: 'stumpy',
      display_name: 'STUMPY Motif',
      recommendation: 'not_recommended',
      fitness_score: 0.18,
      decision_confidence: 0.63,
      summary: 'No repeated pattern evidence yet.',
      evidence: { motif_evidence: false },
      requirements: [],
      warnings: ['low confidence'],
      parameters_tested: {},
    },
  ],
  suggested_questions: ['Which analyzer should I try first?'],
  ai_opinion: { available: false, recommended: [], not_recommended: [], caveats: [], diverges_from_router: false },
};

const evaluatedResponseWithAiOpinion: AnalyzerRecommendationChatResponse = {
  ...preliminaryResponse,
  stale: false,
  recommendation_mode: 'evaluated',
  ai_opinion: {
    available: true,
    best_analyzer_id: 'baseline_shift',
    rationale: 'The sample shows a discrete step change rather than continuous drift.',
    recommended: [
      { analyzer_id: 'baseline_shift', recommendation: 'recommended', rank: 1, confidence: 0.8, reason: 'Best fit for the observed step change.' },
    ],
    not_recommended: [],
    caveats: ['Confirm with a longer window.'],
    diverges_from_router: true,
    router_top_analyzer_id: 'trend',
    unavailable_reason: null,
  },
};

describe('AnalyzerRecommendationPage scenarios', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('given preliminary analyzer recommendations with stale context, groups results and warns before treating them as final', async () => {
    vi.mocked(api.metricAnalyzerSamples).mockResolvedValue([]);
    vi.mocked(api.metricAnalyzerChat).mockResolvedValue(preliminaryResponse);

    renderPage();

    fireEvent.change(await screen.findByLabelText(/Metric Name/), { target: { value: 'container_memory_usage_bytes' } });
    fireEvent.change(screen.getByLabelText(/Metric Description/), {
      target: { value: 'Current memory consumed by a Kubernetes container.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Memory Template' }));
    fireEvent.click(screen.getByRole('button', { name: 'Get Preliminary Recommendation' }));

    await waitFor(() => expect(api.metricAnalyzerChat).toHaveBeenCalled());

    expect(await screen.findByText('Recommendation Results')).toBeInTheDocument();
    expect(screen.getByText('Metric context has changed. Reevaluate analyzers to refresh the recommendation.')).toBeInTheDocument();
    expect(screen.getByText(/Preliminary recommendation. Upload or select a representative historical sample/)).toBeInTheDocument();
    expect(screen.getByText('Trend Analyzer')).toBeInTheDocument();
    expect(screen.getByText('Baseline Shift')).toBeInTheDocument();
    expect(screen.getByText('STUMPY Motif')).toBeInTheDocument();
    expect(screen.getByText('Fitness 18%')).toBeInTheDocument();
    expect(screen.getByText('Confidence 63%')).toBeInTheDocument();
    expect(screen.queryByText('Second Opinion')).not.toBeInTheDocument();
  });

  it('renders every recommendation value the backend returns, so optional and rejected analyzers are never dropped', async () => {
    const base = preliminaryResponse.recommendations[0];
    vi.mocked(api.metricAnalyzerSamples).mockResolvedValue([]);
    vi.mocked(api.metricAnalyzerChat).mockResolvedValue({
      ...preliminaryResponse,
      recommendations: [
        { ...base, analyzer_id: 'pyod_outlier', display_name: 'PyOD Outlier', recommendation: 'optional' },
        { ...base, analyzer_id: 'kats', display_name: 'Kats', recommendation: 'rejected' },
        { ...base, analyzer_id: 'forecasting', display_name: 'Forecasting', recommendation: 'conditional' },
      ],
    });

    renderPage();

    fireEvent.change(await screen.findByLabelText(/Metric Name/), { target: { value: 'cpu_usage' } });
    fireEvent.change(screen.getByLabelText(/Metric Description/), { target: { value: 'CPU usage.' } });
    fireEvent.click(screen.getByRole('button', { name: 'CPU Template' }));
    fireEvent.click(screen.getByRole('button', { name: 'Get Preliminary Recommendation' }));

    expect(await screen.findByText('Recommendation Results')).toBeInTheDocument();
    for (const analyzerId of ['pyod_outlier', 'kats', 'forecasting']) {
      expect(screen.getByRole('button', { name: `Copy snippet for ${analyzerId}` })).toBeInTheDocument();
    }
  });

  it('shows the AI second opinion and flags divergence from the router without hiding the deterministic recommendations', async () => {
    vi.mocked(api.metricAnalyzerSamples).mockResolvedValue([]);
    vi.mocked(api.metricAnalyzerChat).mockResolvedValue(evaluatedResponseWithAiOpinion);

    renderPage();

    fireEvent.change(await screen.findByLabelText(/Metric Name/), { target: { value: 'container_memory_usage_bytes' } });
    fireEvent.change(screen.getByLabelText(/Metric Description/), {
      target: { value: 'Current memory consumed by a Kubernetes container.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Memory Template' }));
    fireEvent.click(screen.getByRole('button', { name: 'Get Preliminary Recommendation' }));

    await waitFor(() => expect(api.metricAnalyzerChat).toHaveBeenCalled());

    expect(await screen.findByText('Recommendation Results')).toBeInTheDocument();
    expect(screen.getByText('Trend Analyzer')).toBeInTheDocument();
    expect(screen.getByText('Second Opinion')).toBeInTheDocument();
    expect(screen.getByText(/disagrees with the router's own top-scored pick \(trend\)/)).toBeInTheDocument();
    expect(screen.getByText('Best pick: baseline_shift')).toBeInTheDocument();
    expect(screen.getByText('The sample shows a discrete step change rather than continuous drift.')).toBeInTheDocument();
    expect(screen.getByText('Confirm with a longer window.')).toBeInTheDocument();
  });
});
