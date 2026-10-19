import React from 'react';
import { createContext, useContext } from 'react';
import type { PropsWithChildren } from 'react';

// What this person may change, from their Grafana role, when the plugin connects through Grafana.
// The backend enforces the same rules (backend/app/roles.py); this only locks buttons and says why.
// role null: no roles ("Browser, directly" mode, tests) - everything is allowed, as before roles.

export type GrafanaRole = 'Viewer' | 'Editor' | 'Admin';
const RANKS: Record<GrafanaRole, number> = { Viewer: 1, Editor: 2, Admin: 3 };

export const LOCK_REASONS = {
  runAnalysis: 'Editors can run analyses. Ask your Grafana admin for the Editor role.',
  answer: 'Editors answer this, because it changes the trust numbers for everyone.',
  createCase: 'Editors can create cases.',
  workCase: 'Read-only for Viewers. Editors can investigate, add the root cause and resolve.',
  schedule: 'Editors can change schedules.',
  saveOrRun: 'Preview is open to everyone. Editors can save a schedule or run it.',
  admin: 'Only Grafana admins can do this.',
} as const;

export function asGrafanaRole(value: unknown): GrafanaRole | null {
  return value === 'Viewer' || value === 'Editor' || value === 'Admin' ? value : null;
}

/** The signed-in user's role from the boot data Grafana puts on every page (a server admin counts as Admin). */
export function grafanaUserRole(): GrafanaRole | null {
  const user = (window as { grafanaBootData?: { user?: { orgRole?: string; isGrafanaAdmin?: boolean } } }).grafanaBootData?.user;
  if (!user) return null;
  return user.isGrafanaAdmin ? 'Admin' : asGrafanaRole(user.orgRole);
}

export function roleAllows(role: GrafanaRole | null, needed: GrafanaRole): boolean {
  return role === null || RANKS[role] >= RANKS[needed];
}

const PermissionsContext = createContext<GrafanaRole | null>(null);

export function PermissionsProvider({ role, children }: PropsWithChildren<{ role: GrafanaRole | null }>) {
  return <PermissionsContext.Provider value={role}>{children}</PermissionsContext.Provider>;
}

export function usePermissions() {
  const role = useContext(PermissionsContext);
  return {
    role,
    canEdit: roleAllows(role, 'Editor'),
    canAdmin: roleAllows(role, 'Admin'),
  };
}

/** The reason shown under a locked button. */
export function LockReason({ children, style }: PropsWithChildren<{ style?: React.CSSProperties }>) {
  return <span style={{ display: 'block', fontSize: 12, color: '#ffb357', marginTop: 6, ...style }}>{children}</span>;
}
