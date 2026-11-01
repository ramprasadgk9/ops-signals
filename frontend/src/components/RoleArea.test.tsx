import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/queries';
import { pageRole, type Me } from '../hooks/useWebPermissions';
import { AppShell } from './AppShell';
import { RoleArea } from './RoleArea';

vi.mock('../api/queries', () => ({
  api: {
    me: vi.fn(),
    health: vi.fn().mockResolvedValue({ status: 'ok' }),
    memoryHealth: vi.fn().mockResolvedValue({ status: 'ok' }),
    findingsSearch: vi.fn().mockResolvedValue([]),
    ingestionStatus: vi.fn().mockResolvedValue({ generated_at: '', has_any_data: true, sources: {}, features: [] }),
  },
}));

// The same table the backend sends (backend/app/roles.py PAGES), shortened to what these tests open.
const PAGES: NonNullable<Me['pages']> = {
  '/': 'Viewer', '/alerts': 'Viewer', '/findings': 'Viewer', '/cases': 'Viewer', '/metric-usage': 'Viewer',
  '/behavior-intelligence': 'Viewer', '/recurring-problems': 'Viewer', '/assistant': 'Viewer', '/autonomous-monitoring': 'Viewer',
  '/validate-data': 'Editor', '/analyzer-recommendation': 'Editor',
  '/integrations': 'Admin', '/experiments': 'Admin', '/assistant/docs-check': 'Admin', '/settings': 'Admin', '/setup-check': 'Admin',
};
const NOBODY: Me = { signed_in: false, name: null, role: null, via: 'none', groups: [], granted_by: null, mode: 'none', problem: null, pages: PAGES, read_only_pages: [] };
const SAM: Me = { signed_in: true, name: 'sam@example.com', role: 'Viewer', via: 'proxy', groups: [], granted_by: null, mode: 'proxy-headers', problem: null, pages: PAGES, read_only_pages: ['/autonomous-monitoring'] };
const PRIYA: Me = { ...SAM, name: 'priya@example.com', role: 'Editor', granted_by: 'sre', read_only_pages: [] };
const ADMIN: Me = { ...PRIYA, name: 'admin@example.com', role: 'Admin' };

function renderAt(me: Me, path: string) {
  vi.mocked(api.me).mockResolvedValue(me);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AppShell>
          <RoleArea name="This page"><p>page content</p></RoleArea>
        </AppShell>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const menu = () => screen.getAllByRole('link').map((link) => link.textContent?.trim());

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('pageRole', () => {
  it('uses the longest listed page, keeps "/" to Overview, and closes unlisted pages to all but Admins', () => {
    expect(pageRole(PAGES, '/cases/412')).toBe('Viewer');
    expect(pageRole(PAGES, '/assistant/docs-check')).toBe('Admin');
    expect(pageRole(PAGES, '/experiments/trend-lab')).toBe('Admin');
    expect(pageRole(PAGES, '/settings/')).toBe('Admin');
    expect(pageRole(PAGES, '/something-new')).toBe('Admin');
  });
});

describe('the menu by role', () => {
  it('shows a Viewer only the pages they can open, and drops sections left empty', async () => {
    renderAt(SAM, '/');
    expect(await screen.findByText('page content')).toBeInTheDocument();
    await screen.findByRole('link', { name: 'Findings' });
    expect(menu()).toEqual(expect.arrayContaining(['Overview', 'Findings', 'Cases', 'Metric Usage', 'Autonomous Analysis']));
    for (const hidden of ['Integrations', 'New Analysis', 'Settings', 'Setup check', 'Add Analyzer', 'Which analyzer fits?', 'Autonomous Analysis Configure']) {
      expect(menu()).not.toContain(hidden);
    }
    expect(screen.queryByText('Analyzer Workbench')).not.toBeInTheDocument();
  });

  it('gives an Editor New Analysis and Recommendations, but no set-up pages', async () => {
    renderAt(PRIYA, '/');
    await screen.findByRole('link', { name: 'Findings' });
    // Recommendations sits in the Analyzer Workbench, which stays folded until opened.
    expect(menu()).toEqual(expect.arrayContaining(['New Analysis', 'Autonomous Analysis Configure']));
    for (const hidden of ['Integrations', 'Settings', 'Setup check']) expect(menu()).not.toContain(hidden);
    expect(screen.getByText('Analyzer Workbench')).toBeInTheDocument();
  });

  it('shows Admins every page, and everyone every page with no sign-in', async () => {
    for (const me of [ADMIN, NOBODY]) {
      renderAt(me, '/');
      await screen.findByRole('link', { name: 'Findings' });
      expect(menu()).toEqual(expect.arrayContaining(['Integrations', 'Settings', 'Setup check', 'New Analysis']));
      cleanup();
    }
  });
});

describe('a page opened by its address', () => {
  it('stays closed to a role it is not for, and never loads', async () => {
    renderAt(PRIYA, '/settings');
    expect(await screen.findByRole('heading', { name: 'This page is for Ops Signals admins' })).toBeInTheDocument();
    expect(screen.getByText("You're signed in as priya (Editor). Ask your Ops Signals admin if you need it.")).toBeInTheDocument();
    expect(screen.queryByText('page content')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go to Overview' })).toHaveAttribute('href', '/');
  });

  it('tells a Viewer to ask for the Editor role', async () => {
    renderAt(SAM, '/validate-data');
    expect(await screen.findByRole('heading', { name: 'This page is for Editors' })).toBeInTheDocument();
    expect(screen.getByText(/Ask your Ops Signals admin for the Editor role/)).toBeInTheDocument();
  });

  it('opens for the right role, and for everyone when the backend sends no page list', async () => {
    renderAt(ADMIN, '/settings');
    expect(await screen.findByText('page content')).toBeInTheDocument();
    cleanup();
    renderAt({ ...SAM, pages: undefined }, '/settings');
    expect(await screen.findByText('page content')).toBeInTheDocument();
  });
});
