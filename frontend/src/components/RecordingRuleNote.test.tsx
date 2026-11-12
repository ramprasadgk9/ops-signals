import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { RecordingRuleNote } from './RecordingRuleNote';
import type { RecordingRule } from '../types';

const rule: RecordingRule = {
  name: 'service:error_rate:percent',
  query: '100 * avg by (service, env) (error_rate)',
  group: 'lab-rules',
  interval_seconds: 15,
  health: 'ok',
  source_metrics: ['error_rate'],
};

describe('RecordingRuleNote', () => {
  it('says which alerts use the rule, where they fire and what the team wrote', () => {
    render(
      <RecordingRuleNote
        rule={{
          ...rule,
          alerts: [{ name: 'SpikeLabErrorRateHigh', group: 'lab-alerts', fires: 'above 5', wait: '5 minutes', text: 'Orders fail at checkout.', runbook_url: 'https://wiki.example.com/r' }],
        }}
      />,
    );

    const [alert] = screen.getAllByTestId('recording-rule-alert');
    expect(alert).toHaveTextContent('Used by alert SpikeLabErrorRateHigh (fires above 5 for 5 minutes): Orders fail at checkout. Runbook');
    expect(screen.getByRole('link', { name: 'Runbook' })).toHaveAttribute('href', 'https://wiki.example.com/r');
  });

  it('adds nothing for a rule no alert uses', () => {
    render(<RecordingRuleNote rule={rule} />);
    expect(screen.queryByTestId('recording-rule-alert')).not.toBeInTheDocument();
  });
});
