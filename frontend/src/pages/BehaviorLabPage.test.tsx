import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/queries';
import { BehaviorLabPage } from './BehaviorLabPage';

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
        <BehaviorLabPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('BehaviorLabPage metric name', () => {
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
