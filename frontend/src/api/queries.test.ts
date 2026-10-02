import { describe, expect, it, vi } from 'vitest';
import { getJson } from './client';
import { api } from './queries';

vi.mock('./client', () => ({
  getJson: vi.fn(async (url: string) => {
    const ids = new URLSearchParams(url.split('?')[1]).getAll('analysis_run_id');
    return ids.map((id) => ({ id: `sig-${id}`, analysis_run_id: id }));
  }),
  postJson: vi.fn(),
  postForm: vi.fn(),
  patchJson: vi.fn(),
  deleteJson: vi.fn(),
}));

describe('api.signalsByRunIds', () => {
  it('asks for many runs per request instead of one request per run', async () => {
    const runIds = Array.from({ length: 250 }, (_, index) => `run-${index}`);

    const signals = await api.signalsByRunIds([...runIds, 'run-0']);

    expect(getJson).toHaveBeenCalledTimes(3);
    expect(signals).toHaveLength(250);
    expect(new Set(signals.map((signal) => signal.analysis_run_id)).size).toBe(250);
  });
});
