import { expect } from 'vitest';
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
