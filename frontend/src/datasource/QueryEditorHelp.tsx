import React from 'react';
import { styles } from '../grafana/plainUi';

export function QueryEditorHelp() {
  return (
    <div style={styles.alert}>
      <h2 style={{ marginTop: 0 }}>Query Help</h2>
      <p>Use this editor to choose the service, metric, and time window. The datasource module sends that context to Ops Signals.</p>
      <ul>
        <li>Service: the workload or application you want to inspect.</li>
        <li>Metric: the time series the analyzers should evaluate.</li>
        <li>Time window: the period used to bound the analysis.</li>
      </ul>
    </div>
  );
}
