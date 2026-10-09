import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { COLOR_MODE_KEY, ThemeProviderWithMode, initialMode, useColorMode } from './ThemeProviderWithMode';

function Probe() {
  const { mode, toggle } = useColorMode();
  return <button onClick={toggle}>mode: {mode}</button>;
}

function memoryStorage(): Storage {
  const items = new Map<string, string>();
  return {
    get length() { return items.size; },
    clear: () => items.clear(),
    getItem: (key: string) => items.get(key) ?? null,
    key: (index: number) => [...items.keys()][index] ?? null,
    removeItem: (key: string) => { items.delete(key); },
    setItem: (key: string, value: string) => { items.set(key, value); },
  };
}

function blockedStorage(): Storage {
  const blocked = () => { throw new Error('blocked'); };
  return { length: 0, clear: blocked, getItem: blocked, key: blocked, removeItem: blocked, setItem: blocked };
}

function systemPrefersDark(dark: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: dark && query.includes('dark'), media: query, addEventListener() {}, removeEventListener() {} }));
}

describe('color mode', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', memoryStorage());
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('follows the system setting until the user chooses', () => {
    systemPrefersDark(true);
    expect(initialMode()).toBe('dark');
    systemPrefersDark(false);
    expect(initialMode()).toBe('light');
  });

  it('remembers the choice across reloads, ahead of the system setting', () => {
    systemPrefersDark(false);
    const { unmount } = render(<ThemeProviderWithMode><Probe /></ThemeProviderWithMode>);
    fireEvent.click(screen.getByRole('button', { name: 'mode: light' }));

    expect(screen.getByRole('button', { name: 'mode: dark' })).toBeInTheDocument();
    expect(window.localStorage.getItem(COLOR_MODE_KEY)).toBe('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(getComputedStyle(document.documentElement).getPropertyValue('--os-surface').trim()).toBe('#111827');

    unmount();
    render(<ThemeProviderWithMode><Probe /></ThemeProviderWithMode>);
    expect(screen.getByRole('button', { name: 'mode: dark' })).toBeInTheDocument();
  });

  it('still works when storage is unavailable', () => {
    systemPrefersDark(false);
    vi.stubGlobal('localStorage', blockedStorage());

    render(<ThemeProviderWithMode><Probe /></ThemeProviderWithMode>);
    fireEvent.click(screen.getByRole('button', { name: 'mode: light' }));
    expect(screen.getByRole('button', { name: 'mode: dark' })).toBeInTheDocument();
  });
});
