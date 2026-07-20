import React from 'react';
import type { PanelProps } from '@grafana/data';
import { Card, Chip, styles } from './plainUi';

function ResultStat({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <div style={styles.label}>{label}</div>
      <strong style={{ fontSize: 22 }}>{value}</strong>
    </div>
  );
}

export function PluginPanel(props: PanelProps): JSX.Element {
  const summary = props.data.series[0]?.fields?.find((field) => field.name === 'summary')?.values?.get?.(0) ?? 'No data yet.';
  const signals = props.data.series[0]?.fields?.find((field) => field.name === 'signals')?.values?.get?.(0) ?? 0;
  const findings = props.data.series[0]?.fields?.find((field) => field.name === 'findings')?.values?.get?.(0) ?? 0;
  const behaviorFindings = props.data.series[0]?.fields?.find((field) => field.name === 'behaviorFindings')?.values?.get?.(0) ?? 0;
  const result = { summary, signals, findings, behaviorFindings };

  return (
    <Card>
      <div style={styles.stack}>
        <h2 style={{ margin: 0 }}>Panel View</h2>
        <p style={{ ...styles.muted, margin: 0 }}>This is the panel-friendly rendering surface for Grafana.</p>
        <div style={styles.row}>
          <ResultStat label="Signals" value={signals} />
          <ResultStat label="Findings" value={findings} />
          <ResultStat label="Behavior Findings" value={behaviorFindings} />
        </div>
        <div>
          <div style={styles.label}>Contract preview</div>
          <pre style={styles.pre}>{JSON.stringify(result, null, 2)}</pre>
        </div>
        <div style={styles.row}>
          <Chip>timeline</Chip>
          <Chip>signal evidence</Chip>
          <Chip>behavior reasoning</Chip>
          <Chip>case handoff</Chip>
        </div>
      </div>
    </Card>
  );
}
