import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PluginPlainBadge, PluginPlainFinding } from './PluginPlainFinding';
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
});
