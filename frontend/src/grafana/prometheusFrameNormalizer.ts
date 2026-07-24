import { FieldType } from '@grafana/data';

export type MetricSample = {
  timestamp: string;
  value: number;
  metric_name: string;
  service: string;
  labels?: Record<string, string>;
  series_id?: string;
};

export type NormalizedPrometheusSamples = {
  samples: MetricSample[];
  seriesCount: number;
  sampleCount: number;
  warnings: string[];
};

export type NormalizationOptions = {
  metricName: string;
  service: string;
  maxSeries: number;
  maxSamplesPerSeries: number;
};

function getValue(values: unknown, index: number) {
  if (Array.isArray(values)) return values[index];
  const vector = values as { get?: (index: number) => unknown; length?: number };
  if (typeof vector?.get === 'function') return vector.get(index);
  return undefined;
}

function valuesLength(values: unknown) {
  if (Array.isArray(values)) return values.length;
  const vector = values as { length?: number };
  return typeof vector?.length === 'number' ? vector.length : 0;
}

function normalizeTimestamp(value: unknown) {
  if (value instanceof Date) return value.toISOString();
  if (typeof value === 'number') return new Date(value > 1e11 ? value : value * 1000).toISOString();
  if (typeof value === 'string') {
    const numeric = Number(value);
    if (Number.isFinite(numeric)) return new Date(numeric > 1e11 ? numeric : numeric * 1000).toISOString();
    const parsed = new Date(value);
    if (!Number.isNaN(parsed.getTime())) return parsed.toISOString();
  }
  return null;
}

function seriesId(labels: Record<string, string>, fallback: string) {
  const labelEntries = Object.entries(labels).sort(([left], [right]) => left.localeCompare(right));
  return labelEntries.length ? labelEntries.map(([key, value]) => `${key}=${value}`).join(',') : fallback;
}

export function normalizePrometheusFrames(frames: Array<{ fields?: any[]; name?: string }>, options: NormalizationOptions): NormalizedPrometheusSamples {
  const warnings: string[] = [];
  const samples: MetricSample[] = [];
  let seriesCount = 0;

  for (const [frameIndex, frame] of frames.entries()) {
    const fields = frame.fields ?? [];
    const timeField = fields.find((field) => field.type === FieldType.time) ?? fields.find((field) => String(field.name).toLowerCase() === 'time');
    const numericFields = fields.filter((field) => field.type === FieldType.number);
    if (!timeField || numericFields.length === 0) continue;

    for (const valueField of numericFields) {
      seriesCount += 1;
      if (seriesCount > options.maxSeries) {
        throw new Error(`The query returned more than ${options.maxSeries} series. Narrow the service, metric, or query.`);
      }

      const labels = Object.fromEntries(
        Object.entries(valueField.labels ?? {}).filter((entry): entry is [string, string] => typeof entry[0] === 'string' && typeof entry[1] === 'string')
      );
      const identity = seriesId(labels, `${frame.name ?? 'series'}-${frameIndex}-${String(valueField.name ?? 'value')}`);
      const rowCount = Math.min(valuesLength(timeField.values), valuesLength(valueField.values));
      const step = rowCount > options.maxSamplesPerSeries ? Math.ceil(rowCount / options.maxSamplesPerSeries) : 1;
      if (step > 1) {
        warnings.push(`Series ${identity} was downsampled from ${rowCount} to about ${Math.ceil(rowCount / step)} samples.`);
      }

      for (let index = 0; index < rowCount; index += step) {
        const timestamp = normalizeTimestamp(getValue(timeField.values, index));
        const value = Number(getValue(valueField.values, index));
        if (!timestamp || !Number.isFinite(value)) continue;
        samples.push({
          timestamp,
          value,
          metric_name: labels.__name__ ?? options.metricName,
          service: options.service,
          labels,
          series_id: identity,
        });
      }
    }
  }

  if (!samples.length) {
    throw new Error('Prometheus returned no numeric time-series samples.');
  }

  const deduped = new Map<string, MetricSample>();
  for (const sample of samples) {
    deduped.set(`${sample.series_id ?? ''}|${sample.timestamp}|${sample.value}`, sample);
  }

  const sorted = [...deduped.values()].sort((left, right) => {
    const timeDiff = new Date(left.timestamp).getTime() - new Date(right.timestamp).getTime();
    return timeDiff || String(left.series_id ?? '').localeCompare(String(right.series_id ?? ''));
  });

  return {
    samples: sorted,
    seriesCount,
    sampleCount: sorted.length,
    warnings,
  };
}

