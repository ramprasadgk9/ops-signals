import { useSyncExternalStore } from 'react';

/** Features a viewer hid from the "More with Prometheus / Grafana" menu group. Per browser only:
 * a convenience, so a failed read or write just means nothing is hidden. */
export const HIDDEN_NAV_FEATURES_KEY = 'ops-signals-hidden-nav-features';

const listeners = new Set<() => void>();
let cache: { raw: string | null; value: string[] } = { raw: null, value: [] };

function read(): string[] {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(HIDDEN_NAV_FEATURES_KEY);
  } catch {
    return cache.value;
  }
  if (raw === cache.raw) return cache.value;
  let value: string[] = [];
  try {
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    value = Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : [];
  } catch {
    value = [];
  }
  cache = { raw, value };
  return value;
}

function write(value: string[]) {
  try {
    if (value.length) window.localStorage.setItem(HIDDEN_NAV_FEATURES_KEY, JSON.stringify(value));
    else window.localStorage.removeItem(HIDDEN_NAV_FEATURES_KEY);
  } catch {
    // Storage blocked: keep the choice for this page view only.
    cache = { raw: cache.raw, value };
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function setNavFeatureHidden(featureId: string, hidden: boolean) {
  const current = read();
  if (hidden === current.includes(featureId)) return;
  write(hidden ? [...current, featureId] : current.filter((id) => id !== featureId));
}

export function showAllNavFeatures() {
  write([]);
}

export function useHiddenNavFeatures(): string[] {
  return useSyncExternalStore(subscribe, read, () => []);
}
