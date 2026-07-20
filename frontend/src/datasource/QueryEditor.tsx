import React from 'react';
import { Chip, Field, styles } from '../grafana/plainUi';
import type { OpsSignalsQuery } from './types';

const queryPresets = [
  { label: 'Service latency spike', service: 'checkout', metric: 'http_request_duration_seconds' },
  { label: 'CPU throttling review', service: 'payments', metric: 'container_cpu_usage_seconds_total' },
  { label: 'Memory growth check', service: 'api', metric: 'container_memory_usage_bytes' },
];

export function QueryEditor({
  query,
  services,
  metrics,
  onChange,
}: {
  query: OpsSignalsQuery;
  services: string[];
  metrics: string[];
  onChange: (next: OpsSignalsQuery) => void;
}) {
  return (
    <div style={styles.stack}>
      <h2 style={{ margin: 0 }}>Query Editor</h2>
      <div style={styles.grid}>
        <Field label="Service">
          <select style={styles.input} value={query.service} onChange={(event) => onChange({ ...query, service: event.target.value })}>
            <option value="" />
            {services.map((service) => (
              <option key={service} value={service}>
                {service}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Metric">
          <select style={styles.input} value={query.metric} onChange={(event) => onChange({ ...query, metric: event.target.value })}>
            <option value="" />
            {metrics.map((metric) => (
              <option key={metric} value={metric}>
                {metric}
              </option>
            ))}
          </select>
        </Field>
        <Field label="From">
          <input style={styles.input} value={query.from} onChange={(event) => onChange({ ...query, from: event.target.value })} />
        </Field>
        <Field label="To">
          <input style={styles.input} value={query.to} onChange={(event) => onChange({ ...query, to: event.target.value })} />
        </Field>
      </div>
      <div style={styles.row}>
        {queryPresets.map((preset) => (
          <Chip key={preset.label} onClick={() => onChange({ ...query, service: preset.service, metric: preset.metric })}>
            {preset.label}
          </Chip>
        ))}
      </div>
    </div>
  );
}
