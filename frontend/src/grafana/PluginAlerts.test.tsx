import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AlertItem } from '../types';
import { listAlerts } from './backendClient';
import { PluginAlerts } from './PluginAlerts';

vi.mock('./backendClient', () => ({ listAlerts: vi.fn() }));
const alerts = vi.mocked(listAlerts);

function alert(overrides: Partial<AlertItem> = {}): AlertItem {
  const now = Date.now();
  return {
    id: 1,
    source: 'alertmanager',
    alert_name: 'CheckoutLatencyHigh',
    status: 'firing',
    service: 'checkout',
    severity: 'critical',
    summary: 'p95 above 800ms',
    starts_at: new Date(now - 30 * 60_000).toISOString(),
    ends_at: null,
    received_at: new Date(now - 30 * 60_000).toISOString(),
    labels: {},
    generator_url: null,
    analysis_status: null,
    recommendation: null,
    notify_status: null,
    finding_id: null,
    case_id: null,
    ...overrides,
  };
}

describe('PluginAlerts', () => {
  beforeEach(() => {
    alerts.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('groups alerts per rule, firing first, with the summary and what changed', async () => {
    alerts.mockResolvedValue([
      alert({ id: 1, alert_name: 'DiskFilling', service: 'db', status: 'resolved', severity: 'warning', ends_at: new Date().toISOString() }),
      alert({
        id: 2,
        finding_id: 9,
        case_id: 4,
        service_has_change_events: true,
        timing: { basis: 'alert_time', time: null, analyzer_id: null, trend_direction: null },
        changes: [{ id: 5, event_type: 'deploy', version: 'v2.3', description: null, author: 'ci', url: null, timestamp: new Date().toISOString(), minutes_before_anchor: 10 }],
      }),
      alert({ id: 3, received_at: new Date(Date.now() - 90 * 60_000).toISOString() }),
    ]);
    render(<PluginAlerts backendUrl="http://backend" onOpenCase={vi.fn()} />);

    const groups = await screen.findAllByTestId('plugin-alert-group');
    expect(alerts).toHaveBeenCalledWith('http://backend', expect.objectContaining({ limit: 500 }));
    expect(screen.getByTestId('plugin-alert-summary')).toHaveTextContent('2 firing now');
    expect(groups).toHaveLength(2);
    expect(groups[0]).toHaveTextContent('CheckoutLatencyHigh');
    expect(groups[0]).toHaveTextContent('FIRING');
    expect(groups[0]).toHaveTextContent('Critical · checkout · 2× in 24h');
    expect(groups[0]).toHaveTextContent('What changed');
    expect(groups[0]).toHaveTextContent('deploy v2.3');
    expect(groups[1]).toHaveTextContent('DiskFilling');
    expect(groups[1]).toHaveTextContent('RESOLVED');
    expect(groups[1]).toHaveTextContent('no matching finding yet');
  });

  it('opens the linked case and lists every occurrence on request', async () => {
    alerts.mockResolvedValue([alert({ id: 1, case_id: 4, finding_id: 9 }), alert({ id: 2 })]);
    const onOpenCase = vi.fn();
    render(<PluginAlerts backendUrl="http://backend" onOpenCase={onOpenCase} />);

    fireEvent.click(await screen.findByRole('button', { name: 'linked to Case #4' }));
    fireEvent.click(screen.getByRole('button', { name: '2 occurrences' }));

    expect(onOpenCase).toHaveBeenCalledWith(4);
    expect(screen.getAllByTestId('plugin-alert-occurrence')).toHaveLength(2);
  });

  it('says how to start receiving alerts when there are none', async () => {
    alerts.mockResolvedValue([]);
    render(<PluginAlerts backendUrl="http://backend" onOpenCase={vi.fn()} />);

    expect(await screen.findByText(/No alerts in the last 24 hours/)).toBeInTheDocument();
  });

  it('keeps the alerts shown when a refresh fails', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    alerts.mockResolvedValueOnce([alert()]).mockRejectedValue(new Error('down'));
    render(<PluginAlerts backendUrl="http://backend" onOpenCase={vi.fn()} />);
    await screen.findByTestId('plugin-alert-group');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });

    expect(alerts).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId('plugin-alert-group')).toBeInTheDocument();
    expect(screen.queryByText(/Could not load received alerts/)).not.toBeInTheDocument();
  });

  it('says when alerts could not be loaded', async () => {
    alerts.mockRejectedValue(new Error('down'));
    render(<PluginAlerts backendUrl="http://backend" onOpenCase={vi.fn()} />);

    expect(await screen.findByText(/Could not load received alerts/)).toBeInTheDocument();
  });
});
