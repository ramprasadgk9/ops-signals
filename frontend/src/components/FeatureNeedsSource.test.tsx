import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/queries';
import { FeatureNeedsSource } from './FeatureNeedsSource';
import { HIDDEN_NAV_FEATURES_KEY } from '../utils/hiddenNavFeatures';
import type { FeatureAvailability, IngestionStatus } from '../types';

vi.mock('../api/queries', () => ({ api: { ingestionStatus: vi.fn() } }));

function memoryStorage(): Storage {
  const items = new Map<string, string>();
  return {
    get length() { return items.size; },
    clear: () => items.clear(),
    getItem: (key: string) => items.get(key) ?? null,
    key: (index: number) => [...items.keys()][index] ?? null,
    removeItem: (key: string) => { items.delete(key); },
    setItem: (key: string, value: string) => { items.set(key, value); },
  };
}

function status(features: FeatureAvailability[], alertsAt: string | null = null): IngestionStatus {
  return {
    generated_at: new Date().toISOString(),
    has_any_data: true,
    sources: {
      otlp: { endpoint_path: '/api/otlp/v1/metrics', last_received_at: new Date().toISOString() },
      alertmanager: { endpoint_path: '/api/integrations/alertmanager', enabled: false, token_required: false, last_received_at: alertsAt, received_24h: 0 },
      prometheus: { configured: false },
    },
    features,
  };
}

const off = (id: string, missing: FeatureAvailability['missing'], label = id): FeatureAvailability => ({ id, label, state: 'off', missing, detail: null });

function renderGate(feature: string, keepContent = false) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <FeatureNeedsSource feature={feature} keepContent={keepContent}>
          <p>page body</p>
        </FeatureNeedsSource>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('FeatureNeedsSource', () => {
  beforeEach(() => vi.stubGlobal('localStorage', memoryStorage()));
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  it('explains an off feature in place of the page, names what it needs and links to Integrations', async () => {
    vi.mocked(api.ingestionStatus).mockResolvedValue(status([off('metric_usage', ['prometheus'], 'Metric Usage')]));
    renderGate('metric_usage');

    expect(await screen.findByText('Find blind spots and metrics nobody uses')).toBeInTheDocument();
    expect(screen.getByText('Needs a Prometheus-compatible source')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Connect on Integrations' })).toHaveAttribute('href', '/integrations');
    expect(screen.queryByText('page body')).not.toBeInTheDocument();
  });

  it('joins several missing sources into one sentence', async () => {
    vi.mocked(api.ingestionStatus).mockResolvedValue(status([off('alert_enrichment', ['alertmanager', 'prometheus'])]));
    renderGate('alert_enrichment');

    expect(await screen.findByText('Needs Alertmanager and a Prometheus-compatible source')).toBeInTheDocument();
  });

  it.each([
    ['on', { id: 'metric_usage', label: 'Metric Usage', state: 'on', missing: [], detail: null }],
    ['partly', { id: 'metric_usage', label: 'Metric Usage', state: 'partly', missing: ['grafana'], detail: 'Reads rules only' }],
  ] as const)('leaves the page alone when the feature is %s', async (_state, feature) => {
    vi.mocked(api.ingestionStatus).mockResolvedValue(status([{ ...feature, missing: [...feature.missing] }]));
    renderGate('metric_usage');

    expect(await screen.findByText('page body')).toBeInTheDocument();
    expect(screen.queryByTestId('feature-needs-source')).not.toBeInTheDocument();
  });

  it('leaves the page alone when availability is unknown (the status call failed)', async () => {
    vi.mocked(api.ingestionStatus).mockRejectedValue(new Error('offline'));
    renderGate('metric_usage');

    expect(await screen.findByText('page body')).toBeInTheDocument();
    expect(screen.queryByTestId('feature-needs-source')).not.toBeInTheDocument();
  });

  it('leaves the page alone when an older backend sends no feature list', async () => {
    const legacy = status([]);
    delete legacy.features;
    vi.mocked(api.ingestionStatus).mockResolvedValue(legacy);
    renderGate('metric_usage');

    expect(await screen.findByText('page body')).toBeInTheDocument();
  });

  it('keeps earlier results visible under a short note when the page has history', async () => {
    vi.mocked(api.ingestionStatus).mockResolvedValue(status([off('metric_usage', ['prometheus'], 'Metric Usage')]));
    renderGate('metric_usage', true);

    expect(await screen.findByText(/Metric Usage is off until you connect a Prometheus-compatible source/)).toBeInTheDocument();
    expect(screen.getByText('page body')).toBeInTheDocument();
  });

  it('hides the feature from the menu and brings it back', async () => {
    vi.mocked(api.ingestionStatus).mockResolvedValue(status([off('metric_usage', ['prometheus'])]));
    renderGate('metric_usage');

    fireEvent.click(await screen.findByRole('button', { name: 'Hide from menu' }));
    expect(window.localStorage.getItem(HIDDEN_NAV_FEATURES_KEY)).toBe('["metric_usage"]');

    fireEvent.click(screen.getByRole('button', { name: 'Show in menu' }));
    expect(window.localStorage.getItem(HIDDEN_NAV_FEATURES_KEY)).toBeNull();
    expect(screen.getByRole('button', { name: 'Hide from menu' })).toBeInTheDocument();
  });
});
