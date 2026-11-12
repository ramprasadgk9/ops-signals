import type { CSSProperties } from 'react';

import type { RecordingRule } from '../types';
import { NO_SERVICE_LABEL_NOTE, ruleAlertSentence, ruleNoteLead } from '../utils/recordingRules';
import { styles } from './plainUi';

const WARN: CSSProperties = { border: '1px solid rgba(255, 152, 48, 0.45)', background: 'rgba(255, 152, 48, 0.08)' };
const ERROR: CSSProperties = { border: '1px solid rgba(242, 73, 92, 0.45)', background: 'rgba(242, 73, 92, 0.08)' };
const code: CSSProperties = { display: 'block', marginTop: 6, padding: '6px 8px', borderRadius: 3, background: '#111217', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word' };

/** Under the Metric field: what a picked recording rule measures. */
export function PluginRecordingRuleNote({ rule, noServiceLabel }: { rule: RecordingRule; noServiceLabel?: boolean }) {
  const tone = rule.health === 'err' ? ERROR : noServiceLabel ? WARN : {};
  return (
    <div data-testid="recording-rule-note" style={{ ...styles.alert, ...tone, marginTop: 8, fontSize: 12.5 }}>
      <div><strong style={{ color: '#fff' }}>{rule.name}</strong>: {ruleNoteLead(rule)}</div>
      {rule.health === 'err' && rule.last_error ? <code style={code}>{rule.last_error}</code> : null}
      <code style={code}>{rule.query}</code>
      {rule.source_metrics.length ? <div style={{ ...styles.helperText }}>Built from {rule.source_metrics.join(', ')}</div> : null}
      {(rule.alerts ?? []).map((alert) => (
        <div key={alert.name} data-testid="recording-rule-alert" style={{ marginTop: 6 }}>
          {ruleAlertSentence(alert)}
          {alert.runbook_url ? (
            <>
              {' '}
              <a href={alert.runbook_url} target="_blank" rel="noopener noreferrer" style={{ color: '#5794f2' }}>Runbook</a>
            </>
          ) : null}
        </div>
      ))}
      {noServiceLabel ? <div style={{ marginTop: 6 }}>{NO_SERVICE_LABEL_NOTE}</div> : null}
    </div>
  );
}

/** Under the Metric list when a service is picked: rules left out because they have no service label. */
export function PluginHiddenRulesLine({ names }: { names: string[] }) {
  if (!names.length) return null;
  const what = names.length === 1 ? `1 recording rule (${names[0]}) isn't listed` : `${names.length} recording rules aren't listed`;
  return (
    <div data-testid="recording-rules-hidden" style={styles.helperText}>
      {what}: {names.length === 1 ? 'it adds' : 'they add'} up all services, so {names.length === 1 ? 'it has' : 'they have'} no service label and can't be analyzed per service.
    </div>
  );
}

/** Result view: the recording rule behind the analyzed metric. */
export function PluginRecordingRuleMeasured({ rule, promql }: { rule: RecordingRule; promql?: string | null }) {
  const row = (label: string, value: string) => (
    <>
      <span style={styles.muted}>{label}</span>
      <span style={{ fontFamily: code.fontFamily, wordBreak: 'break-word' }}>{value}</span>
    </>
  );
  return (
    <div data-testid="recording-rule-measured" style={styles.card}>
      <h3 style={{ margin: '0 0 10px' }}>How this was measured</h3>
      <div style={{ display: 'grid', gridTemplateColumns: '120px minmax(0, 1fr)', gap: '6px 12px', fontSize: 12.5 }}>
        {row('Recording rule', rule.group ? `${rule.name} (group ${rule.group})` : rule.name)}
        {row('Saved query', rule.query)}
        {rule.source_metrics.length ? row('Built from', rule.source_metrics.join(', ')) : null}
        {promql ? row('Query used', promql) : null}
      </div>
      <div style={styles.helperText}>This is the rule as it is now. If someone changed it since this run, older points used the old query.</div>
    </div>
  );
}
