import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getCaseStillSeen } from './backendClient';
import { PluginStillSeen } from './PluginStillSeen';

vi.mock('./backendClient', () => ({ getCaseStillSeen: vi.fn() }));
const stillSeen = vi.mocked(getCaseStillSeen);

describe('PluginStillSeen', () => {
  beforeEach(() => {
    stillSeen.mockReset();
  });

  it('warns when the problem is still being found', async () => {
    stillSeen.mockResolvedValue({ still_seen: true, finding_id: 57, seen_at: '2026-09-14T10:30:00Z' });

    render(<PluginStillSeen backendUrl="http://backend" caseId={12} />);

    const warning = await screen.findByTestId('plugin-still-seen');
    expect(warning).toHaveTextContent('This problem is still showing up.');
    expect(warning).toHaveTextContent('(finding #57)');
    expect(stillSeen).toHaveBeenCalledWith('http://backend', 12);
  });

  it('shows nothing when the problem is not being found any more', async () => {
    stillSeen.mockResolvedValue({ still_seen: false, finding_id: null, seen_at: null });

    render(<PluginStillSeen backendUrl="http://backend" caseId={12} />);

    await waitFor(() => expect(stillSeen).toHaveBeenCalled());
    expect(screen.queryByTestId('plugin-still-seen')).toBeNull();
  });

  it('shows nothing when the check fails', async () => {
    stillSeen.mockRejectedValue(new Error('backend down'));

    render(<PluginStillSeen backendUrl="http://backend" caseId={12} />);

    await waitFor(() => expect(stillSeen).toHaveBeenCalled());
    expect(screen.queryByTestId('plugin-still-seen')).toBeNull();
  });
});
