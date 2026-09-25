import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { deleteAutonomousPolicy, listServices, resetTestingOperationalData, setApiToken } from './backendClient';

function mockFetch() {
  const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => new Response('[]', { status: 200, headers: { 'content-type': 'application/json' } }));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function sentHeaders(fetchMock: ReturnType<typeof mockFetch>) {
  const init = fetchMock.mock.calls[0][1] as RequestInit | undefined;
  return (init?.headers ?? {}) as Record<string, string>;
}

// Node 25's own (file-less, non-functional) localStorage shadows jsdom's, so use a plain in-memory one.
function memoryStorage(): Storage {
  const items = new Map<string, string>();
  return {
    get length() {
      return items.size;
    },
    clear: () => items.clear(),
    getItem: (key) => items.get(key) ?? null,
    key: (index) => [...items.keys()][index] ?? null,
    removeItem: (key) => void items.delete(key),
    setItem: (key, value) => void items.set(key, String(value)),
  };
}

describe('backendClient API token', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', memoryStorage());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('sends no Authorization header without a token', async () => {
    const fetchMock = mockFetch();
    await listServices('http://backend');
    expect(sentHeaders(fetchMock).Authorization).toBeUndefined();
  });

  it('adds the saved token to reads, writes and deletes', async () => {
    setApiToken('  s3cret  ');
    for (const call of [
      () => listServices('http://backend'),
      () => resetTestingOperationalData('http://backend'),
      () => deleteAutonomousPolicy('http://backend', 'p1'),
    ]) {
      const fetchMock = mockFetch();
      await call();
      expect(sentHeaders(fetchMock).Authorization).toBe('Bearer s3cret');
    }
  });
});
