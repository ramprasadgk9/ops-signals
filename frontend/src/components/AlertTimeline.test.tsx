import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { AlertsOverviewPanel, groupAlerts, severityKey, summarizeAlerts } from './AlertTimeline';
import { api } from '../api/queries';
import type { AlertItem } from '../types';

vi.mock('../api/queries', () => ({
  api: {
    alerts: vi.fn(),
  },
}));

const HOUR = 3_600_000;
const ago = (hours: number) => new Date(Date.now() - hours * HOUR).toISOString();

function alert(overrides: Partial<AlertItem>): AlertItem {
  return {
    id: 1,
    source: 'alertmanager',
    alert_name: 'DemoMixedLabLatencyHigh',
    status: 'resolved',
    service: 'mixed-lab',
    severity: 'warning',
    summary: 'mixed-lab p95 latency above 300ms',
    starts_at: ago(5),
    ends_at: ago(4.5),
    received_at: ago(5),
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

// The shape from the screenshot that prompted this: two rules, many occurrences.
const alerts: AlertItem[] = [
  alert({ id: 1, alert_name: 'DemoMockTargetUp', service: 'ops-signals-mock', severity: 'info', status: 'firing', starts_at: ago(3), ends_at: null, received_at: ago(3) }),
  alert({ id: 2, status: 'firing', starts_at: ago(3), ends_at: null, received_at: ago(3), finding_id: 100 }),
  alert({ id: 3, starts_at: ago(5), ends_at: ago(4.5), received_at: ago(5), finding_id: 99 }),
  alert({ id: 4, alert_name: 'DemoMockTargetUp', service: 'ops-signals-mock', severity: 'info', starts_at: ago(5), ends_at: ago(4), received_at: ago(5) }),
  alert({ id: 5, starts_at: ago(15), ends_at: ago(14), received_at: ago(15) }),
];

function renderPanel(props: Partial<React.ComponentProps<typeof AlertsOverviewPanel>> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AlertsOverviewPanel title="Alerts" {...props} />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('groupAlerts', () => {
  it('collapses occurrences into one group per rule, firing and linked first', () => {
    const groups = groupAlerts(alerts);

    expect(groups.map((group) => [group.alertName, group.occurrences.length])).toEqual([
      ['DemoMixedLabLatencyHigh', 3],
      ['DemoMockTargetUp', 2],
    ]);
    expect(groups[0].firing).toBe(true);
    // The link comes from the newest linked occurrence.
    expect(groups[0].link).toEqual({ text: 'Finding #100', to: '/findings?finding=100' });
    expect(groups[1].link).toBeNull();
    expect(groups[1].severity).toBe('other');
  });

  it('keeps the same rule on different services apart and prefers a case link', () => {
    const groups = groupAlerts([
      alert({ id: 1, service: 'a', case_id: 7, finding_id: 70 }),
      alert({ id: 2, service: 'b' }),
    ]);
    expect(groups).toHaveLength(2);
    expect(groups[0].link).toEqual({ text: 'Case #7', to: '/cases/7' });
  });

  it('uses the most severe level seen across occurrences', () => {
    const [group] = groupAlerts([alert({ id: 1, severity: 'warning' }), alert({ id: 2, severity: 'critical' })]);
    expect(group.severity).toBe('critical');
  });
});

describe('summarizeAlerts / severityKey', () => {
  it('counts firing, linked and resolved occurrences', () => {
    expect(summarizeAlerts(alerts)).toEqual({ firing: 2, linked: 2, resolved: 3 });
  });

  it('maps common severity spellings and treats anything else as info', () => {
    expect(severityKey('CRITICAL')).toBe('critical');
    expect(severityKey('page')).toBe('critical');
    expect(severityKey('warn')).toBe('warning');
    expect(severityKey('info')).toBe('other');
    expect(severityKey(null)).toBe('other');
  });
});

describe('AlertsOverviewPanel', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('shows the summary, one timeline lane per rule and a grouped list', async () => {
    vi.mocked(api.alerts).mockResolvedValue(alerts);

    renderPanel();

    const summary = await screen.findByLabelText('Alert summary');
    expect(within(summary).getByText('firing now').previousSibling).toHaveTextContent('2');
    expect(within(summary).getByText('linked to a finding').previousSibling).toHaveTextContent('2');
    expect(within(summary).getByText('resolved (24h)').previousSibling).toHaveTextContent('3');

    const timeline = screen.getByRole('figure', { name: 'Alert timeline, last 24 hours' });
    // One bar per occurrence, each focusable with its own description.
    expect(within(timeline).getAllByLabelText(/^DemoMixedLabLatencyHigh, /)).toHaveLength(3);
    expect(within(timeline).getAllByLabelText(/^DemoMockTargetUp, /)).toHaveLength(2);
    // Linked occurrences get a marker that opens the finding.
    expect(within(timeline).getByRole('link', { name: 'DemoMixedLabLatencyHigh linked to Finding #100' })).toHaveAttribute('href', '/findings?finding=100');

    const list = screen.getByLabelText('Alert rules');
    expect(within(list).getAllByText('FIRING')).toHaveLength(2);
    expect(within(list).getByText(/3× in 24h/)).toBeInTheDocument();
    expect(within(list).getByRole('link', { name: 'linked to Finding #100' })).toBeInTheDocument();

    expect(api.alerts).toHaveBeenCalledWith(expect.objectContaining({ limit: 500, since: expect.any(String) }));
    const since = Date.parse(vi.mocked(api.alerts).mock.calls[0][0]!.since!);
    expect(Math.abs(Date.now() - 24 * HOUR - since)).toBeLessThan(60_000);
  });

  it('expands a rule to its individual occurrences', async () => {
    vi.mocked(api.alerts).mockResolvedValue(alerts);
    renderPanel();

    const toggle = await screen.findByRole('button', { name: '3 occurrences' });
    fireEvent.click(toggle);

    expect(screen.getByRole('button', { name: 'Hide' })).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getAllByText('mixed-lab p95 latency above 300ms')).toHaveLength(3);
  });

  it('compact variant keeps the summary and timeline but drops the list', async () => {
    vi.mocked(api.alerts).mockResolvedValue(alerts);
    renderPanel({ variant: 'compact', viewAllTo: '/integrations' });

    expect(await screen.findByRole('figure', { name: /Alert timeline/ })).toBeInTheDocument();
    expect(screen.queryByLabelText('Alert rules')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'All alerts →' })).toHaveAttribute('href', '/integrations');
  });

  it('limits timeline lanes and points to the list for the rest', async () => {
    vi.mocked(api.alerts).mockResolvedValue(
      Array.from({ length: 4 }, (_, index) => alert({ id: index + 1, alert_name: `Rule${index}` }))
    );
    renderPanel({ maxLanes: 3 });

    expect(await screen.findByText('+1 more alert rule in the list below')).toBeInTheDocument();
  });

  it('renders nothing when hidden-when-empty and no alerts arrived', async () => {
    vi.mocked(api.alerts).mockResolvedValue([]);
    const { container } = renderPanel({ hideWhenEmpty: true });
    await waitFor(() => expect(api.alerts).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('shows an empty state otherwise', async () => {
    vi.mocked(api.alerts).mockResolvedValue([]);
    renderPanel();
    expect(await screen.findByText(/No alerts in the last 24 hours/)).toBeInTheDocument();
  });
});
