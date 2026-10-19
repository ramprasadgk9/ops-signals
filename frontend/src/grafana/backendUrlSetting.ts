// Where the plugin finds the Ops Signals backend. A Grafana admin sets it once on the plugin's
// Configuration page (stored in the app's jsonData, or provisioned); the local-stack addresses stay
// in the picker so the development setups keep working without any configuration.

export type PluginJsonData = { backendUrl?: string } | undefined | null;

export type BackendOption = { label: string; value: string };

export const localBackendOptions: BackendOption[] = [
  { label: 'Grafana stack backend (:8002)', value: 'http://localhost:8002' },
  { label: 'Standalone app backend (:8001)', value: 'http://localhost:8001' },
  { label: 'Host backend from Docker (:8002)', value: 'http://host.docker.internal:8002' },
];

export function normalizeBackendUrl(value: string): string {
  return value.trim().replace(/\/+$/, '');
}

// Only http(s) URLs: the plugin calls the backend from the browser with fetch.
export function isValidBackendUrl(value: string): boolean {
  try {
    const url = new URL(normalizeBackendUrl(value));
    return url.protocol === 'http:' || url.protocol === 'https:';
  } catch {
    return false;
  }
}

export function configuredBackendUrl(jsonData: PluginJsonData): string | undefined {
  const value = normalizeBackendUrl(jsonData?.backendUrl ?? '');
  return value && isValidBackendUrl(value) ? value : undefined;
}

export function defaultBackendUrl(jsonData: PluginJsonData, buildDefault?: string): string {
  return configuredBackendUrl(jsonData) ?? buildDefault ?? localBackendOptions[0].value;
}

// The configured backend leads the picker; a URL that is neither configured nor local (the build
// default) is still listed so the select never shows a value it has no option for.
export function backendOptionsFor(jsonData: PluginJsonData, buildDefault?: string): BackendOption[] {
  const options = [...localBackendOptions];
  const extra = [buildDefault, configuredBackendUrl(jsonData)].filter((value): value is string => Boolean(value));
  for (const value of extra) {
    const index = options.findIndex((option) => option.value === value);
    if (index >= 0) options.splice(index, 1);
    const label = value === configuredBackendUrl(jsonData) ? `Configured backend (${value})` : `Build default (${value})`;
    options.unshift({ label, value });
  }
  return options;
}
