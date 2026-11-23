import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { listPrometheusLabelValues, runConnectionAnalysis } from './backendClient';
import { buildMetricQuery } from './prometheusQueryBuilder';

const RUN = {
  analysis_run_id: 'run-eu', connection_name: 'Mimir team-a (eu, us)', sample_count: 652, series_count: 1, signal_count: 2,
  findings_count: 1, behavior_findings_count: 0, warnings: ['Kept one copy of each HA replica pair'], analyzer_selection_mode: 'recommended_threshold',
};

function respond(url: string): unknown {
  if (url.includes('/api/analysis/prometheus')) return RUN;
  if (url.includes('/api/timeseries')) return [{ timestamp: '2026-10-09T00:00:00Z', value: 1 }];
  if (url.includes('/api/findings')) return [{ id: 7, title: 'p95 stepped up', summary: '', category: 'behavior_change', health_status: 'warning', importance_score: 0.8, investigation_priority: 1, signal_ids: [], comparison_json: {}, metric_name: 'request_latency_p95' }];
  return [];
}

describe('runConnectionAnalysis', () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn(async (url: string) => new Response(JSON.stringify(respond(url)), { status: 200, headers: { 'content-type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it('asks the backend to analyse the series on the connection, then loads the run with its cluster', async () => {
    const result = await runConnectionAnalysis('http://backend', {
      connectionId: 'team-a', connectionName: 'team-a', service: 'checkout', metric: 'request_latency_p95',
      promql: 'request_latency_p95{service="checkout",cluster="eu"}', from: '2026-10-08T00:00:00Z', to: '2026-10-09T00:00:00Z', stepSeconds: 120, cluster: 'eu',
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://backend/api/analysis/prometheus');
    expect(JSON.parse(String(init.body))).toEqual({
      connection_id: 'team-a', query: 'request_latency_p95{service="checkout",cluster="eu"}', service: 'checkout', metric: 'request_latency_p95',
      start: '2026-10-08T00:00:00Z', end: '2026-10-09T00:00:00Z', step: '120s', execution_mode: 'persist',
    });
    const timeseriesUrl = fetchMock.mock.calls.map(([called]) => String(called)).find((called) => called.includes('/api/timeseries'));
    expect(timeseriesUrl).toContain('analysis_run_id=run-eu');
    expect(timeseriesUrl).toContain('cluster=eu');
    expect(result).toMatchObject({ runId: 'run-eu', cluster: 'eu', connection: 'Mimir team-a (eu, us)', datasource: 'Mimir team-a (eu, us)', sampleCount: 652, warnings: ['Kept one copy of each HA replica pair'] });
    expect(result.findings.map((finding) => finding.title)).toEqual(['p95 stepped up']);
  });

  it("keeps the problem's case on each finding, so the card can say Open Case", async () => {
    fetchMock.mockImplementation(async (url: string) => new Response(JSON.stringify(
      url.includes('/api/findings') ? [{ ...(respond(url) as object[])[0], case_id: 12, case_status: 'resolved' }] : respond(url),
    ), { status: 200 }));

    const result = await runConnectionAnalysis('http://backend', {
      connectionId: 'team-a', connectionName: 'team-a', service: 'checkout', metric: 'request_latency_p95',
      promql: 'request_latency_p95{service="checkout"}', from: 'S', to: 'E', stepSeconds: 120,
    });

    expect(result.findings[0]).toMatchObject({ case_id: 12, case_status: 'resolved' });
  });

  it('asks for per-pod series to be combined and says how the run read them', async () => {
    const combined = { label: 'pod', count: 4, how: 'avg', odd: { value: 'checkout-2', message: 'checkout-2 is behaving differently from the other 3 pods: it reaches 1,150 while the others stay near 90.' } };
    fetchMock.mockImplementation(async (url: string) => new Response(JSON.stringify(
      url.includes('/api/analysis/prometheus') ? { ...RUN, query: 'avg by (service) (request_latency_p95{service="checkout"})', combined } : respond(url),
    ), { status: 200 }));

    const result = await runConnectionAnalysis('http://backend', {
      connectionId: 'team-a', connectionName: 'team-a', service: 'checkout', metric: 'request_latency_p95',
      promql: 'request_latency_p95{service="checkout"}', from: 'S', to: 'E', stepSeconds: 120, combine: 'auto',
    });

    expect(JSON.parse(String((fetchMock.mock.calls[0] as [string, RequestInit])[1].body)).combine).toBe('auto');
    expect(result.promql).toBe('avg by (service) (request_latency_p95{service="checkout"})');
    expect(result.analyzedAs).toBe(`Analyzed as one line: the average of 4 pods. ${combined.odd.message}`);
  });

  it('lists label values on a connection, narrowed to matching series in a range', async () => {
    fetchMock.mockImplementation(async () => new Response(JSON.stringify({ connection_id: 'team-a', label: 'cluster', values: ['eu', 'us'] }), { status: 200 }));

    const response = await listPrometheusLabelValues('http://backend', 'cluster', 'team-a', { match: ['request_latency_p95{service="checkout"}'], start: 'S', end: 'E' });

    expect(response.values).toEqual(['eu', 'us']);
    const url = new URL(String(fetchMock.mock.calls[0][0]));
    expect(url.pathname).toBe('/api/prometheus/label-values');
    expect(url.searchParams.get('connection_id')).toBe('team-a');
    expect(url.searchParams.getAll('match')).toEqual(['request_latency_p95{service="checkout"}']);
    expect(url.searchParams.get('start')).toBe('S');
  });
});

describe('buildMetricQuery cluster', () => {
  it('adds the cluster matcher in metric mode only', () => {
    expect(buildMetricQuery({ metric: 'error_rate', mode: 'metric', service: 'checkout', serviceLabel: 'service', cluster: { label: 'cluster', value: 'us' } }))
      .toBe('error_rate{service="checkout",cluster="us"}');
    expect(buildMetricQuery({ metric: 'error_rate', mode: 'metric', service: 'checkout', serviceLabel: 'service' })).toBe('error_rate{service="checkout"}');
    expect(buildMetricQuery({ metric: 'sum(rate(x[5m]))', mode: 'promql', service: 'checkout', serviceLabel: 'service', cluster: { label: 'cluster', value: 'us' } }))
      .toBe('sum(rate(x[5m]))');
    expect(() => buildMetricQuery({ metric: 'x', mode: 'metric', service: 'a', serviceLabel: 'service', cluster: { label: 'bad label', value: 'us' } })).toThrow('Invalid cluster label');
  });
});
