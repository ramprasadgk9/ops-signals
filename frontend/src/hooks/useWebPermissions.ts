import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';

// Who is using the web UI and what they may change (GET /api/me; backend/app/identity.py and roles.py).
// With no sign-in set up nobody is signed in and nothing is locked, as before sign-in existed. The
// backend enforces the same rules; this only locks buttons and says why.

type Role = 'Viewer' | 'Editor' | 'Admin';

export type Me = {
  signed_in: boolean;
  name: string | null;
  role: Role | null;
  via: 'grafana' | 'proxy' | 'oidc' | 'dev' | 'none';
  groups: string[];
  granted_by: string | null;
  mode: string;
  problem: string | null;
  /** Each page and the lowest role that may open it (backend/app/roles.py PAGES). */
  pages?: Record<string, Role>;
  /** Pages this person sees without their set-up part. */
  read_only_pages?: string[];
  /** With the backend's own sign-in (mode oidc): where to sign in, the button's words, whether to skip
   * the sign-in page, the provider's name for the person, and when the session ends. */
  login_url?: string | null;
  provider_name?: string | null;
  auto_redirect?: boolean;
  display_name?: string | null;
  session_ends_at?: string | null;
};

const RANKS = { Viewer: 1, Editor: 2, Admin: 3 } as const;

export const WEB_LOCK_REASONS = {
  runAnalysis: 'Editors can run analyses. Ask your Ops Signals admin for the Editor role.',
  answer: 'Editors answer this, because it changes the trust numbers for everyone. Ask your Ops Signals admin for the Editor role.',
  createCase: 'Editors can create cases.',
  workCase: 'Read-only for Viewers. Editors can investigate, add the root cause and resolve.',
  saveOrRun: 'Preview is open to everyone. Editors can save a schedule or run it.',
  schedule: 'Editors can change schedules. Ask your Ops Signals admin for the Editor role.',
  admin: 'Only Ops Signals admins can do this.',
  importIncidents: 'Only Ops Signals admins can import past incidents.',
} as const;

/** The role that applies, or null when nobody is signed in (then nothing is limited). */
export function effectiveRole(me: Me | undefined): Me['role'] {
  return me && me.via !== 'none' ? me.role : null;
}

export function allows(role: Me['role'], needed: 'Editor' | 'Admin'): boolean {
  return role === null || RANKS[role] >= RANKS[needed];
}

/** The lowest role that may open this page: the longest listed page that covers it ("/" is only
 * Overview), Admin when none does. Same rule as backend/app/roles.py page_role. */
export function pageRole(pages: Record<string, Role>, path: string): Role {
  const clean = path.replace(/\/+$/, '') || '/';
  const entry = Object.keys(pages)
    .filter((page) => clean === page || (page !== '/' && clean.startsWith(`${page}/`)))
    .sort((a, b) => b.length - a.length)[0];
  return entry ? pages[entry] : 'Admin';
}

export const ME_QUERY_KEY = ['me'];

export function useWebPermissions() {
  const query = useQuery({ queryKey: ME_QUERY_KEY, queryFn: api.me, retry: false, staleTime: 5 * 60_000 });
  const role = effectiveRole(query.data);
  const pages = query.data?.pages;
  /** The role a page needs, or null when this person may open it (always, with no sign-in). */
  const neededFor = (path: string): Role | null => {
    if (!pages) return null;
    const needed = pageRole(pages, path);
    return needed === 'Viewer' || allows(role, needed) ? null : needed;
  };
  return {
    me: query.data,
    role,
    /** True until GET /api/me has answered or failed: pages wait for it, so nothing closed flashes up. */
    loading: query.isPending,
    canEdit: allows(role, 'Editor'),
    canAdmin: allows(role, 'Admin'),
    neededFor,
    canOpen: (path: string) => neededFor(path) === null,
    isReadOnly: (path: string) => role !== null && (query.data?.read_only_pages ?? []).includes(path),
  };
}
