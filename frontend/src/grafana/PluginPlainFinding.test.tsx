import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PluginPlainBadge, PluginPlainFinding } from './PluginPlainFinding';
import { PermissionsProvider } from './permissions';

const { getFindingAiWording } = vi.hoisted(() => ({ getFindingAiWording: vi.fn() }));
vi.mock('./backendClient', () => ({ getFindingAiWording }));
import type { FindingPlain } from '../types';

const gap: FindingPlain = {
  kind: 'data_gap',
  badge: 'gap',
  badge_label: 'Monitoring gap',
  headline: 'We lost alert-notification errors data for 22 hours',
  what: 'No data from [[time:2026-10-19T21:40:00Z]] to [[time:2026-10-20T19:32:00Z]] (1,311 readings missing).',
  why: "Alerts and dashboards using this metric couldn't see problems during this time.",
  check: 'Is the data source running? Did the metric name or a label change?',
  related: [],
};

describe('PluginPlainFinding', () => {
  it('shows what changed, why it matters and what to check, with the stored text folded away', () => {
    render(<PluginPlainFinding plain={gap} details="prometheus_notifications_errors_total stopped reporting for 21.9 hours." />);

    const shown = screen.getByTestId('plugin-plain');
    expect(shown).not.toHaveTextContent('[[time:');
    expect(shown).toHaveTextContent('(1,311 readings missing).');
    expect(screen.getByText('Why it matters')).toBeInTheDocument();
    expect(screen.getByText('Is the data source running? Did the metric name or a label change?')).toBeInTheDocument();
    expect(screen.queryByTestId('plugin-plain-details')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Technical details/ }));

    expect(screen.getByTestId('plugin-plain-details')).toHaveTextContent('stopped reporting for 21.9 hours.');
  });

  it('labels the badge from the wording file', () => {
    render(<PluginPlainBadge plain={gap} />);
    expect(screen.getByTestId('plugin-plain-badge')).toHaveTextContent('Monitoring gap');
  });

  it("shows the service's importance next to the badge", () => {
    render(<PluginPlainBadge plain={{ ...gap, service_importance: 'critical', service_importance_label: 'Critical service' }} />);
    expect(screen.getByTestId('plugin-plain-importance')).toHaveTextContent('Critical service');
  });

  it('shows no importance label for a service without one', () => {
    render(<PluginPlainBadge plain={gap} />);
    expect(screen.queryByTestId('plugin-plain-importance')).not.toBeInTheDocument();
  });

  it('keeps the strongest signal in analyzer words under Technical details', () => {
    render(<PluginPlainFinding plain={gap} details="stored text" signal="A stretch unlike the rest. (stumpy · confidence 1.00)" />);

    expect(screen.queryByTestId('plugin-plain-signal')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Technical details/ }));
    expect(screen.getByTestId('plugin-plain-signal')).toHaveTextContent('Strongest signal: A stretch unlike the rest. (stumpy · confidence 1.00)');
  });

  it('explains "Happened with" in a tooltip', () => {
    const related = { ...gap, related: [{ finding_id: 8299, text: 'Slow-request time (p95) also dropped at [[time:2026-10-19T22:54:17Z]] (571 ms to 357 ms).' }] };
    render(<PluginPlainFinding plain={related} details="stored text" />);

    const hint = screen.getByTestId('plugin-plain-hint');
    expect(hint).toHaveTextContent('Happened with');
    expect(hint).toHaveAttribute('title', expect.stringContaining('within 10 minutes'));
    expect(screen.getAllByTestId('plugin-plain-hint')).toHaveLength(1);
  });
});

// Same as AppShell.test.tsx: Node's own localStorage global hides jsdom's.
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

describe('PluginPlainFinding with AI wording', () => {
  beforeEach(() => vi.stubGlobal('localStorage', memoryStorage()));
  afterEach(() => {
    getFindingAiWording.mockReset();
    vi.unstubAllGlobals();
  });

  it('asks for AI lines for a saved finding and marks the ones it wrote', async () => {
    getFindingAiWording.mockResolvedValue({ available: true, why: 'The alert sender may be down, so alerts can go missing.', check_extra: null, related_extra: null, model: 'test-model' });
    render(<PluginPlainFinding plain={gap} details="stored" findingId={8305} backendUrl="http://backend" />);

    expect(await screen.findByTestId('plugin-plain-ai')).toBeInTheDocument();
    expect(getFindingAiWording).toHaveBeenCalledWith('http://backend', 8305);
    expect(screen.getByTestId('plugin-plain')).toHaveTextContent('The alert sender may be down, so alerts can go missing.');
    expect(screen.getByTestId('plugin-plain-ai-footer')).toHaveTextContent("Written by AI (test-model) from this finding's facts");

    fireEvent.click(screen.getByRole('button', { name: 'Show template wording' }));
    expect(screen.getByTestId('plugin-plain')).toHaveTextContent("Alerts and dashboards using this metric couldn't see problems during this time.");
    expect(screen.queryByTestId('plugin-plain-ai')).not.toBeInTheDocument();
  });

  it('does not ask without a finding id', () => {
    render(<PluginPlainFinding plain={gap} details="stored" backendUrl="http://backend" />);
    expect(getFindingAiWording).not.toHaveBeenCalled();
  });

  it('offers admins how to turn AI on, until they choose Not now', async () => {
    getFindingAiWording.mockResolvedValue({ available: false, reason: 'ai_off' });
    const { unmount } = render(<PluginPlainFinding plain={gap} details="stored" findingId={8305} backendUrl="http://backend" />);

    expect(await screen.findByTestId('plugin-enable-ai-hint')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'How to turn it on' }));
    expect(screen.getByTestId('plugin-enable-ai-hint')).toHaveTextContent('docker compose --profile ai up -d');
    fireEvent.click(screen.getByRole('button', { name: 'Not now' }));
    expect(screen.queryByTestId('plugin-enable-ai-hint')).not.toBeInTheDocument();
    unmount();

    render(<PluginPlainFinding plain={gap} details="stored" findingId={8305} backendUrl="http://backend" />);
    await waitFor(() => expect(getFindingAiWording).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId('plugin-enable-ai-hint')).not.toBeInTheDocument();
  });

  it('does not offer it to Viewers, who cannot turn it on', async () => {
    getFindingAiWording.mockResolvedValue({ available: false, reason: 'ai_off' });
    render(
      <PermissionsProvider role="Viewer">
        <PluginPlainFinding plain={gap} details="stored" findingId={8305} backendUrl="http://backend" />
      </PermissionsProvider>,
    );
    await waitFor(() => expect(getFindingAiWording).toHaveBeenCalled());
    expect(screen.queryByTestId('plugin-enable-ai-hint')).not.toBeInTheDocument();
  });
});

describe('PluginPlainFinding with an alert on the metric', () => {
  it("shows the team's words and the runbook link", () => {
    render(
      <PluginPlainFinding
        plain={{ ...gap, alert: { name: 'NotifyErrors', group: 'g', text: 'Pages may not reach on-call.', runbook_url: 'https://wiki.example.com/notify', line: null, line_alert: null } }}
        details="stored"
      />,
    );

    const shown = screen.getByTestId('plugin-plain');
    expect(shown).toHaveTextContent('Pages may not reach on-call.');
    expect(screen.getByTestId('plugin-plain-link')).toHaveAttribute('href', 'https://wiki.example.com/notify');
    expect(screen.getByTestId('plugin-plain-link')).toHaveAttribute('rel', 'noopener noreferrer');
  });
});
