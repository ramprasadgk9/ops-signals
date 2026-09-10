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
  });
});
