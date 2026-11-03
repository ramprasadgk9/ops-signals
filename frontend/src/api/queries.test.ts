import { describe, expect, it, vi } from 'vitest';
import { getJson, postJson } from './client';
import { DEMO_STEP_EVENT } from '../demo/events';
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

describe('creating a case', () => {
  it('ticks off the demo guide\'s case step once the case exists, not when the request fails', async () => {
    const marks: string[] = [];
    const listener = (event: Event) => marks.push(String((event as CustomEvent).detail));
    window.addEventListener(DEMO_STEP_EVENT, listener);
    vi.mocked(postJson).mockResolvedValueOnce({ case_id: 7 }).mockResolvedValueOnce({ case_id: 8 }).mockRejectedValueOnce(new Error('down'));

    await api.createCase(42);
    await api.createCaseFromBehavior(5);
    await expect(api.createCase(43)).rejects.toThrow('down');

    window.removeEventListener(DEMO_STEP_EVENT, listener);
    expect(marks).toEqual(['case-created', 'case-created']);
  });
});
