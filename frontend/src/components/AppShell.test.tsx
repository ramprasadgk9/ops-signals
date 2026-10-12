import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/queries';
import { AppShell } from './AppShell';
import { HIDDEN_NAV_FEATURES_KEY } from '../utils/hiddenNavFeatures';
import type { FeatureAvailability, IngestionStatus } from '../types';

vi.mock('../api/queries', () => ({
  api: {
    health: vi.fn().mockResolvedValue({ status: 'ok' }),
    memoryHealth: vi.fn().mockResolvedValue({ status: 'ok' }),
    findingsSearch: vi.fn().mockResolvedValue([]),
    ingestionStatus: vi.fn(),
  },
}));

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

const feature = (id: string, state: FeatureAvailability['state']): FeatureAvailability => ({
  id, label: id, state, missing: state === 'off' ? ['prometheus'] : [], detail: null,
});

function status(features: FeatureAvailability[]): IngestionStatus {
  return {
    generated_at: new Date().toISOString(),
    has_any_data: true,
    sources: {
      otlp: { endpoint_path: '/api/otlp/v1/metrics', last_received_at: null },
      alertmanager: { endpoint_path: '/api/integrations/alertmanager', enabled: false, token_required: false, last_received_at: null, received_24h: 0 },
      prometheus: { configured: false },
    },
    features,
  };
}

const OTLP_ONLY = [
  feature('findings', 'on'),
  feature('alert_enrichment', 'off'),
  feature('autonomous_analysis', 'off'),
  feature('metric_usage', 'off'),
];

function renderShell() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AppShell>
          <p>page</p>
        </AppShell>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('AppShell navigation by feature availability', () => {
  beforeEach(() => vi.stubGlobal('localStorage', memoryStorage()));
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('moves pages whose feature is off into their own group, each marked Connect', async () => {
    vi.mocked(api.ingestionStatus).mockResolvedValue(status(OTLP_ONLY));
    renderShell();

    const group = await screen.findByTestId('nav-needs-source');
    expect(within(group).getByText('More with Prometheus / Grafana')).toBeInTheDocument();
    for (const label of ['Alerts', 'Autonomous Analysis Configure', 'Metric Usage']) {
      expect(within(group).getByRole('link', { name: new RegExp(label) })).toBeInTheDocument();
    }
    expect(within(group).getAllByText('Connect')).toHaveLength(3);
    // Pages that work stay in the main list.
    expect(within(group).queryByRole('link', { name: /Findings/ })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Findings/ })).toBeInTheDocument();
  });

  it('keeps a partly available page in the main list', async () => {
    vi.mocked(api.ingestionStatus).mockResolvedValue(status([feature('metric_usage', 'partly')]));
    renderShell();

    expect(await screen.findByRole('link', { name: /Metric Usage/ })).toBeInTheDocument();
    expect(screen.queryByTestId('nav-needs-source')).not.toBeInTheDocument();
  });

  it('shows the menu as before when availability is unknown', async () => {
    vi.mocked(api.ingestionStatus).mockRejectedValue(new Error('offline'));
    renderShell();

    expect(await screen.findByRole('link', { name: /Metric Usage/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Alerts/ })).toBeInTheDocument();
    expect(screen.queryByTestId('nav-needs-source')).not.toBeInTheDocument();
  });

  it('leaves out pages the viewer hid, with a way to bring them back', async () => {
    window.localStorage.setItem(HIDDEN_NAV_FEATURES_KEY, '["metric_usage"]');
    vi.mocked(api.ingestionStatus).mockResolvedValue(status(OTLP_ONLY));
    renderShell();

    const group = await screen.findByTestId('nav-needs-source');
    expect(within(group).queryByRole('link', { name: /Metric Usage/ })).not.toBeInTheDocument();

    fireEvent.click(within(group).getByRole('button', { name: 'Show 1 hidden' }));
    expect(within(group).getByRole('link', { name: /Metric Usage/ })).toBeInTheDocument();
    expect(window.localStorage.getItem(HIDDEN_NAV_FEATURES_KEY)).toBeNull();
  });

  it('ignores a hidden list it cannot read', async () => {
    window.localStorage.setItem(HIDDEN_NAV_FEATURES_KEY, 'not json');
    vi.mocked(api.ingestionStatus).mockResolvedValue(status(OTLP_ONLY));
    renderShell();

    const group = await screen.findByTestId('nav-needs-source');
    expect(within(group).getByRole('link', { name: /Metric Usage/ })).toBeInTheDocument();
  });
});
