const API_BASE = import.meta.env.VITE_API_BASE ?? '';

async function errorMessage(res: Response) {
  const fallback = `Request failed: ${res.status}`;
  const text = await res.text();
  if (!text) return fallback;
  try {
    const parsed = JSON.parse(text) as { detail?: unknown };
    if (typeof parsed.detail === 'string') return parsed.detail;
    if (parsed.detail) return JSON.stringify(parsed.detail);
  } catch {
    return text;
  }
  return text;
}

/** A failed API call, with its HTTP status so callers can tell "not found" from "server down". */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/** A 4xx answer: asking again gets the same answer, so it isn't worth retrying. */
export function isClientError(error: unknown): boolean {
  return error instanceof ApiError && error.status >= 400 && error.status < 500;
}

/** The web UI's query retry rule: up to 3 retries, none for a 4xx. Retrying a 404 three times kept
 * a missing case's page on a loading skeleton for about 7 seconds before it said anything. */
export function retryUnlessClientError(failureCount: number, error: unknown): boolean {
  return !isClientError(error) && failureCount < 3;
}

/** Fired on a 401. With the backend's own sign-in it means the session has ended, and the web UI offers
 * to sign in again without losing the page (components/SignIn.tsx). */
export const SIGNED_OUT_EVENT = 'ops-signals:signed-out';

async function apiError(res: Response): Promise<ApiError> {
  if (res.status === 401 && typeof window !== 'undefined') window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
  return new ApiError(res.status, await errorMessage(res));
}

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    throw await apiError(res);
  }
  return res.json() as Promise<T>;
}

export type HealthStatus = { status: string; database?: string };

/** /api/health answers 503 when the database is unreachable, with a body that still says the
 * backend itself is up; read it instead of treating the whole backend as down. */
export async function getHealth(): Promise<HealthStatus> {
  const res = await fetch(`${API_BASE}/api/health`);
  if (res.ok || res.status === 503) {
    try {
      return (await res.json()) as HealthStatus;
    } catch {
      // Not our JSON: a proxy's error page; fall through to the error below.
    }
  }
  throw new ApiError(res.status, `Request failed: ${res.status}`);
}

export async function postJson<TRequest, TResponse>(path: string, body: TRequest): Promise<TResponse> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw await apiError(res);
  }
  return res.json() as Promise<TResponse>;
}

export async function patchJson<TRequest, TResponse>(path: string, body: TRequest): Promise<TResponse> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw await apiError(res);
  }
  return res.json() as Promise<TResponse>;
}

export async function putJson<TRequest, TResponse>(path: string, body: TRequest): Promise<TResponse> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw await apiError(res);
  }
  return res.json() as Promise<TResponse>;
}

export async function deleteJson<TResponse>(path: string): Promise<TResponse> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    throw await apiError(res);
  }
  return res.json() as Promise<TResponse>;
}

export async function postForm<TResponse>(path: string, body: FormData): Promise<TResponse> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    body,
  });
  if (!res.ok) {
    throw await apiError(res);
  }
  return res.json() as Promise<TResponse>;
}
