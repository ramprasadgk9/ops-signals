import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, getJson, postJson, SIGNED_OUT_EVENT } from './client';

afterEach(() => vi.unstubAllGlobals());

describe('a 401 from the API', () => {
  it('says the sign-in ended, so the page can offer to sign in again', async () => {
    const heard = vi.fn();
    window.addEventListener(SIGNED_OUT_EVENT, heard);
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'missing or invalid bearer token' }), { status: 401 })));
    await expect(getJson('/api/findings')).rejects.toBeInstanceOf(ApiError);
    await expect(postJson('/api/cases/findings/1/create', {})).rejects.toThrow('missing or invalid bearer token');
    expect(heard).toHaveBeenCalledTimes(2);
    window.removeEventListener(SIGNED_OUT_EVENT, heard);
  });

  it('is not fired for other failures', async () => {
    const heard = vi.fn();
    window.addEventListener(SIGNED_OUT_EVENT, heard);
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 403 })));
    await expect(getJson('/api/setup/check')).rejects.toBeInstanceOf(ApiError);
    expect(heard).not.toHaveBeenCalled();
    window.removeEventListener(SIGNED_OUT_EVENT, heard);
  });
});
