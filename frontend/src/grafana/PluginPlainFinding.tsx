import React, { useState } from 'react';
import type { FindingPlain } from '../types';
import { plainLines, plainTimes, plainTone, type PlainTone } from '../utils/findingPlain';
import { styles } from './plainUi';

// A finding in plain words in the plugin's own styling: the same wording as the web UI's
// PlainFindingSummary (utils/findingPlain.ts, config/finding_templates.yaml).

const TONE: Record<PlainTone, { color: string; border: string; background: string }> = {
  bad: { color: '#ff7381', border: 'rgba(255, 115, 129, 0.45)', background: 'rgba(255, 115, 129, 0.1)' },
  good: { color: '#3fcf8e', border: 'rgba(63, 207, 142, 0.45)', background: 'rgba(63, 207, 142, 0.1)' },
  gap: { color: '#ffb357', border: 'rgba(255, 179, 87, 0.45)', background: 'rgba(255, 179, 87, 0.1)' },
  neutral: { color: '#a8b3c4', border: 'rgba(204, 204, 220, 0.25)', background: 'transparent' },
};

export function PluginPlainBadge({ plain }: { plain: FindingPlain }) {
  const tone = TONE[plainTone(plain.badge)];
  return (
    <span
      data-testid="plugin-plain-badge"
      style={{ ...styles.chip, color: tone.color, borderColor: tone.border, background: tone.background, fontWeight: 600, flex: 'none' }}
    >
      {plain.badge_label}
    </span>
  );
}

export function PluginPlainFinding({ plain, details }: { plain: FindingPlain; details: string }) {
  const [showDetails, setShowDetails] = useState(false);
  const lines = plainLines(plain);
  return (
    <div data-testid="plugin-plain" style={{ ...styles.stack, gap: 8 }}>
      <p style={{ margin: 0 }}>{plainTimes(plain.what)}</p>
      {lines.length ? (
        <dl style={{ margin: 0, display: 'grid', gridTemplateColumns: 'minmax(96px, auto) minmax(0, 1fr)', columnGap: 12, rowGap: 6, fontSize: 13 }}>
          {lines.map((line, index) => (
            <React.Fragment key={`${line.label}-${index}`}>
              <dt style={{ ...styles.muted, fontWeight: 600 }}>{line.label}</dt>
              <dd style={{ margin: 0, minWidth: 0 }}>{line.text}</dd>
            </React.Fragment>
          ))}
        </dl>
      ) : null}
      <div>
        <button type="button" aria-expanded={showDetails} style={{ ...styles.tableRowButton, padding: 0 }} onClick={() => setShowDetails(!showDetails)}>
          {showDetails ? '▾' : '▸'} Technical details
        </button>
        {showDetails ? (
          <p data-testid="plugin-plain-details" style={{ ...styles.muted, margin: '4px 0 0', fontSize: 13 }}>
            {details}
          </p>
        ) : null}
      </div>
    </div>
  );
}
