import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { BehaviorIntelligencePage } from './BehaviorIntelligencePage';
import { api } from '../api/queries';
import type { BehaviorFinding } from '../types';

vi.mock('../api/queries', () => ({
  api: {
    behaviorDefinitions: vi.fn().mockResolvedValue([]),
    behaviorFindings: vi.fn(),
    createCaseFromBehavior: vi.fn(),
  },
}));

function behavior(overrides: Partial<BehaviorFinding> = {}): BehaviorFinding {
  return {
    id: 1,
    behavior_id: 'memory-leak-1',
    definition_id: 'memory_leak',
    definition_version: 1,
    title: 'Memory leak driving resource degradation',
    summary: 'Sustained upward memory trend was accompanied by increased CPU throttling.',
    category: 'resource_constraint',
    severity: 'critical',
    service: 'payments-service',
    input_metrics_json: { memory: 'memory_usage', throttling: 'cpu_throttled_seconds' },
    facts_json: {},
    evidence_json: ['memory.trend.direction'],
    matched_conditions_json: [],
    confidence: 0.88,
    correlation_json: {},
    case_id: null,
    occurrence_count: 1,
    last_seen_at: '2026-09-08T00:00:00Z',
    created_at: '2026-09-08T00:00:00Z',
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<BehaviorIntelligencePage />} />
          <Route path="/cases/:id" element={<div>Case details page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('BehaviorIntelligencePage', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('lets an uncased behavior be turned into a case and navigates to it', async () => {
    vi.mocked(api.behaviorFindings).mockResolvedValue([behavior()]);
    vi.mocked(api.createCaseFromBehavior).mockResolvedValue({
      case_id: 77,
      behavior_finding_id: 1,
      case_status: 'open',
      memory_status: 'not_indexed',
    });

    renderPage();

    const createButton = await screen.findByRole('button', { name: 'Create Case' });
    fireEvent.click(createButton);

    expect(await screen.findByText('Case details page')).toBeInTheDocument();
    expect(api.createCaseFromBehavior).toHaveBeenCalledWith(1);
  });

  it('shows a View Case link instead, once a behavior already has one', async () => {
    vi.mocked(api.behaviorFindings).mockResolvedValue([behavior({ case_id: 42 })]);

    renderPage();

    expect(await screen.findByRole('link', { name: 'View Case' })).toHaveAttribute('href', '/cases/42');
    expect(screen.queryByRole('button', { name: 'Create Case' })).not.toBeInTheDocument();
  });
});
