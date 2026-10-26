import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/queries';
import { allows, effectiveRole, WEB_LOCK_REASONS, type Me } from '../hooks/useWebPermissions';
import type { Finding } from '../types';
import { FindingTrustPanel } from './FindingTrustPanel';
import { UserChip } from './UserChip';

vi.mock('../api/queries', () => ({ api: { me: vi.fn(), findingFeedback: vi.fn() } }));

const NOBODY: Me = { signed_in: false, name: null, role: null, via: 'none', groups: [], granted_by: null, mode: 'none', problem: null };
const PRIYA: Me = { signed_in: true, name: 'priya@example.com', role: 'Editor', via: 'proxy', groups: ['payments', 'sre'], granted_by: 'sre', mode: 'proxy-headers', problem: null };
const VIC: Me = { ...PRIYA, name: 'vic@example.com', role: 'Viewer', granted_by: null, groups: ['payments'] };

function renderWith(me: Me, node: ReactNode) {
  vi.mocked(api.me).mockResolvedValue(me);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

afterEach(() => vi.clearAllMocks());

describe('web roles', () => {
  it('applies a role only to someone signed in, and limits nothing otherwise', () => {
    expect(effectiveRole(NOBODY)).toBeNull();
    expect(effectiveRole(undefined)).toBeNull();
    expect(effectiveRole(VIC)).toBe('Viewer');
    expect([allows(null, 'Admin'), allows('Viewer', 'Editor'), allows('Editor', 'Editor'), allows('Editor', 'Admin')]).toEqual([true, false, true, false]);
  });
});

describe('UserChip', () => {
  it('says who is signed in, and why they have their role', async () => {
    renderWith(PRIYA, <UserChip />);
    fireEvent.click(await screen.findByRole('button', { name: 'Signed in as priya@example.com, Editor' }));
    expect(screen.getByText('priya · Editor')).toBeInTheDocument();
    expect(screen.getByText('sre')).toBeInTheDocument();
    expect(screen.getByText('company sign-in')).toBeInTheDocument();
  });

  it('warns when nobody is signed in, and names a sign-in problem', async () => {
    renderWith(NOBODY, <UserChip />);
    expect(await screen.findByText('Not signed in · everyone can change things')).toBeInTheDocument();
  });

  it('flags a sign-in that is on but not working', async () => {
    renderWith({ ...NOBODY, mode: 'proxy-headers', problem: 'Sign-in is on, but this request had no user header.' }, <UserChip />);
    expect(await screen.findByText('Sign-in problem · see Setup check')).toBeInTheDocument();
  });

  it('marks the dev-only user', async () => {
    renderWith({ ...VIC, via: 'dev', name: 'priya@example.com' }, <UserChip />);
    expect(await screen.findByText('priya · Viewer (dev)')).toBeInTheDocument();
  });
});

const FINDING = {
  id: 4,
  service: 'cart',
  trust: { group: 'spike', tier: 'context', badge: null, moved: null, checks: [], tested: null, service: { real: 0, answered: 0, min_answers: 5 }, your_answer: null },
} as unknown as Finding;

describe('a signed-in Viewer', () => {
  it('sees "Was this real?" locked, with the reason', async () => {
    renderWith(VIC, <FindingTrustPanel finding={FINDING} answerOnly />);
    expect(await screen.findByText(WEB_LOCK_REASONS.answer)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Real problem' })).toBeDisabled();
  });

});

describe('an Editor', () => {
  it('can answer "Was this real?"', async () => {
    renderWith(PRIYA, <><UserChip /><FindingTrustPanel finding={FINDING} answerOnly /></>);
    // Wait until the backend has said who this is, so the check isn't made before roles apply.
    await screen.findByText('priya · Editor');
    expect(screen.getByRole('button', { name: 'Real problem' })).toBeEnabled();
    expect(screen.queryByText(WEB_LOCK_REASONS.answer)).not.toBeInTheDocument();
  });
});
