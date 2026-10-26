import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/queries';
import type { Me } from '../hooks/useWebPermissions';
import { callbackAddress, SignInSetupHelp } from './SignInSetupHelp';

vi.mock('../api/queries', () => ({ api: { me: vi.fn(), testSignIn: vi.fn() } }));

const ADA: Me = { signed_in: true, name: 'ada@example.com', role: 'Admin', via: 'oidc', groups: [], granted_by: 'ops-signals-admins', mode: 'oidc', problem: null, login_url: '/api/auth/login' };

function renderHelp(me: Me) {
  vi.mocked(api.me).mockResolvedValue(me);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><SignInSetupHelp /></QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('SignInSetupHelp', () => {
  it('shows the address to register and tests the provider before signing in', async () => {
    vi.mocked(api.testSignIn).mockResolvedValue({ reachable: true, issuer: 'https://idp.example.com', redirect_uri: 'x', detail: 'Ops Signals can reach your provider.', test_provider: false });
    renderHelp(ADA);
    expect(await screen.findByText(callbackAddress())).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Test sign-in' }));
    expect(await screen.findByText(/Ops Signals can reach your provider/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Sign in in a new tab' })).toHaveAttribute('href', '/api/auth/login?next=%2Fsetup-check');
  });

  it('says why the provider could not be reached', async () => {
    vi.mocked(api.testSignIn).mockResolvedValue({ reachable: false, issuer: null, redirect_uri: 'x', detail: 'Couldn\'t read https://idp.example.com/.well-known/openid-configuration', test_provider: false });
    renderHelp(ADA);
    fireEvent.click(await screen.findByRole('button', { name: 'Test sign-in' }));
    expect(await screen.findByText(/Test sign-in failed: Couldn't read/)).toBeInTheDocument();
  });

  it('offers only the set-up help while sign-in is off', async () => {
    renderHelp({ ...ADA, mode: 'none', via: 'none', role: null });
    expect(await screen.findByRole('button', { name: 'How to set up company sign-in' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Test sign-in' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'How to set up company sign-in' }));
    expect(screen.getByRole('dialog', { name: 'Set up company sign-in' })).toHaveTextContent('OPS_SIGNALS_AUTH_MODE=oidc');
    expect(screen.getByRole('dialog')).toHaveTextContent('OPS_SIGNALS_TEST_SIGN_IN=true');
  });
});
