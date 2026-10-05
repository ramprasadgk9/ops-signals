import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { api } from '../api/queries';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { FindingCard } from './FindingCard';
import type { Finding } from '../types';

vi.mock('../api/queries', () => ({ api: { createCase: vi.fn(), prometheusConnections: vi.fn() } }));

const newPodsFinding: Finding = {
  id: 7,
  service: 'drill-cart',
  metric_name: 'http_errors_total',
  title: 'http_errors_total experienced a persistent baseline shift during the selected time window.',
  summary: 'Errors rose.',
  category: 'behavior_change',
  health_status: 'critical',
  importance_score: 0.85,
  investigation_priority: 1,
  signal_ids: [],
  comparison_json: {
    breakdown: {
      status: 'ok',
      label: 'pod',
      mode: 'share',
      spread: 'partial',
      direction: 'up',
      parts_total: 6,
      parts_changed: 2,
      new_parts: 2,
      top: [
        { value: 'cart-8c2-q1', before: null, after: 1.34, change: 1.34, relative_change: 11.8, share: 0.51, moved: true, new: true, gone: false },
        { value: 'cart-8c2-w7', before: null, after: 1.25, change: 1.25, relative_change: 11.0, share: 0.48, moved: true, new: true, gone: false },
        { value: 'cart-6b4-c3', before: 0.09, after: 0.1, change: 0.01, relative_change: 0.11, share: 0.01, moved: false, new: false, gone: false },
      ],
      others: null,
    },
  },
};

function renderCard(finding: Finding, onViewDetails = vi.fn()) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <FindingCard finding={finding} onViewDetails={onViewDetails} />
      </MemoryRouter>
    </QueryClientProvider>
  );
  return onViewDetails;
}

describe('FindingCard drill-down chip', () => {
  it('opens the finding details when clicked', () => {
    const onViewDetails = renderCard(newPodsFinding);

    fireEvent.click(screen.getByText('2 new pods'));

    expect(onViewDetails).toHaveBeenCalledWith(newPodsFinding);
  });

  it('names the pods on hover', async () => {
    renderCard(newPodsFinding);

    fireEvent.mouseOver(screen.getByText('2 new pods'));

    expect(await screen.findByText(/cart-8c2-q1, cart-8c2-w7\. Click for the full breakdown\./)).toBeInTheDocument();
  });

  it('shows no chip without a breakdown', () => {
    renderCard({ ...newPodsFinding, comparison_json: {} });

    expect(screen.queryByText('2 new pods')).not.toBeInTheDocument();
  });
});

describe('FindingCard identity', () => {
  it('shows the service and metric under the title', () => {
    renderCard(newPodsFinding);

    expect(screen.getByText('drill-cart \u00b7 http_errors_total')).toBeInTheDocument();
  });
});

describe('FindingCard connection', () => {
  const plain = { ...newPodsFinding, comparison_json: {} };

  it('names the Prometheus connection when there are several', async () => {
    vi.mocked(api.prometheusConnections).mockResolvedValue({
      connections: [
        { id: 'mimir-a', name: 'Mimir team A', configured: true, is_default: true },
        { id: 'mimir-b', name: 'Mimir team B', configured: true },
      ],
    });
    renderCard({ ...plain, connection_id: 'mimir-b' });

    expect(await screen.findByText(/Mimir team B/)).toBeInTheDocument();
  });

  it('says nothing about connections when there is only one', async () => {
    vi.mocked(api.prometheusConnections).mockResolvedValue({ connections: [{ id: 'default', name: 'Default Prometheus', configured: true }] });
    renderCard({ ...plain, connection_id: 'default' });

    await vi.waitFor(() => expect(api.prometheusConnections).toHaveBeenCalled());
    expect(screen.queryByText(/Default Prometheus/)).not.toBeInTheDocument();
  });
});
