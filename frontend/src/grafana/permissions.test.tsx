import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { FindingTrust } from '../types';
import { grafanaUserRole, LOCK_REASONS, PermissionsProvider, roleAllows } from './permissions';
import { PluginFindingTrust } from './PluginFindingTrust';

vi.mock('./backendClient', () => ({ sendFindingFeedback: vi.fn() }));

describe('roleAllows', () => {
  it('ranks Viewer < Editor < Admin, and allows everything without a role', () => {
    expect(roleAllows('Viewer', 'Editor')).toBe(false);
    expect(roleAllows('Editor', 'Editor')).toBe(true);
    expect(roleAllows('Editor', 'Admin')).toBe(false);
    expect(roleAllows('Admin', 'Admin')).toBe(true);
    expect(roleAllows(null, 'Admin')).toBe(true);
  });
});

describe('grafanaUserRole', () => {
  it("reads the user's org role, a server admin counting as Admin", () => {
    Object.assign(window, { grafanaBootData: { user: { orgRole: 'Viewer', isGrafanaAdmin: false } } });
    expect(grafanaUserRole()).toBe('Viewer');
    Object.assign(window, { grafanaBootData: { user: { orgRole: 'Viewer', isGrafanaAdmin: true } } });
    expect(grafanaUserRole()).toBe('Admin');
    delete (window as { grafanaBootData?: unknown }).grafanaBootData;
    expect(grafanaUserRole()).toBeNull();
  });
});

const TRUST: FindingTrust = {
  group: 'level_change_agree',
  tier: 'context',
  badge: null,
  moved: null,
  checks: [],
  tested: null,
  service: { real: 0, answered: 0, min_answers: 5 },
  your_answer: null,
};

describe('a Viewer on "Was this real?"', () => {
  it('sees the answers locked, with the reason', () => {
    render(
      <PermissionsProvider role="Viewer">
        <PluginFindingTrust backendUrl="/proxy" findingId={4} trust={TRUST} />
      </PermissionsProvider>
    );
    expect(screen.getByRole('button', { name: 'Real problem' })).toBeDisabled();
    expect(screen.getByText(LOCK_REASONS.answer)).toBeInTheDocument();
  });

  it('is unlocked for an Editor', () => {
    render(
      <PermissionsProvider role="Editor">
        <PluginFindingTrust backendUrl="/proxy" findingId={4} trust={TRUST} />
      </PermissionsProvider>
    );
    expect(screen.getByRole('button', { name: 'Real problem' })).toBeEnabled();
    expect(screen.queryByText(LOCK_REASONS.answer)).not.toBeInTheDocument();
  });
});
