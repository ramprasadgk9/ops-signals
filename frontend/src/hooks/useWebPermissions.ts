import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';

// Who is using the web UI and what they may change (GET /api/me; backend/app/identity.py and roles.py).
// With no sign-in set up nobody is signed in and nothing is locked, as before sign-in existed. The
// backend enforces the same rules; this only locks buttons and says why.

export type Me = {
  signed_in: boolean;
  name: string | null;
  role: 'Viewer' | 'Editor' | 'Admin' | null;
  via: 'grafana' | 'proxy' | 'dev' | 'none';
  groups: string[];
  granted_by: string | null;
  mode: string;
  problem: string | null;
};

const RANKS = { Viewer: 1, Editor: 2, Admin: 3 } as const;

export const WEB_LOCK_REASONS = {
  runAnalysis: 'Editors can run analyses. Ask your Ops Signals admin for the Editor role.',
  answer: 'Editors answer this, because it changes the trust numbers for everyone. Ask your Ops Signals admin for the Editor role.',
  createCase: 'Editors can create cases.',
  workCase: 'Read-only for Viewers. Editors can investigate, add the root cause and resolve.',
  saveOrRun: 'Preview is open to everyone. Editors can save a schedule or run it.',
  admin: 'Only Ops Signals admins can do this.',
} as const;

/** The role that applies, or null when nobody is signed in (then nothing is limited). */
export function effectiveRole(me: Me | undefined): Me['role'] {
  return me && me.via !== 'none' ? me.role : null;
}

export function allows(role: Me['role'], needed: 'Editor' | 'Admin'): boolean {
  return role === null || RANKS[role] >= RANKS[needed];
}

export const ME_QUERY_KEY = ['me'];

export function useWebPermissions() {
  const query = useQuery({ queryKey: ME_QUERY_KEY, queryFn: api.me, retry: false, staleTime: 5 * 60_000 });
  const role = effectiveRole(query.data);
  return { me: query.data, role, canEdit: allows(role, 'Editor'), canAdmin: allows(role, 'Admin') };
}
