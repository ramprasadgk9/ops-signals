import type { MemoryStatsResponse, OperationalCase } from '../types';

export type MemorySummary = {
  indexedItems: number;
  source: 'recent-case-list' | 'memory-stats';
  isCompleteTotal: boolean;
  availability: 'available' | 'unavailable' | 'disabled';
};

export function buildMemorySummary(cases: OperationalCase[]): MemorySummary {
  return {
    indexedItems: cases.filter((item) => item.memory_status === 'indexed').length,
    source: 'recent-case-list',
    isCompleteTotal: false,
    availability: 'available',
  };
}

export function buildMemorySummaryFromStats(stats: MemoryStatsResponse | undefined): MemorySummary | null {
  if (!stats) return null;
  return {
    indexedItems: stats.indexed_cases,
    source: 'memory-stats',
    isCompleteTotal: true,
    availability: !stats.enabled ? 'disabled' : stats.status === 'healthy' ? 'available' : 'unavailable',
  };
}
