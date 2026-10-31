import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { connectionPodSplit, podSplit, runPrometheusSampleAnalysis } from './backendClient';

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

  it('sends a line Grafana already combined with how it was combined', async () => {
    const combined = { label: 'pod', count: 30, how: 'avg' as const, original_query: TARGET.promql };
    mockRun({ ...RUN, promql: 'avg by (service) (request_latency_p95{service="search-svc"})', series_count: 1, combined: { ...combined, odd: null } });

    const result = await runPrometheusSampleAnalysis('http://backend', { ...TARGET, promql: 'avg by (service) (request_latency_p95{service="search-svc"})', combined });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(String(init.body));
    expect(body.combined).toEqual(combined);
    expect(body).not.toHaveProperty('combine');
    expect(result.analyzedAs).toBe('Analyzed as one line: the average of 30 pods.');
  });

  it('asks how to combine series from their labels', async () => {
    const split = { label: 'pod', values: ['a', 'b'], suggested_combine: 'sum', queries: { sum: 'sum by (service) (q)' } };
    fetchMock = vi.fn(async () => new Response(JSON.stringify(split), { status: 200, headers: { 'content-type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await podSplit('http://backend', { query: 'q', metric: 'm', labels: [{ pod: 'a' }, { pod: 'b' }] });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://backend/api/ingestion/pod-split');
    expect(JSON.parse(String(init.body))).toEqual({ query: 'q', metric: 'm', labels: [{ pod: 'a' }, { pod: 'b' }] });
    expect(result).toEqual(split);
  });

  it('asks a connection preview how its pods would combine', async () => {
    const pods = { label: 'pod', values: ['a', 'b', 'c'], suggested_combine: 'avg', queries: {}, one_queries: {}, odd: null };
    fetchMock = vi.fn(async () => new Response(JSON.stringify({ series_count: 3, pods }), { status: 200, headers: { 'content-type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await connectionPodSplit('http://backend', { connectionId: 'team-a', query: 'q', from: '2026-07-26T10:00:00Z', to: '2026-07-26T11:00:00Z', stepSeconds: 60 });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://backend/api/prometheus/preview');
    expect(JSON.parse(String(init.body))).toEqual({ connection_id: 'team-a', query: 'q', start: '2026-07-26T10:00:00Z', end: '2026-07-26T11:00:00Z', step: '60s' });
    expect(result).toEqual(pods);
  });
});
