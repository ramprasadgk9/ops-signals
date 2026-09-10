import { describe, expect, it } from 'vitest';

import { buildMetricQuery, buildServiceMatcher, escapePrometheusLabelValue, validatePromQL } from '../../../grafana/prometheusQueryBuilder';

describe('Grafana Prometheus query scenarios', () => {
  it('given metric mode and service input, builds a scoped Prometheus query for the selected service', () => {
    expect(
      buildMetricQuery({
        mode: 'metric',
        metric: 'http_request_duration_seconds',
        service: 'checkout-api',
        serviceLabel: 'service',
      })
    ).toBe('http_request_duration_seconds{service="checkout-api"}');
  });

  it('given a PromQL expression with service placeholder, replaces only the service value safely', () => {
    expect(
      buildMetricQuery({
        mode: 'promql',
        metric: 'sum(rate(http_requests_total{service="$service"}[5m]))',
        service: 'checkout"api',
        serviceLabel: 'service',
      })
    ).toBe('sum(rate(http_requests_total{service="checkout\\"api"}[5m]))');
  });

  it('given invalid query or label input, rejects it instead of issuing misleading plugin requests', () => {
    expect(() => validatePromQL('up\nrate(http_requests_total[5m])')).toThrow('PromQL must be a single expression.');
    expect(() => buildServiceMatcher('service-name', 'checkout')).toThrow('Invalid service label');
    expect(() =>
      buildMetricQuery({
        mode: 'metric',
        metric: 'sum(rate(http_requests_total[5m]))',
        service: 'checkout',
        serviceLabel: 'service',
      })
    ).toThrow('Metric mode requires a raw Prometheus metric name.');
  });

  it('given special characters in service names, escapes them to avoid false-positive broad queries', () => {
    expect(escapePrometheusLabelValue('checkout\\api"\nprod')).toBe('checkout\\\\api\\"\\nprod');
  });
});
