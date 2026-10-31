import React from 'react';
import type { PodSplit } from '../types';
import { COMBINE_ORDER, combineName } from '../utils/podCombine';
import { styles } from './plainUi';

// A PromQL query that returned one series per pod: the web UI's Combine buttons (Advanced mode of
// New Analysis) in the plugin's own styling. A button only puts a query in the PromQL box.

const BLUE_BORDER = 'rgba(87, 148, 242, 0.55)';

const buttonStyle: React.CSSProperties = {
  border: `1px solid ${BLUE_BORDER}`,
  borderRadius: 3,
  background: 'transparent',
  color: '#6e9fff',
  padding: '4px 9px',
  fontSize: 12,
  fontWeight: 600,
  cursor: 'pointer',
};

export function PluginPodCombineBox({ pods, onUseQuery }: { pods: PodSplit; onUseQuery: (query: string) => void }) {
  const { label, odd } = pods;
  const oddQuery = odd ? pods.one_queries?.[odd.value] : undefined;
  return (
    <div data-testid="pod-combine-box" style={{ ...styles.alert, marginTop: 12 }}>
      <strong style={{ color: '#fff' }}>This query returns {pods.values.length} lines, one per {label}. Analysis needs one line.</strong>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, margin: '9px 0 6px' }}>
        {COMBINE_ORDER.map((how) => (
          <button
            key={how}
            type="button"
            style={how === pods.suggested_combine ? { ...buttonStyle, background: 'rgba(87, 148, 242, 0.18)', color: '#fff' } : buttonStyle}
            onClick={() => onUseQuery(pods.queries[how])}
          >
            Combine: {combineName(how, label).toLowerCase()}
          </button>
        ))}
      </div>
      <div style={{ ...styles.helperText, marginTop: 0 }}>
        Each button puts a new query in the PromQL box; you can edit it before running. The usual way for this metric is {combineName(pods.suggested_combine, label).toLowerCase()}.
      </div>
      {odd ? (
        <div style={{ marginTop: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, background: 'rgba(0, 0, 0, 0.25)', borderLeft: '3px solid #ff4d57', borderRadius: 3, padding: '7px 9px', fontSize: 12 }}>
          <span>{odd.message}</span>
          {oddQuery ? (
            <button type="button" style={{ ...buttonStyle, whiteSpace: 'nowrap' }} onClick={() => onUseQuery(oddQuery)}>
              Analyze only {odd.value}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
