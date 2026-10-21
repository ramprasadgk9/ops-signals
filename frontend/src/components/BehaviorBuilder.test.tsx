import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/queries';
import { BehaviorBuilder, seedFromCatalog, seedFromDefinition } from './BehaviorBuilder';

vi.mock('../api/queries', () => ({
  api: {
    behaviorFacts: vi.fn().mockResolvedValue([]),
    metricAnalyzerSamples: vi.fn().mockResolvedValue([]),
    behaviorAvailableMetrics: vi.fn(),
    validateBehaviorDefinition: vi.fn(),
    dryRunBehaviorDefinition: vi.fn(),
    saveBehaviorDefinitionToPack: vi.fn(),
  },
}));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <BehaviorBuilder />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('BehaviorBuilder metric name', () => {
  afterEach(() => {
    cleanup();
    vi.mocked(api.behaviorAvailableMetrics).mockReset();
  });

  it('suggests the metric names Ops Signals has stored, and fills one in when picked', async () => {
    vi.mocked(api.behaviorAvailableMetrics).mockResolvedValue(['container.memory.usage', 'cpu_usage', 'process_resident_memory_bytes']);
    renderPage();

    const field = screen.getByRole('combobox', { name: 'Metric name' });
    await vi.waitFor(() => expect(api.behaviorAvailableMetrics).toHaveBeenCalled());
    fireEvent.change(field, { target: { value: 'mem' } });

    expect(await screen.findByRole('option', { name: 'container.memory.usage' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'process_resident_memory_bytes' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'cpu_usage' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('option', { name: 'container.memory.usage' }));
    expect(field).toHaveValue('container.memory.usage');
  });

  it('still takes a name that is not stored yet', async () => {
    vi.mocked(api.behaviorAvailableMetrics).mockResolvedValue(['cpu_usage']);
    renderPage();

    const field = screen.getByRole('combobox', { name: 'Metric name' });
    fireEvent.change(field, { target: { value: 'k8s.pod.memory.usage' } });

    expect(field).toHaveValue('k8s.pod.memory.usage');
  });

  it('works as a plain text box when the list cannot be loaded', async () => {
    vi.mocked(api.behaviorAvailableMetrics).mockRejectedValue(new Error('offline'));
    renderPage();

    const field = screen.getByRole('combobox', { name: 'Metric name' });
    fireEvent.change(field, { target: { value: 'memory_usage' } });

    expect(field).toHaveValue('memory_usage');
  });
});

describe('seedFromDefinition', () => {
  it('fills every field from a definition as the API returns it, under a new id', () => {
    const seed = seedFromDefinition(
      {
        id: 'pool_exhaustion',
        title: 'Pool exhaustion',
        description: 'Wait and connections rise together.',
        inputs: [{ alias: 'db_wait', metric_name: 'db_connection_wait_seconds', analyzers: ['trend', 'ruptures'] }],
        conditions: { all: [{ fact: 'db_wait.change.upward', operator: 'equals', value: true }], any: [] },
        correlation: { max_time_gap: '30m', minimum_overlap: '5m' },
        output: { category: 'resource_constraint', severity: 'critical', title: 'Pool exhaustion', summary: 'Filling up.\n' },
      },
      '_copy',
    );
    expect(seed).toEqual({
      id: 'pool_exhaustion_copy',
      title: 'Pool exhaustion',
      description: 'Wait and connections rise together.',
      category: 'resource_constraint',
      severity: 'critical',
      outputTitle: 'Pool exhaustion',
      outputSummary: 'Filling up.',
      inputs: [{ alias: 'db_wait', metricName: 'db_connection_wait_seconds', analyzers: 'trend,ruptures' }],
      conditionsAll: [{ fact: 'db_wait.change.upward', operator: 'equals', value: true }],
      conditionsAny: [],
      maxTimeGap: '30m',
      minimumOverlap: '5m',
    });
  });

  it('falls back to a blank form for missing parts', () => {
    const seed = seedFromDefinition({ id: 'x' });
    expect(seed.inputs).toEqual([{ alias: '', metricName: '', analyzers: '' }]);
    expect(seed.severity).toBe('medium');
    expect(seed.maxTimeGap).toBe('15m');
  });
});

describe('seedFromCatalog', () => {
  it('labels each input with its signal and the words to find a metric by', () => {
    const seed = seedFromCatalog({
      key: 'retry_storm', rule: null, name: 'Retry storm', meaning: 'm', why: 'w', check_first: 'c', proof: 'common', scenarios: [],
      signals: [{ alias: 'errors', label: 'Error rate unusual', shape: 'unusual', metric_hint: 'error_rate', keywords: ['error', '5xx'], analyzers: ['pyod_outlier'] }],
      draft: { id: 'retry_storm', inputs: [{ alias: 'errors', metric_name: 'error_rate', analyzers: ['pyod_outlier'] }] },
    });
    expect(seed.id).toBe('retry_storm');
    expect(seed.inputs).toEqual([{ alias: 'errors', metricName: 'error_rate', analyzers: 'pyod_outlier', label: 'Error rate unusual', keywords: ['error', '5xx'] }]);
  });
});
