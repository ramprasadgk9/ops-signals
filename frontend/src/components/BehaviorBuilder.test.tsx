import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/queries';
import { BehaviorBuilder, BLANK_SEED, seedFromCatalog, seedFromDefinition, type BuilderSeed } from './BehaviorBuilder';

vi.mock('../api/queries', () => ({
  api: {
    behaviorFacts: vi.fn().mockResolvedValue([]),
    behaviorAvailableMetrics: vi.fn(),
    validateBehaviorDefinition: vi.fn(),
    saveBehaviorDefinitionToPack: vi.fn(),
    behaviorHistoryServices: vi.fn().mockResolvedValue([]),
    behaviorHistoryPreview: vi.fn(),
  },
}));

function renderPage(props: Parameters<typeof BehaviorBuilder>[0] = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <BehaviorBuilder {...props} />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const TWO_INPUTS: BuilderSeed = {
  ...BLANK_SEED,
  id: 'consumer',
  title: 'Consumer',
  inputs: [
    { alias: 'lag', metricName: 'kafka_consumergroup_lag', analyzers: 'trend' },
    { alias: 'incoming', metricName: 'kafka_topic_messages_in_rate', analyzers: '' },
  ],
};

/** The conditions the builder would send, read off the Validate call. */
async function sentConditions() {
  vi.mocked(api.validateBehaviorDefinition).mockResolvedValue({ valid: true, errors: [], warnings: [] });
  fireEvent.click(screen.getByRole('button', { name: 'Validate' }));
  await vi.waitFor(() => expect(api.validateBehaviorDefinition).toHaveBeenCalled());
  const draft = vi.mocked(api.validateBehaviorDefinition).mock.calls.at(-1)![0];
  return draft;
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

describe('BehaviorBuilder conditions in plain words', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('adds one condition per metric, each saying it is rising', async () => {
    vi.mocked(api.behaviorAvailableMetrics).mockResolvedValue([]);
    renderPage({ seed: TWO_INPUTS });
    fireEvent.click(screen.getByRole('button', { name: 'Add all condition' }));
    fireEvent.click(screen.getByRole('button', { name: 'Add all condition' }));

    expect(screen.getAllByRole('combobox', { name: 'What happens' })).toHaveLength(2);
    expect(screen.queryByPlaceholderText('cpu.anomaly.present')).not.toBeInTheDocument();
    const draft = await sentConditions();
    expect(draft.conditions.all).toEqual([
      { fact: 'lag.change.upward', operator: 'equals', value: true },
      { fact: 'incoming.change.upward', operator: 'equals', value: true },
    ]);
  });

  it('keeps an analyzer that can see the chosen change', async () => {
    vi.mocked(api.behaviorAvailableMetrics).mockResolvedValue([]);
    renderPage({ seed: { ...TWO_INPUTS, conditionsAll: [{ fact: 'lag.change.upward', operator: 'equals', value: true }] } });

    fireEvent.mouseDown(screen.getByRole('combobox', { name: 'What happens' }));
    fireEvent.click(screen.getByRole('option', { name: 'has an unusual spike' }));

    const draft = await sentConditions();
    expect(draft.conditions.all).toEqual([{ fact: 'lag.anomaly.present', operator: 'equals', value: true }]);
    // lag listed only trend, which never reports a spike; incoming lists none, so any analyzer counts.
    expect(draft.inputs.map((input) => input.analyzers)).toEqual([['trend', 'anomaly_zscore', 'pyod_outlier'], []]);
  });

  it('asks for a percent when the change must be big enough', async () => {
    vi.mocked(api.behaviorAvailableMetrics).mockResolvedValue([]);
    renderPage({ seed: { ...TWO_INPUTS, conditionsAll: [{ fact: 'lag.change.upward', operator: 'equals', value: true }] } });

    fireEvent.mouseDown(screen.getByRole('combobox', { name: 'What happens' }));
    fireEvent.click(screen.getByRole('option', { name: 'went down by more than' }));
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Percent' }), { target: { value: '40' } });

    const draft = await sentConditions();
    expect(draft.conditions.all).toEqual([{ fact: 'lag.change.signed_change_percent', operator: 'less_than', value: -40 }]);
  });

  it('writes a condition by hand, and shows one it cannot say in plain words that way', async () => {
    vi.mocked(api.behaviorAvailableMetrics).mockResolvedValue([]);
    renderPage({ seed: { ...TWO_INPUTS, conditionsAny: [{ fact: 'lag.anomaly.max_score', operator: 'greater_than', value: 0.8 }] } });
    expect(screen.getByDisplayValue('lag.anomaly.max_score')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Add all condition' }));
    fireEvent.click(screen.getByRole('button', { name: 'Write All condition 1 by hand' }));
    fireEvent.change(screen.getAllByPlaceholderText('cpu.anomaly.present')[0], { target: { value: 'lag.anomaly.count' } });

    const draft = await sentConditions();
    expect(draft.conditions.all).toEqual([{ fact: 'lag.anomaly.count', operator: 'equals', value: true }]);
  });

  it('keeps every fact out of the way until asked for', async () => {
    vi.mocked(api.behaviorAvailableMetrics).mockResolvedValue([]);
    vi.mocked(api.behaviorFacts).mockResolvedValue([{ key: 'anomaly.present', description: 'Any anomaly.', example: true }]);
    renderPage();
    const summary = screen.getByRole('button', { name: /Advanced: all facts/ });
    expect(summary).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(summary);
    expect(summary).toHaveAttribute('aria-expanded', 'true');
    expect(await screen.findByText('anomaly.present')).toBeVisible();
  });
});

describe('BehaviorBuilder starting points', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  const template: BuilderSeed = {
    ...BLANK_SEED,
    id: 'consumer_falling_behind',
    inputs: [
      { alias: 'lag', metricName: 'consumer_lag', analyzers: '', label: 'Consumer lag rising', keywords: ['consumer', 'lag'] },
      { alias: 'produced', metricName: 'messages_in_rate', analyzers: '', label: 'Incoming messages rising', keywords: ['messages', 'produced'] },
    ],
  };

  it('fills in a template signal only one stored metric fits, and says it did', async () => {
    vi.mocked(api.behaviorAvailableMetrics).mockResolvedValue(['demo_consumer_lag', 'kafka_consumergroup_lag', 'kafka_topic_messages_in_rate']);
    renderPage({ seed: template });

    expect(await screen.findByText(/the only stored metric that looks like this one/)).toBeInTheDocument();
    const fields = screen.getAllByRole('combobox', { name: 'Metric name' });
    expect(fields[1]).toHaveValue('kafka_topic_messages_in_rate');
    // Two metrics fit the lag: that one is still the user's to pick.
    expect(fields[0]).toHaveValue('consumer_lag');
    expect(screen.getByRole('status')).toHaveTextContent('Pick your metric for Consumer lag rising first (step 2).');

    fireEvent.click(screen.getByRole('button', { name: 'kafka_consumergroup_lag' }));
    expect(fields[0]).toHaveValue('kafka_consumergroup_lag');
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('points a blank pattern at the known ones', () => {
    vi.mocked(api.behaviorAvailableMetrics).mockResolvedValue([]);
    const onBrowseKnown = vi.fn();
    renderPage({ onBrowseKnown });
    fireEvent.click(screen.getByRole('button', { name: 'See known patterns' }));
    expect(onBrowseKnown).toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: /Load Example/ })).not.toBeInTheDocument();
    expect(screen.queryByText('Select Existing Sample')).not.toBeInTheDocument();
  });

  it('shows no such pointer when started from something', () => {
    vi.mocked(api.behaviorAvailableMetrics).mockResolvedValue([]);
    renderPage({ seed: template });
    expect(screen.queryByRole('button', { name: 'See known patterns' })).not.toBeInTheDocument();
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
