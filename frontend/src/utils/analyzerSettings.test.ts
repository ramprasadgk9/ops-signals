import { describe, expect, it } from 'vitest';
import {
  labChanges,
  overrideFileName,
  overrideSnippet,
  perServiceProblems,
  selectionSentence,
  siteSnippet,
  sourceText,
  type AnalyzerInUse,
  type AnalyzerSetting,
} from './analyzerSettings';

function setting(path: string, value: unknown, extra: Partial<AnalyzerSetting> = {}): AnalyzerSetting {
  return { path, value, default: value, changed: false, source: { layer: 'default', file: 'config/analyzer_registry.d/builtin.yml' }, use: 'used', use_note: null, meaning: null, label: null, per_service: false, min: null, max: null, ...extra };
}

const TREND: AnalyzerInUse = {
  analyzer_id: 'trend',
  display_name: 'Trend Analysis',
  description: null,
  enabled: true,
  run: { status: 'router', text: 'The router picks it for a metric it suits.' },
  changed_count: 0,
  settings_note: null,
  settings: [
    setting('implementation.library', 'statsmodels'),
    setting('implementation.model', 'OLS'),
    setting('finding_rules.min_slope_percent', 10, { per_service: true, min: 1, max: 100 }),
  ],
};

describe('labChanges', () => {
  it('keeps only the Lab values that differ from what runs use', () => {
    const changes = labChanges(TREND, { implementation: { library: 'statsmodels', model: 'OLS' }, finding_rules: { min_slope_percent: 5 } });
    expect(changes.map(({ path, from, to }) => ({ path, from, to }))).toEqual([{ path: 'finding_rules.min_slope_percent', from: 10, to: 5 }]);
  });

  it('treats 3 and 3.0 as the same value and finds nothing before the settings load', () => {
    expect(labChanges(TREND, { finding_rules: { min_slope_percent: 10.0 } })).toEqual([]);
    expect(labChanges(undefined, { finding_rules: { min_slope_percent: 5 } })).toEqual([]);
  });
});

describe('snippets', () => {
  const changes = labChanges(TREND, { finding_rules: { min_slope_percent: 5 } });

  it('nests a site-wide change under analysis → analyzers, where config/analyzers.yaml reads it', () => {
    expect(siteSnippet('trend', changes)).toBe('analysis:\n  analyzers:\n    trend:\n      finding_rules:\n        min_slope_percent: 5\n');
  });

  it("writes a team's override with scope, reason and only the changed key", () => {
    expect(overrideSnippet('trend', changes, 'payments-api', '', 'Memory grows slowly')).toBe(
      'overrides:\n  payments_api_trend:\n    scope:\n      service: payments-api\n    reason: "Memory grows slowly"\n    analyzers:\n      trend:\n        finding_rules:\n          min_slope_percent: 5\n',
    );
    expect(overrideSnippet('trend', changes, 'payments-api', 'process_resident_memory_bytes', '')).toContain('metric: process_resident_memory_bytes');
    expect(overrideSnippet('trend', changes, '', '', '')).toContain('service: my-service');
  });

  it('quotes a wildcard name that YAML would read as an alias', () => {
    expect(overrideSnippet('trend', changes, '*-api', '', 'x')).toContain('service: "*-api"');
  });

  it('names the override file after the service', () => {
    expect(overrideFileName('payments-api', '')).toBe('payments-api.yml');
    expect(overrideFileName('', '')).toBe('my-team.yml');
  });
});

describe('perServiceProblems', () => {
  it("allows only settings a team's file may change, within their range", () => {
    expect(perServiceProblems(labChanges(TREND, { finding_rules: { min_slope_percent: 5 } }))).toEqual([]);
    expect(perServiceProblems(labChanges(TREND, { finding_rules: { min_slope_percent: 500 } }))[0]).toContain('between 1 and 100');
    expect(perServiceProblems(labChanges(TREND, { implementation: { model: 'RLM' } }))[0]).toContain('only be changed for every service');
  });
});

describe('words', () => {
  it('says how a run picks analyzers for each selection mode', () => {
    const base = { min_score: 0.8, max_analyzers: 3, include_optional: false, selected_analyzers: [], max_analyzers_source: null };
    expect(selectionSentence({ ...base, mode: 'recommended_threshold' })).toContain('runs up to 3 that score 0.80 or more');
    expect(selectionSentence({ ...base, mode: 'all' })).toBe('Every analyzer that is turned on runs on every metric.');
    expect(selectionSentence({ ...base, mode: 'manual_override', selected_analyzers: ['anomaly_zscore'] })).toContain('(anomaly_zscore)');
  });

  it('names where a value comes from', () => {
    expect(sourceText({ layer: 'default', file: 'x' })).toBe('Built-in default');
    expect(sourceText({ layer: 'site', file: 'config/analyzers.yaml' })).toBe('config/analyzers.yaml');
    expect(sourceText({ layer: 'override', file: 'config/analyzer_overrides.d/payments-team.yml', override_id: 'payments_memory' })).toBe('payments-team.yml → payments_memory');
  });
});
