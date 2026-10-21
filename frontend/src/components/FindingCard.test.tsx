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

  it('says when the data did not come from Prometheus', () => {
    renderCard({ ...plain, source: 'otlp' });
    expect(screen.getByText('drill-cart \u00b7 http_errors_total \u00b7 via OTLP')).toBeInTheDocument();
  });

  it('adds nothing for Prometheus or an unknown source', () => {
    renderCard({ ...plain, source: 'prometheus' });
    expect(screen.getByText('drill-cart \u00b7 http_errors_total')).toBeInTheDocument();
  });
});

describe('FindingCard Create Case', () => {
  it('says on hover that a Jira ticket can be created from the case', async () => {
    renderCard(newPodsFinding);

    fireEvent.mouseOver(screen.getByRole('button', { name: 'Create Case' }));

    expect(await screen.findByRole('tooltip')).toHaveTextContent(
      'Opens a case for this finding. From the case you can also create a Jira ticket.'
    );
  });
});

describe('FindingCard metric usage tag', () => {
  const usage = {
    metric: 'http_errors_total', status: 'watched' as const, connections: ['default'], via_recording_rules: [],
    problem_findings: 1, latest_finding_id: 7, analyzed: true, series: null,
    usages: [
      { kind: 'dashboard' as const, location: 'Production / API Health / Errors' },
      { kind: 'alert_rule' as const, location: 'Production / Errors high' },
    ],
  };

  function renderWithUsage(item?: typeof usage | (Omit<typeof usage, 'status'> & { status: 'blind_spot' })) {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <FindingCard finding={newPodsFinding} usage={item} />
        </MemoryRouter>
      </QueryClientProvider>
    );
  }

  it('names the dashboard and alerts that watch the metric', () => {
    renderWithUsage(usage);
    expect(screen.getByTestId('finding-watched-by')).toHaveTextContent('On API Health · 1 alert');
  });

  it('says when nothing watches the metric', () => {
    renderWithUsage({ ...usage, status: 'blind_spot', usages: [] });
    expect(screen.getByTestId('finding-watched-by')).toHaveTextContent('Not on any dashboard or alert');
  });

  it('shows no tag before any metric usage check', () => {
    renderWithUsage(undefined);
    expect(screen.queryByTestId('finding-watched-by')).toBeNull();
  });
});

describe('FindingCard problem timing', () => {
  it('shows whether the problem is still happening, from the latest run that saw it', () => {
    const first = { ...newPodsFinding, id: 1, event_start: '2026-10-12T09:00:00Z', event_end: '2026-10-12T09:10:00Z', ongoing: true };
    const latest = { ...first, id: 2, problem_id: 1, event_end: '2026-10-12T09:45:00Z', ongoing: false };
    render(
      <MemoryRouter>
        <QueryClientProvider client={new QueryClient()}>
          <FindingCard finding={first} repeats={{ count: 2, latest }} />
        </QueryClientProvider>
      </MemoryRouter>
    );

    expect(screen.getByTestId('finding-timing')).toHaveTextContent(/· over$/);
    expect(screen.queryByText('Seen in 2 runs')).not.toBeInTheDocument();
  });
});

describe('FindingCard plain wording', () => {
  const plainFinding: Finding = {
    ...newPodsFinding,
    comparison_json: {},
    plain: {
      kind: 'level_change',
      badge: 'worse',
      badge_label: 'Worse',
      headline: 'HTTP errors rose sharply and stayed higher',
      what: 'About 0.09 until [[time:2026-10-19T22:54:17Z]]. Since then about 1.3 (about 14 times as high).',
      why: 'More requests fail, so more users see errors or failed actions.',
      check: null,
      related: [],
    },
  };

  it('leads with the badge and headline, and keeps the stored text under Technical details', () => {
    renderCard(plainFinding);

    expect(screen.getByTestId('finding-plain-badge')).toHaveTextContent('Worse');
    expect(screen.getByText('HTTP errors rose sharply and stayed higher')).toBeInTheDocument();
    expect(screen.queryByText(newPodsFinding.title)).not.toBeInTheDocument();
    expect(screen.getByTestId('finding-plain-what').textContent).toMatch(/^About 0\.09 until Oct 19, .+\. Since then about 1\.3/);
    expect(screen.getByText('More requests fail, so more users see errors or failed actions.')).toBeInTheDocument();
    expect(screen.queryByTestId('finding-plain-details')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Technical details/ }));

    expect(screen.getByTestId('finding-plain-details')).toHaveTextContent(`${newPodsFinding.title} Errors rose.`);
  });

  it('shows the stored title and summary when there is no plain wording', () => {
    renderCard({ ...newPodsFinding, comparison_json: {}, plain: null });

    expect(screen.getByText(newPodsFinding.title)).toBeInTheDocument();
    expect(screen.getByText('Errors rose.')).toBeInTheDocument();
    expect(screen.queryByTestId('finding-plain')).not.toBeInTheDocument();
  });

  it("shows the service's importance and the target line when the wording file has them", () => {
    renderCard({
      ...plainFinding,
      plain: {
        ...plainFinding.plain!,
        target: 'Above your 1% target since [[time:2026-10-19T22:54:17Z]] (2 hours so far).',
        service_about: 'Customers pay for their orders here.',
        service_importance: 'critical',
        service_importance_label: 'Critical service',
      },
    });

    expect(screen.getByTestId('finding-plain-importance')).toHaveTextContent('Critical service');
    expect(screen.getByText('Your target')).toBeInTheDocument();
    expect(screen.getByText(/^Above your 1% target since Oct 19, .+ \(2 hours so far\)\.$/)).toBeInTheDocument();
    expect(screen.getByText('Customers pay for their orders here.')).toBeInTheDocument();
  });

  it('keeps the analyzer wording of the strongest signal under Technical details', async () => {
    const { PlainFindingSummary } = await import('./PlainFindingSummary');
    render(<PlainFindingSummary plain={plainFinding.plain!} summary="stored" signal="A stretch unlike the rest. (stumpy · confidence 1.00)" />);

    expect(screen.queryByTestId('finding-plain-signal')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Technical details/ }));
    expect(screen.getByTestId('finding-plain-signal')).toHaveTextContent('Strongest signal: A stretch unlike the rest. (stumpy · confidence 1.00)');
  });

  it('explains "Happened with" in a tooltip', async () => {
    const { PlainFindingSummary } = await import('./PlainFindingSummary');
    const related = { ...plainFinding.plain!, related: [{ finding_id: 8299, text: 'Slow-request time (p95) also rose at [[time:2026-10-19T22:54:17Z]] (357 ms to 571 ms).' }] };
    render(<PlainFindingSummary plain={related} summary="stored" />);

    fireEvent.mouseOver(screen.getByTestId('finding-plain-hint'));
    expect(await screen.findByRole('tooltip')).toHaveTextContent('within 10 minutes of this change');
  });
});
