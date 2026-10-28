import type React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PluginShiftHandoff } from './PluginShiftHandoff';
import { getAiStatus, getCase, getShiftHandoff, writeShiftHandoffNote } from './backendClient';
import type { AIStatus, ShiftHandoff } from '../types';

vi.mock('./backendClient', () => ({
  getShiftHandoff: vi.fn(),
  writeShiftHandoffNote: vi.fn(),
  getAiStatus: vi.fn(),
  getCase: vi.fn(),
}));
vi.mock('./PanelPreview', () => ({ InvestigationDrawer: ({ open }: { open: boolean }) => (open ? <div data-testid="case-drawer" /> : null) }));

const aiOff: AIStatus = { enabled: false, provider: 'none', model: null, endpoint: null, api_key_set: null, active: false, issue: null };

const handoff: ShiftHandoff = {
  generated_at: '2026-10-27T12:00:00Z',
  hours: 12,
  since: '2026-10-27T00:00:00Z',
  new_findings: 4,
  cases_opened: 2,
  cases_resolved: 1,
  cases_still_open: 2,
  older_open_cases: 0,
  watch: [
    { kind: 'case', title: 'Payments errors up', service: 'payments', metric_name: 'error_rate', case_id: 10, finding_id: 1, reason: 'open 8 hours, started after deploy v2.3, critical', live: true },
    { kind: 'finding', title: 'Search slower', service: 'search', metric_name: 'latency_p95', finding_id: 4, reason: 'no case yet, seen 3 hours ago, high', live: true },
  ],
  summary: 'Last 12 hours: 4 new findings, 2 cases opened, 1 resolved. 2 cases still open.',
};

function renderOpen(ui: React.ReactElement) {
  const view = render(ui);
  fireEvent.click(screen.getByRole('button', { name: '⇄ Shift handoff' }));
  return view;
}

describe('PluginShiftHandoff', () => {
  beforeEach(() => {
    vi.mocked(getShiftHandoff).mockReset().mockResolvedValue(handoff);
    vi.mocked(getAiStatus).mockReset().mockResolvedValue(aiOff);
    vi.mocked(writeShiftHandoffNote).mockReset();
    vi.mocked(getCase).mockReset().mockResolvedValue({ id: 10 } as never);
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
  });

  it('shows the counts and opens the case to watch in the case drawer', async () => {
    renderOpen(<PluginShiftHandoff backendUrl="/api/plugin" />);
    expect(await screen.findByTestId('plugin-shift-handoff-counts')).toHaveTextContent('4 new findings · 2 cases opened · 1 resolved · 2 still open');
    fireEvent.click(screen.getByRole('button', { name: 'Open case' }));
    expect(await screen.findByTestId('case-drawer')).toBeInTheDocument();
    expect(getCase).toHaveBeenCalledWith('/api/plugin', 10);
  });

  it('opens a finding through the overview, and says so when it is not there', async () => {
    const onOpenFinding = vi.fn().mockReturnValueOnce(true).mockReturnValueOnce(false);
    renderOpen(<PluginShiftHandoff backendUrl="/api/plugin" onOpenFinding={onOpenFinding} />);
    const finding = await screen.findByRole('button', { name: /search \/ latency_p95/ });
    fireEvent.click(finding);
    expect(onOpenFinding).toHaveBeenCalledWith(4);
    expect(screen.queryByText(/not in the overview window/)).toBeNull();
    fireEvent.click(finding);
    expect(await screen.findByText(/not in the overview window/)).toBeInTheDocument();
  });

  it('copies without web UI links, and writes the AI note when AI is on', async () => {
    vi.mocked(getAiStatus).mockResolvedValue({ ...aiOff, enabled: true, active: true });
    vi.mocked(writeShiftHandoffNote).mockResolvedValue({ available: true, note: 'Watch case #10 on payments.' });
    renderOpen(<PluginShiftHandoff backendUrl="/api/plugin" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Write with AI' }));
    expect(await screen.findByTestId('plugin-shift-handoff-note')).toHaveTextContent('Watch case #10 on payments.');
    fireEvent.click(screen.getByRole('button', { name: 'Copy for Slack' }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalled());
    const text = vi.mocked(navigator.clipboard.writeText).mock.calls[0][0];
    expect(text.startsWith('Watch case #10 on payments.')).toBe(true);
    expect(text).not.toContain('http');
  });

  it('loads nothing until opened, and closes again', async () => {
    render(<PluginShiftHandoff backendUrl="/api/plugin" />);
    expect(getShiftHandoff).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '⇄ Shift handoff' }));
    await screen.findByTestId('plugin-shift-handoff-counts');
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.queryByTestId('plugin-shift-handoff')).toBeNull();
  });

  it('switches the window and says so when the backend fails', async () => {
    const { container } = renderOpen(<PluginShiftHandoff backendUrl="/api/plugin" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Last 8h' }));
    await waitFor(() => expect(getShiftHandoff).toHaveBeenCalledWith('/api/plugin', 8));
    vi.mocked(getShiftHandoff).mockRejectedValue(new Error('down'));
    fireEvent.click(screen.getByRole('button', { name: 'Last 24h' }));
    expect(await screen.findByText(/could not be loaded/)).toBeInTheDocument();
  });
});
