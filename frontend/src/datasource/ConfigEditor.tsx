import React from 'react';
import { Field, styles } from '../grafana/plainUi';
import type { OpsSignalsDataSourceOptions } from './types';

export function ConfigEditor({
  options,
  onChange,
}: {
  options: OpsSignalsDataSourceOptions;
  onChange: (next: OpsSignalsDataSourceOptions) => void;
}) {
  return (
    <div style={styles.stack}>
      <h2 style={{ margin: 0 }}>Datasource Settings</h2>
      <div style={styles.grid}>
        <Field label="Backend URL">
          <input
            style={styles.input}
            value={options.url}
            onChange={(event) => onChange({ ...options, url: event.target.value })}
            placeholder="http://localhost:8000"
          />
        </Field>
        <Field label="Default Service">
          <input
            style={styles.input}
            value={options.defaultService ?? ''}
            onChange={(event) => onChange({ ...options, defaultService: event.target.value })}
            placeholder="Optional service preselection"
          />
        </Field>
      </div>
    </div>
  );
}
