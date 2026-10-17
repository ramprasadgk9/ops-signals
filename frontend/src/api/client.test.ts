import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, getHealth, getJson, retryUnlessClientError } from './client';

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

describe('retryUnlessClientError (QA-19)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('does not retry a 404 or other 4xx', async () => {
    respond(404, JSON.stringify({ detail: 'case not found' }));
    const error = await getJson('/api/cases/99999').catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(404);
    expect((error as ApiError).message).toBe('case not found');
    expect(retryUnlessClientError(0, error)).toBe(false);
    expect(retryUnlessClientError(0, new ApiError(422, 'invalid'))).toBe(false);
  });

  it('still retries server errors and network failures up to 3 times', () => {
    expect(retryUnlessClientError(0, new ApiError(503, 'down'))).toBe(true);
    expect(retryUnlessClientError(2, new TypeError('Failed to fetch'))).toBe(true);
    expect(retryUnlessClientError(3, new ApiError(500, 'boom'))).toBe(false);
  });
});
