// The analyzer settings analysis runs use (GET /api/analyzer-settings,
// backend/app/services/analyzer_settings.py), and what a Lab needs to turn its values into a snippet
// for the right file. Settings are named by their path in config/analyzers.yaml.

export type SettingSource = {
  layer: 'default' | 'site' | 'provider' | 'override';
  file: string;
  override_id?: string;
  reason?: string;
};

export type AnalyzerSetting = {
  path: string;
  value: unknown;
  default: unknown;
  changed: boolean;
  source: SettingSource;
  /** Whether the analyzer reads it: label = only shown in a finding's details; unused = read in
   * another mode only; unknown = not one of its settings (likely a typo). */
  use: SettingUse;
  use_note: string | null;
  meaning: string | null;
  label: string | null;
  per_service: boolean;
  min: number | null;
  max: number | null;
};

export type SettingUse = 'used' | 'label' | 'unused' | 'unknown';

export type RunStatus = 'every_metric' | 'router' | 'only_if_chosen' | 'turned_off' | 'cant_run';

export type AnalyzerInUse = {
  analyzer_id: string;
  display_name: string;
  description: string | null;
  enabled: boolean;
  run: { status: RunStatus; text: string; note?: string; source?: SettingSource };
  settings: AnalyzerSetting[];
  /** Says when settings look shared with another analyzer's but aren't. */
  settings_note: string | null;
  changed_count: number;
};

export type SettingsLayer = {
  key: 'default' | 'site' | 'provider' | 'override';
  title: string;
  file: string;
  exists?: boolean;
  changed?: number | null;
  analyzers?: number;
  files?: number;
  overrides?: number;
  applied?: string[];
  errors?: Array<{ file: string; message: string }>;
};

export type OverrideScope = { override_id: string; service: string | null; metric: string | null; file: string; reason: string };

export type AnalyzerSettingsResponse = {
  provider: 'prometheus' | 'otel';
  provider_label: string;
  service: string | null;
  metric: string | null;
  selection: {
    mode: string;
    min_score: number;
    max_analyzers: number;
    include_optional: boolean;
    selected_analyzers: string[];
    max_analyzers_source: SettingSource | null;
  };
  layers: SettingsLayer[];
  scopes: OverrideScope[];
  analyzers: AnalyzerInUse[];
};

export const RUN_STATUS: Record<RunStatus, { label: string; tone: 'green' | 'blue' | 'amber' | 'red' | 'grey' }> = {
  every_metric: { label: 'Every metric', tone: 'green' },
  router: { label: 'When it suits the metric', tone: 'blue' },
  only_if_chosen: { label: 'Only if you choose it', tone: 'amber' },
  turned_off: { label: 'Turned off', tone: 'grey' },
  cant_run: { label: "Can't run", tone: 'red' },
};

export const OVERRIDES_DOC_URL = 'https://github.com/ramprasadgk9/ops-signals/blob/main/docs/configuration.md#per-service-analyzer-settings';

/** How a run picks analyzers, in one sentence. */
export function selectionSentence(selection: AnalyzerSettingsResponse['selection']): string {
  const mode = selection.mode.toLowerCase();
  const always = 'Analyzers marked "Every metric" run on every metric.';
  if (mode === 'all') return 'Every analyzer that is turned on runs on every metric.';
  if (mode === 'manual_override') {
    const chosen = selection.selected_analyzers.length ? selection.selected_analyzers.join(', ') : 'none yet';
    return `The router's picks for each metric run, plus the analyzers chosen in selected_analyzers (${chosen}). ${always}`;
  }
  if (mode === 'recommended_only') return `For each metric, every analyzer the router recommends runs. ${always}`;
  return `For each metric, the router scores every analyzer that's turned on and runs up to ${selection.max_analyzers} that score ${selection.min_score.toFixed(2)} or more. ${always}`;
}

/** The order the Settings in use table groups analyzers in: most-used first. */
export const RUN_ORDER: RunStatus[] = ['every_metric', 'router', 'only_if_chosen', 'cant_run', 'turned_off'];

function names(analyzers: AnalyzerInUse[]): string {
  const list = analyzers.map((analyzer) => analyzer.display_name);
  return list.length < 2 ? list.join('') : `${list.slice(0, -1).join(', ')} and ${list[list.length - 1]}`;
}

function count(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** The page's answer in three sentences: what's customized, what runs, and any key nothing reads. */
export function atAGlance(data: AnalyzerSettingsResponse): { customized: string; runs: string; problems: string | null } {
  const [, site, provider, override] = data.layers;
  const scoped = Boolean(data.service || data.metric);
  const teams = scoped ? override?.applied?.length ?? 0 : override?.overrides ?? 0;
  const parts = [
    site?.changed ? `${count(site.changed, 'value')} in ${site.file}` : '',
    provider?.changed ? `${count(provider.changed, 'value')} in ${provider.file}` : '',
    teams ? (scoped ? `${count(teams, "team's override")} for ${[data.service, data.metric].filter(Boolean).join(' · ')}` : `${count(teams, "team's override")} for chosen services`) : '',
  ].filter(Boolean);
  const customized = parts.length
    ? `Changed from the built-in defaults: ${parts.join(', ')}.`
    : 'Nothing is customized: every analyzer uses its built-in defaults.';

  const by = (status: RunStatus) => data.analyzers.filter((analyzer) => analyzer.run.status === status);
  const runs = [
    by('every_metric').length ? `${names(by('every_metric'))} ${by('every_metric').length === 1 ? 'runs' : 'run'} on every metric.` : '',
    by('router').length ? `The router adds the ones that suit each metric from ${names(by('router'))}.` : '',
    by('only_if_chosen').length ? `${names(by('only_if_chosen'))} ${by('only_if_chosen').length === 1 ? 'runs only if you choose it' : 'run only if you choose them'}.` : '',
    by('cant_run').length ? `${names(by('cant_run'))} can't run.` : '',
    by('turned_off').length ? `${names(by('turned_off'))} ${by('turned_off').length === 1 ? 'is' : 'are'} turned off.` : '',
  ].filter(Boolean).join(' ');

  const unknown = data.analyzers.flatMap((analyzer) => analyzer.settings.filter((setting) => setting.use === 'unknown').map((setting) => `${analyzer.analyzer_id}: ${setting.path}`));
  const problems = unknown.length ? `${count(unknown.length, 'setting')} in your files ${unknown.length === 1 ? "isn't" : "aren't"} read by any analyzer, probably a typo: ${unknown.join(', ')}.` : null;
  return { customized, runs, problems };
}

export function sourceText(source: SettingSource): string {
  if (source.layer === 'default') return 'Built-in default';
  if (source.layer === 'override') return `${source.file.replace('config/analyzer_overrides.d/', '')} → ${source.override_id}`;
  return source.file;
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

/** Leaves of a nested settings block, by dotted path. */
export function leaves(value: Record<string, unknown>, prefix = ''): Array<[string, unknown]> {
  return Object.entries(value).flatMap(([key, child]) =>
    child && typeof child === 'object' && !Array.isArray(child)
      ? leaves(child as Record<string, unknown>, `${prefix}${key}.`)
      : [[`${prefix}${key}`, child] as [string, unknown]],
  );
}

function sameValue(a: unknown, b: unknown): boolean {
  if (typeof a === 'number' || typeof b === 'number') return Number(a) === Number(b);
  return formatValue(a) === formatValue(b);
}

export function settingAt(analyzer: AnalyzerInUse | undefined, path: string): AnalyzerSetting | undefined {
  return analyzer?.settings.find((setting) => setting.path === path);
}

export type LabChange = { path: string; from: unknown; to: unknown; setting?: AnalyzerSetting };

/** The Lab values that differ from what runs use now. `values` is in config/analyzers.yaml's shape
 * for this analyzer, e.g. { implementation: {...}, finding_rules: {...} }. */
export function labChanges(analyzer: AnalyzerInUse | undefined, values: Record<string, unknown>): LabChange[] {
  if (!analyzer) return [];
  return leaves(values)
    .map(([path, value]) => ({ path, to: value, setting: settingAt(analyzer, path) }))
    .filter(({ to, setting }) => !setting || !sameValue(to, setting.value))
    .map(({ path, to, setting }) => ({ path, from: setting?.value, to, setting }));
}

function nest(changes: LabChange[]): Record<string, unknown> {
  const root: Record<string, unknown> = {};
  for (const change of changes) {
    const parts = change.path.split('.');
    let node = root;
    for (const part of parts.slice(0, -1)) node = (node[part] ??= {}) as Record<string, unknown>;
    node[parts[parts.length - 1]] = change.to;
  }
  return root;
}

function scalar(value: unknown): string {
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  const text = String(value ?? '');
  return /^[a-zA-Z0-9_./-]+$/.test(text) && !/^[*&!]/.test(text) ? text : JSON.stringify(text);
}

export function toYaml(value: Record<string, unknown>, indent = 0): string {
  return Object.entries(value)
    .map(([key, child]) =>
      child && typeof child === 'object' && !Array.isArray(child)
        ? `${' '.repeat(indent)}${key}:\n${toYaml(child as Record<string, unknown>, indent + 2)}`
        : `${' '.repeat(indent)}${key}: ${scalar(child)}\n`,
    )
    .join('');
}

/** The block for config/analyzers.yaml: only the changed keys, nested where the file reads them. */
export function siteSnippet(analyzerId: string, changes: LabChange[]): string {
  return toYaml({ analysis: { analyzers: { [analyzerId]: nest(changes) } } });
}

export function overrideId(analyzerId: string, service: string, metric: string): string {
  const name = [service, metric].filter(Boolean).join('_') || 'my_service';
  return `${name}_${analyzerId}`.replace(/[^a-zA-Z0-9]+/g, '_').replace(/^_+|_+$/g, '').toLowerCase();
}

/** A per-service override file (config/analyzer_overrides.d/) with the changed keys. */
export function overrideSnippet(analyzerId: string, changes: LabChange[], service: string, metric: string, reason: string): string {
  const scope: Record<string, unknown> = {};
  if (service) scope.service = service;
  if (metric) scope.metric = metric;
  return toYaml({
    overrides: {
      [overrideId(analyzerId, service, metric)]: {
        scope: Object.keys(scope).length ? scope : { service: 'my-service' },
        reason: reason.trim() || 'Why these services need different settings (shown on their findings)',
        analyzers: { [analyzerId]: nest(changes) },
      },
    },
  });
}

export function overrideFileName(service: string, metric: string): string {
  const base = (service || metric || 'my-team').replace(/[^a-zA-Z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').toLowerCase();
  return `${base || 'my-team'}.yml`;
}

/** Why a change can't go in a team's override file: only `tunable` settings, within their range. */
export function perServiceProblems(changes: LabChange[]): string[] {
  return changes.flatMap((change) => {
    const setting = change.setting;
    if (!setting?.per_service) return [`${change.path} can only be changed for every service`];
    const value = Number(change.to);
    if ((setting.min !== null && value < setting.min) || (setting.max !== null && value > setting.max)) {
      return [`${change.path} must be between ${setting.min} and ${setting.max} in a team's file`];
    }
    return [];
  });
}
