import { expect, vi } from 'vitest';
import * as matchers from '@testing-library/jest-dom/matchers';

expect.extend(matchers);

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver = ResizeObserverMock;

// jsdom has no layout, so its window.scrollTo only logs "Not implemented". Pages that open at the
// top call it on mount; tests that care spy on it.
window.scrollTo = (() => {}) as typeof window.scrollTo;

// @grafana/runtime only loads inside Grafana (its UI package pulls in CSS). Plugin code that keeps
// state in the page URL through locationService gets a stand-in backed by jsdom's URL; tests that
// need more of the package mock it themselves.
vi.mock('@grafana/runtime', () => ({
  locationService: {
    getSearchObject: () => Object.fromEntries(new URLSearchParams(window.location.search)),
    partial: (query: Record<string, string | null | undefined>, replace?: boolean) => {
      const params = new URLSearchParams(window.location.search);
      for (const [key, value] of Object.entries(query)) {
        if (value === null || value === undefined) params.delete(key);
        else params.set(key, value);
      }
      const search = params.toString();
      window.history[replace ? 'replaceState' : 'pushState'](null, '', `${window.location.pathname}${search ? `?${search}` : ''}`);
    },
  },
  getBackendSrv: vi.fn(),
  getDataSourceSrv: vi.fn(),
}));
