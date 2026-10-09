import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getCaseSameFix } from './backendClient';
import { PluginSameFix } from './PluginSameFix';

vi.mock('./backendClient', () => ({ getCaseSameFix: vi.fn() }));
const sameFix = vi.mocked(getCaseSameFix);

describe('PluginSameFix', () => {
  beforeEach(() => {
    sameFix.mockReset();
  });

  it('lists past cases fixed the same way, with how each fix held', async () => {
    sameFix.mockResolvedValue({
      case_id: 3,
      available: true,
      outcome: { status: 'held', label: 'Fix held' },
      matches: [
        {
          case_id: 9,
          title: 'Payments pool exhaustion',
          service: 'payments',
          similarity_score: 0.87,
          corrective_action: 'Raised pool size to 50',
          rca_verified: true,
          outcome: { status: 'came_back', label: 'Came back after 12 days' },
        },
      ],
    });

    render(<PluginSameFix backendUrl="http://backend" caseId={3} />);

    const row = await screen.findByTestId('plugin-same-fix-match');
    expect(sameFix).toHaveBeenCalledWith('http://backend', 3);
    expect(screen.getByText('Fix held')).toBeInTheDocument();
    expect(row).toHaveTextContent('Payments pool exhaustion');
    expect(row).toHaveTextContent('Came back after 12 days');
    expect(row).toHaveTextContent('Case #9 · payments · 87% same cause and fix · verified cause');
    expect(row).toHaveTextContent('Fix: Raised pool size to 50');
  });

  it('explains why there is nothing to compare yet', async () => {
    sameFix.mockResolvedValue({ case_id: 3, available: false, reason: 'No cause or fix recorded for this case yet.', matches: [] });

    render(<PluginSameFix backendUrl="http://backend" caseId={3} />);

    expect(await screen.findByText('No cause or fix recorded for this case yet.')).toBeInTheDocument();
  });

  it('says when no other case was fixed this way', async () => {
    sameFix.mockResolvedValue({ case_id: 3, available: true, matches: [] });

    render(<PluginSameFix backendUrl="http://backend" caseId={3} />);

    expect(await screen.findByText('No other case was fixed this way.')).toBeInTheDocument();
  });
});
