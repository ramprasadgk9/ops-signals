import { afterEach, describe, expect, it, vi } from 'vitest';
import { getHealth } from './client';

function respond(status: number, body: string, contentType = 'application/json') {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(body, { status, headers: { 'Content-Type': contentType } })));
}

describe('getHealth', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('returns the status when everything is up', async () => {
    respond(200, JSON.stringify({ status: 'ok', database: 'ok' }));
    await expect(getHealth()).resolves.toEqual({ status: 'ok', database: 'ok' });
  });

  it('reads the 503 body: the backend is up, only the database is down', async () => {
    respond(503, JSON.stringify({ status: 'degraded', database: 'unavailable' }));
    await expect(getHealth()).resolves.toEqual({ status: 'degraded', database: 'unavailable' });
  });

  it('treats a proxy error page as the backend being unreachable', async () => {
    respond(502, '<html>Bad Gateway</html>', 'text/html');
    await expect(getHealth()).rejects.toThrow('Request failed: 502');
  });
});
