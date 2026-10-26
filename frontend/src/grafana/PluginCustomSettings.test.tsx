import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PluginCustomSettings, PluginCustomSettingsChip } from './PluginCustomSettings';

const tuned = {
  custom_settings: {
    settings: [{ analyzer_id: 'trend', analyzer: 'Trend Analysis', path: 'finding_rules.min_slope_percent', label: 'Smallest steady climb or drop that counts', value: 5, default: 10 }],
    overrides: [{ id: 'payments_memory', file: 'payments-team.yml', reason: 'Memory grows slowly here.' }],
  },
};

describe('PluginCustomSettings', () => {
  it('shows the chip and the settings a team set, with the default and why', () => {
    render(<><PluginCustomSettingsChip finding={tuned} /><PluginCustomSettings finding={tuned} /></>);

    expect(screen.getByTestId('plugin-custom-settings-chip')).toHaveTextContent('Custom settings · not tested');
    const box = screen.getByTestId('plugin-custom-settings');
    expect(box).toHaveTextContent('Found with custom settings · payments-team.yml');
    expect(box).toHaveTextContent('Trend Analysis: Smallest steady climb or drop that counts: 5 (default 10)');
    expect(box).toHaveTextContent('Why: Memory grows slowly here. · override payments_memory in payments-team.yml');
  });

  it('renders nothing for a finding on the default settings', () => {
    const { container } = render(<><PluginCustomSettingsChip finding={{ custom_settings: null }} /><PluginCustomSettings finding={{}} /></>);
    expect(container).toBeEmptyDOMElement();
  });
});
