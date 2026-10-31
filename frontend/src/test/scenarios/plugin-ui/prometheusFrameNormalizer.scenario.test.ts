import { describe, expect, it, vi } from 'vitest';

import { frameSeriesLabels, normalizePrometheusFrames } from '../../../grafana/prometheusFrameNormalizer';

vi.mock('@grafana/data', () => ({
  FieldType: {
    time: 'time',
    number: 'number',
  },
}));

const FieldType = {
  time: 'time',
  number: 'number',
};

const options = {
  metricName: 'container_cpu_usage_seconds_total',
  service: 'checkout-api',
  maxSeries: 5,
  maxSamplesPerSeries: 100,
};

describe('Prometheus frame normalization scenarios', () => {
  it('given a valid Grafana Prometheus frame, returns ordered plugin samples with labels and series identity', () => {
    const result = normalizePrometheusFrames(
      [
        {
          name: 'cpu',
          fields: [
            { name: 'Time', type: FieldType.time, values: [1785000000000, 1785000300000] },
            {
              name: 'Value',
              type: FieldType.number,
              values: [0.42, 0.65],
              labels: { __name__: 'container_cpu_usage_seconds_total', service: 'checkout-api', pod: 'checkout-1' },
            },
          ],
        },
      ],
      options
    );

    expect(result.seriesCount).toBe(1);
    expect(result.sampleCount).toBe(2);
    expect(result.warnings).toEqual([]);
    expect(result.samples[0]).toMatchObject({
      metric_name: 'container_cpu_usage_seconds_total',
      service: 'checkout-api',
      value: 0.42,
      labels: { service: 'checkout-api', pod: 'checkout-1' },
      series_id: '__name__=container_cpu_usage_seconds_total,pod=checkout-1,service=checkout-api',
    });
  });

  it('given malformed Grafana frame data, fails instead of producing a false successful analysis payload', () => {
    expect(() =>
      normalizePrometheusFrames(
        [
          {
            name: 'bad-frame',
            fields: [{ name: 'Time', type: FieldType.time, values: [1785000000000] }],
          },
        ],
        options
      )
    ).toThrow('Prometheus returned no numeric time-series samples.');
  });

  it('given duplicate Grafana samples, deduplicates them so repeated frames do not create false-positive volume', () => {
    const result = normalizePrometheusFrames(
      [
        {
          name: 'cpu',
          fields: [
            { name: 'Time', type: FieldType.time, values: [1785000000000, 1785000000000] },
            {
              name: 'Value',
              type: FieldType.number,
              values: [0.42, 0.42],
              labels: { service: 'checkout-api' },
            },
          ],
        },
      ],
      options
    );

    expect(result.sampleCount).toBe(1);
    expect(result.samples).toHaveLength(1);
  });

  it('given more series than are sent, lists each one\'s labels without reading samples', () => {
    const frames = Array.from({ length: 30 }, (_, index) => ({
      name: `pod-${index}`,
      fields: [
        { name: 'Time', type: FieldType.time, values: [1_700_000_000_000] },
        { name: 'Value', type: FieldType.number, values: [1], labels: { service: 'search-svc', pod: `search-svc-${index}` } },
      ],
    }));

    const labels = frameSeriesLabels([...frames, { name: 'no-time', fields: [{ name: 'Value', type: FieldType.number, values: [1] }] }]);

    expect(labels).toHaveLength(30);
    expect(labels[29]).toEqual({ service: 'search-svc', pod: 'search-svc-29' });
    expect(() => normalizePrometheusFrames(frames, options)).toThrow('more than 5 series');
  });
});
