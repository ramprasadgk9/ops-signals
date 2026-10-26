import { describe, expect, it } from 'vitest';
import type { FindingCustomSettings, FindingTrust } from '../types';
import { customSettings, customSettingsTooltip, settingLines, settingValue } from './customSettings';
import { testedCaption, testedHeadline } from './findingTrust';

const TUNED: FindingCustomSettings = {
  settings: [
    {
      analyzer_id: 'trend',
      analyzer: 'Trend Analysis',
      path: 'finding_rules.min_slope_percent',
      label: "Smallest steady climb or drop that counts, as % of the metric's usual level",
      value: 5,
      default: 10,
    },
  ],
  overrides: [{ id: 'payments_memory', file: 'payments-team.yml', reason: 'Memory grows slowly here.' }],
};

describe('customSettings', () => {
  it('is null for a finding on the default settings', () => {
    expect(customSettings({ custom_settings: null })).toBeNull();
    expect(customSettings({})).toBeNull();
    expect(customSettings({ custom_settings: { settings: [], overrides: [] } })).toBeNull();
    expect(customSettings({ custom_settings: TUNED })).toBe(TUNED);
  });

  it('says each setting with the value used and the default', () => {
    expect(settingLines(TUNED)).toEqual(["Trend Analysis: Smallest steady climb or drop that counts, as % of the metric's usual level: 5 (default 10)"]);
    expect(customSettingsTooltip(TUNED)).toBe(
      "Found with per-service settings from payments-team.yml. Trend Analysis: Smallest steady climb or drop that counts, as % of the metric's usual level: 5 (default 10). Open the finding for why."
    );
    expect([settingValue(null), settingValue(true), settingValue(0.56)]).toEqual(['—', 'on', '0.56']);
  });

  it("replaces the tested numbers' wording for a tuned finding", () => {
    const trust = { group: 'pattern', tested: null, custom_settings: true } as unknown as FindingTrust;
    expect(testedHeadline(trust)).toBe('Custom settings · not tested');
    expect(testedCaption(trust)).toContain('Tested on public data with the default settings');
  });
});
