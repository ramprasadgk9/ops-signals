import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { deleteAutonomousPolicy, getSetupSummary, listAnalysisRuns, listServices, resetTestingOperationalData, setApiToken } from './backendClient';

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

describe('listAnalysisRuns', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('asks for the newest runs only, never the full list', async () => {
    const fetchMock = mockFetch();
    await listAnalysisRuns('http://backend');
    expect(fetchMock.mock.calls[0][0]).toBe('http://backend/api/analysis-runs?limit=25');
  });

  it('passes the service and metric filters', async () => {
    const fetchMock = mockFetch();
    await listAnalysisRuns('http://backend', { limit: 1, service: 'checkout', metric: 'cpu_usage' });
    expect(fetchMock.mock.calls[0][0]).toBe('http://backend/api/analysis-runs?limit=1&service=checkout&metric_name=cpu_usage');
  });
});

describe('getSetupSummary', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

  it('reads the summary every role may see', async () => {
    const fetchMock = vi.fn(async (_url: string) => json({ version: 'v', checks: [] }));
    vi.stubGlobal('fetch', fetchMock);
    await getSetupSummary('http://localhost:8002');
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual(['http://localhost:8002/api/setup/summary']);
  });

  it('falls back to the full check on a backend from before the summary', async () => {
    const fetchMock = vi.fn(async (url: string) => (url.endsWith('/summary') ? json({ detail: 'Not Found' }, 404) : json({ version: 'old', checks: [] })));
    vi.stubGlobal('fetch', fetchMock);
    expect((await getSetupSummary('http://localhost:8002')).version).toBe('old');
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual(['http://localhost:8002/api/setup/summary', 'http://localhost:8002/api/setup/check']);
  });

  it('passes on any other failure, such as a refusal', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ detail: 'Only Grafana admins can see this.' }, 403)));
    await expect(getSetupSummary('http://localhost:8002')).rejects.toThrow('Request failed: 403');
  });
});
