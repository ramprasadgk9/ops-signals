import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { BenchmarkDashboardPage } from './BenchmarkDashboardPage';
import { api } from '../api/queries';
import type { BenchmarkReportResponse, BenchmarkScenarioDescriptor } from '../types/benchmark';

vi.mock('../api/queries', () => ({
  api: {
    benchmarkScenarios: vi.fn(),
    benchmarkReport: vi.fn(),
    runBenchmark: vi.fn(),
  },
}));

const mockScenarios: BenchmarkScenarioDescriptor[] = [
  {
    id: 'scenario_01_resource_degradation',
    title: 'Resource Degradation',
    entity: 'payment-service',
    root_cause: 'MEMORY_LEAK',
    fault_window: {
      start: '2026-09-07T10:30:00+00:00',
      end: '2026-09-07T11:45:00+00:00',
    },
    key_evidence: {
      metrics: ['memory_usage', 'cpu_throttled_seconds'],
      signals: ['trend', 'baseline_shift'],
    },
    has_metrics: true,
    has_events: true,
  },
];

const mockReport: BenchmarkReportResponse = {
  report_path: '/path/to/benchmark_report.json',
  generated_at: '2026-09-10T18:00:00Z',
  scenarios: [
    {
      scenario: 'scenario_01_resource_degradation',
      ground_truth: {
        scenario_id: '01_resource_degradation',
        entity: 'payment-service',
        root_cause: 'MEMORY_LEAK',
      },
      iam: {
        runner_id: 'iam_slice_runner',
        status: 'SUCCESS',
        entity: 'payment-service',
        root_cause: 'MEMORY_LEAK',
        summary_text: 'Memory leak confirmed by sustained upward trend.',
        window_iou: 0.65,
        evidence_f1: 0.89,
        composite_score: 0.89,
        tokens: 0,
        cost_usd: 0.0,
        execution_time_seconds: 0.084,
        metadata: {
          executed_analyzers: ['baseline_shift', 'trend'],
          finding_count: 2,
          signal_count: 3,
        },
        judge: {
          consensus: {
            judge_id: 'consensus',
            attribution: 5,
            grounding: 5,
            actionability: 5,
            justification: 'Consensus across raters.',
          },
          scores: [],
        },
      },
      baseline_a: {
        runner_id: 'baseline_a_mock',
        status: 'SUCCESS',
        entity: 'payment-service',
        root_cause: 'MEMORY_LEAK',
        summary_text: 'Agent diagnosis.',
        window_iou: 0.60,
        evidence_f1: 0.86,
        composite_score: 0.86,
        tokens: 4240,
        cost_usd: 0.0175,
        execution_time_seconds: 0.001,
        metadata: {
          trajectory: [
            {
              turn: 1,
              thought: 'Investigate payment-service memory.',
              tool: 'query_prometheus',
              input: 'memory_usage',
              observation: 'High memory detected.',
            },
          ],
        },
        judge: {
          consensus: {
            judge_id: 'consensus',
            attribution: 5,
            grounding: 4,
            actionability: 5,
            justification: 'Good diagnosis.',
          },
          scores: [],
        },
      },
      baseline_b: {
        runner_id: 'baseline_b_mock',
        status: 'SUCCESS',
        entity: 'payment-service',
        root_cause: 'MEMORY_LEAK',
        summary_text: 'Signals agent diagnosis.',
        window_iou: 0.60,
        evidence_f1: 0.86,
        composite_score: 0.86,
        tokens: 2340,
        cost_usd: 0.0106,
        execution_time_seconds: 0.001,
      },
    },
  ],
  summary: {
    iam: {
      runs: 1,
      success_count: 1,
      partial_count: 0,
      failed_count: 0,
      success_rate_pct: 100.0,
      total_tokens: 0,
      total_cost_usd: 0.0,
      avg_latency_s: 0.084,
      avg_evidence_f1: 0.89,
      avg_judge_attribution: 5.0,
      avg_judge_grounding: 5.0,
      avg_judge_actionability: 5.0,
    },
    baseline_a: {
      runs: 1,
      success_count: 1,
      partial_count: 0,
      failed_count: 0,
      success_rate_pct: 100.0,
      total_tokens: 4240,
      total_cost_usd: 0.0175,
      avg_latency_s: 0.001,
      avg_evidence_f1: 0.86,
      avg_judge_attribution: 5.0,
      avg_judge_grounding: 4.0,
      avg_judge_actionability: 5.0,
    },
    baseline_b: {
      runs: 1,
      success_count: 1,
      partial_count: 0,
      failed_count: 0,
      success_rate_pct: 100.0,
      total_tokens: 2340,
      total_cost_usd: 0.0106,
      avg_latency_s: 0.001,
      avg_evidence_f1: 0.86,
      avg_judge_attribution: 5.0,
      avg_judge_grounding: 4.0,
      avg_judge_actionability: 5.0,
    },
    pareto: {
      token_reduction_vs_a_pct: 100.0,
      token_reduction_vs_b_pct: 100.0,
      cost_reduction_pct: 100.0,
      latency_speedup_vs_a_x: 0.1,
      iam_cost_per_incident: '$0.00',
      iam_token_usage: 0,
    },
  },
};

function renderBenchmarkDashboard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <BenchmarkDashboardPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('BenchmarkDashboardPage', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders benchmark dashboard with KPI metrics and scorecard table', async () => {
    vi.mocked(api.benchmarkScenarios).mockResolvedValue(mockScenarios);
    vi.mocked(api.benchmarkReport).mockResolvedValue(mockReport);

    renderBenchmarkDashboard();

    expect(await screen.findByText(/IAM vs. LLM Benchmark & Evaluation/i)).toBeInTheDocument();
    expect(screen.getAllByText(/\$0\.00/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/100% cost reduction vs LLM agents/i)).toBeInTheDocument();
    expect(screen.getByText(/Multi-Scenario Pareto Frontier Scorecard/i)).toBeInTheDocument();
    expect(screen.getAllByText(/IAM Engine/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Baseline A/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Baseline B/i).length).toBeGreaterThanOrEqual(1);

    // Verify Benchmark Analysis Card and Rating
    expect(screen.getByText(/Benchmark Analysis & Architectural Insights/i)).toBeInTheDocument();
    expect(screen.getByText(/9\.2 \/ 10/i)).toBeInTheDocument();
    expect(screen.getByText(/Grade: A-/i)).toBeInTheDocument();
  });

  it('navigates through architectural analysis tabs', async () => {
    vi.mocked(api.benchmarkScenarios).mockResolvedValue(mockScenarios);
    vi.mocked(api.benchmarkReport).mockResolvedValue(mockReport);

    renderBenchmarkDashboard();

    expect(await screen.findByText(/Benchmark Analysis & Architectural Insights/i)).toBeInTheDocument();

    // Default tab: Pareto Frontier & Efficiency
    expect(screen.getByText(/Core Takeaways on the Efficiency Frontier/i)).toBeInTheDocument();

    // Switch to Tab 2: Causal Attribution Under Stress
    const causalTab = screen.getByRole('tab', { name: /2\. Causal Attribution Under Stress/i });
    fireEvent.click(causalTab);

    expect(await screen.findByText(/Cascading Failure & Connection Pool Exhaustion/i)).toBeInTheDocument();
    expect(screen.getByText(/Benign Batch Maintenance \(False-Alarm Suppression\)/i)).toBeInTheDocument();
    expect(screen.getByText(/IAM Topology & Causal Traversal/i)).toBeInTheDocument();

    // Switch to Tab 3: Hybrid Architecture Blueprint
    const hybridTab = screen.getByRole('tab', { name: /3\. Hybrid Architecture Blueprint/i });
    fireEvent.click(hybridTab);

    expect(await screen.findByText(/Recommended Production Pipeline: Deterministic Triage Feeding an LLM Advisor/i)).toBeInTheDocument();
    expect(screen.getByText(/Deterministic IAM Algorithmic Triage Engine/i)).toBeInTheDocument();
    expect(screen.getByText(/Layer 4: LLM Incident Advisor/i)).toBeInTheDocument();
  });

  it('opens trajectory drawer when clicking inspect details', async () => {
    vi.mocked(api.benchmarkScenarios).mockResolvedValue(mockScenarios);
    vi.mocked(api.benchmarkReport).mockResolvedValue(mockReport);

    renderBenchmarkDashboard();

    expect(await screen.findByText(/Multi-Scenario Pareto Frontier Scorecard/i)).toBeInTheDocument();

    const inspectButtons = screen.getAllByRole('button', { name: /inspect trajectory/i });
    expect(inspectButtons.length).toBeGreaterThan(0);

    fireEvent.click(inspectButtons[0]);

    expect(await screen.findByText(/Diagnosis & Benchmark Evaluation/i)).toBeInTheDocument();
  });
});
