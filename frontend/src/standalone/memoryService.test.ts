import { describe, expect, it } from 'vitest';
import { buildMemorySummaryFromStats } from './memoryService';

describe('memory service', () => {
  it('treats healthy memory stats as authoritative', () => {
    expect(buildMemorySummaryFromStats({
      generated_at: '2026-07-26T00:00:00Z',
      enabled: true,
      status: 'healthy',
      indexed_cases: 2,
      not_indexed_cases: 1,
      stale_cases: 0,
      error_cases: 0,
      total_cases: 3,
      source: 'ops_operational_cases.memory_status',
    })).toEqual({
      indexedItems: 2,
      source: 'memory-stats',
      isCompleteTotal: true,
      availability: 'available',
    });
  });

  it('marks enabled but unhealthy memory as unavailable', () => {
    expect(buildMemorySummaryFromStats({
      generated_at: '2026-07-26T00:00:00Z',
      enabled: true,
      status: 'unhealthy',
      indexed_cases: 2,
      not_indexed_cases: 1,
      stale_cases: 0,
      error_cases: 0,
      total_cases: 3,
      source: 'ops_operational_cases.memory_status',
    })?.availability).toBe('unavailable');
  });
});
