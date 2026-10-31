import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { runPrometheusSampleAnalysis } from './backendClient';

const RUN = {
  analysis_run_id: 'run-grafana', promql: 'request_latency_p95{service="search-svc"}', sample_count: 240, series_count: 4, signal_count: 1,
  findings_count: 1, behavior_findings_count: 0, warnings: [], analyzer_selection_mode: 'recommended_threshold',
};

function respond(url: string, run: unknown): unknown {
  if (url.includes('/api/ingestion/prometheus-run')) return run;
  if (url.includes('/api/timeseries')) return [{ timestamp: '2026-07-26T10:00:00Z', value: 90 }];
  return [];
}

const TARGET = {
  datasourceUid: 'prom', datasourceName: 'Prometheus', service: 'search-svc', metric: 'request_latency_p95',
  promql: 'request_latency_p95{service="search-svc"}', from: '2026-07-26T10:00:00Z', to: '2026-07-26T11:00:00Z', stepSeconds: 60,
  samples: [], seriesCount: 4, sampleCount: 0, warnings: [], durationMs: 5,
};

describe('runPrometheusSampleAnalysis (Grafana data source)', () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  const mockRun = (run: unknown) => {
    fetchMock = vi.fn(async (url: string) => new Response(JSON.stringify(respond(url, run)), { status: 200, headers: { 'content-type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);
  };
  beforeEach(() => mockRun(RUN));
  afterEach(() => vi.unstubAllGlobals());

  it('asks for per-pod series to be combined and says how the run read them', async () => {
    const combined = { label: 'pod', count: 4, how: 'avg', odd: { value: 'search-svc-2', message: 'search-svc-2 is behaving differently from the other 3 pods: it reaches 1,150 while the others stay near 91.' } };
    mockRun({ ...RUN, promql: 'avg by (service) (request_latency_p95{service="search-svc"})', combined });

    const result = await runPrometheusSampleAnalysis('http://backend', { ...TARGET, combine: 'auto' });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://backend/api/ingestion/prometheus-run');
    expect(JSON.parse(String(init.body)).combine).toBe('auto');
    expect(result.promql).toBe('avg by (service) (request_latency_p95{service="search-svc"})');
    expect(result.analyzedAs).toBe(`Analyzed as one line: the average of 4 pods. ${combined.odd.message}`);
  });

  it('leaves a PromQL query as written', async () => {
    const result = await runPrometheusSampleAnalysis('http://backend', TARGET);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).not.toHaveProperty('combine');
    expect(result.promql).toBe(TARGET.promql);
    expect(result.analyzedAs).toBeNull();
  });
});
