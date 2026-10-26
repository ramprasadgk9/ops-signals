import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/queries';
import { SIGNED_OUT_EVENT } from '../api/client';
import type { Me } from '../hooks/useWebPermissions';
import { SignInGate } from './SignIn';
import { timeLeft, UserChip } from './UserChip';

vi.mock('../api/queries', () => ({ api: { me: vi.fn(), signOut: vi.fn() } }));

const SIGNED_OUT: Me = {
  signed_in: false, name: null, role: null, via: 'none', groups: [], granted_by: null, mode: 'oidc', problem: null,
  login_url: '/api/auth/login', provider_name: 'test accounts', auto_redirect: false,
};
const SAM: Me = { ...SIGNED_OUT, signed_in: true, name: 'sam@example.com', role: 'Viewer', via: 'oidc', session_ends_at: new Date(Date.now() + 2 * 3600_000).toISOString() };

function renderAt(me: Me, path: string) {
  vi.mocked(api.me).mockResolvedValue(me);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <SignInGate><p>the app</p><UserChip /></SignInGate>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const realLocation = window.location;
beforeEach(() => {
  Object.defineProperty(window, 'location', { configurable: true, value: { ...realLocation, assign: vi.fn() } });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
  Object.defineProperty(window, 'location', { configurable: true, value: realLocation });
});

describe('SignInGate', () => {
  it('leaves the app alone without the backend own sign-in', async () => {
    renderAt({ ...SIGNED_OUT, mode: 'none', login_url: null }, '/findings');
    expect(await screen.findByText('the app')).toBeInTheDocument();
  });

  it('asks someone not signed in to sign in, and to come back to the page they opened', async () => {
    renderAt(SIGNED_OUT, '/cases/4?tab=notes');
    const button = await screen.findByRole('link', { name: 'Sign in with test accounts' });
    expect(button).toHaveAttribute('href', '/api/auth/login?next=%2Fcases%2F4%3Ftab%3Dnotes');
    expect(screen.queryByText('the app')).not.toBeInTheDocument();
  });

  it('goes straight to the provider with auto-redirect on', async () => {
    renderAt({ ...SIGNED_OUT, auto_redirect: true }, '/findings');
    await vi.waitFor(() => expect(window.location.assign).toHaveBeenCalledWith('/api/auth/login?next=%2Ffindings'));
  });

  it('says why a sign-in failed', async () => {
    renderAt(SIGNED_OUT, '/sign-in?error=not_allowed&id=7f3a91c2&as=sam%40example.com');
    expect(await screen.findByText("You can't use Ops Signals yet")).toBeInTheDocument();
    expect(screen.getByText(/You signed in as sam@example.com, but you aren't in a group/)).toBeInTheDocument();
    expect(screen.getByText('Error id 7f3a91c2')).toBeInTheDocument();
    cleanup();

    renderAt(SIGNED_OUT, '/sign-in?error=provider&id=41b0d7e3&said=Not%20assigned');
    expect(await screen.findByText(/It said: "Not assigned"/)).toBeInTheDocument();
    cleanup();

    renderAt(SIGNED_OUT, '/sign-in?error=expired');
    expect(await screen.findByText('That sign-in took too long')).toBeInTheDocument();
  });

  it('lets someone whose groups went missing carry on as a Viewer', async () => {
    renderAt(SAM, '/sign-in?error=groups&next=%2Fcases');
    expect(await screen.findByText("Signed in, but your groups didn't come through")).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Continue as Viewer' })).toHaveAttribute('href', '/cases');
  });

  it('says what is missing when sign-in is on but not set up', async () => {
    renderAt({ ...SIGNED_OUT, login_url: null, problem: 'Company sign-in needs OPS_SIGNALS_API_TOKEN too.' }, '/');
    expect(await screen.findByText("Sign-in isn't set up yet")).toBeInTheDocument();
    expect(screen.getByText('Company sign-in needs OPS_SIGNALS_API_TOKEN too.')).toBeInTheDocument();
  });

  it('shows the signed-out page', async () => {
    renderAt(SIGNED_OUT, '/signed-out');
    expect(await screen.findByText("You're signed out of Ops Signals.")).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Sign in again' })).toHaveAttribute('href', '/api/auth/login?next=%2F');
  });

  it('when a session ends mid-work, signs in again in a new tab and keeps the page', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const open = vi.spyOn(window, 'open').mockReturnValue(null);
    renderAt(SAM, '/cases/4');
    expect(await screen.findByText('the app')).toBeInTheDocument();

    act(() => {
      window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
    });
    expect(await screen.findByText('Your sign-in has ended')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Sign in again' }));
    expect(open).toHaveBeenCalledWith('/api/auth/login?next=%2Fsign-in%2Fdone', '_blank', 'noopener');
    expect(screen.getByText('the app')).toBeInTheDocument();

    vi.mocked(api.me).mockResolvedValue(SAM);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100);
    });
    await vi.waitFor(() => expect(screen.queryByText('Your sign-in has ended')).not.toBeInTheDocument());
  });
});

describe('UserChip with the backend own sign-in', () => {
  it('says when the session ends, and signs out', async () => {
    vi.mocked(api.signOut).mockResolvedValue({ redirect: '/signed-out' });
    renderAt(SAM, '/');
    fireEvent.click(await screen.findByRole('button', { name: 'Signed in as sam@example.com, Viewer' }));
    expect(screen.getByText('your company account')).toBeInTheDocument();
    expect(screen.getByText('Session ends in')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
    await vi.waitFor(() => expect(window.location.assign).toHaveBeenCalledWith('/signed-out'));
  });

  it('counts down in hours and minutes', () => {
    const now = Date.parse('2026-10-26T10:00:00Z');
    expect(timeLeft('2026-10-26T17:12:00Z', now)).toBe('7 h 12 min');
    expect(timeLeft('2026-10-26T10:40:00Z', now)).toBe('40 min');
    expect(timeLeft(null, now)).toBeNull();
  });
});
