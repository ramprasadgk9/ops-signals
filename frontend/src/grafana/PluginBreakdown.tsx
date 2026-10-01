import React, { useState } from 'react';
import type { Finding } from '../types';
import {
  breakdownNextStep,
  breakdownScopeLabel,
  breakdownSentence,
  breakdownUnavailableReason,
  findingBreakdown,
  formatValue,
  type BreakdownPart,
  type FindingBreakdown,
} from '../utils/findingBreakdown';
import { styles } from './plainUi';

// The finding drill-down (docs/finding-drilldown.md) in the Grafana plugin's own styling. The words
// come from utils/findingBreakdown, shared with the web UI's FindingBreakdown, so both say the same.

const HOT = '#f2495c';
const WARM = '#ffb357';
const TRACK = 'rgba(204, 204, 220, 0.12)';
const IDLE = 'rgba(204, 204, 220, 0.35)';

function spreadTone(breakdown: FindingBreakdown): string {
  return breakdown.spread === 'widespread' ? WARM : HOT;
}

function barWidth(part: BreakdownPart, breakdown: FindingBreakdown, largest: number): number {
  if (breakdown.mode === 'share') return Math.max(0, Math.min(1, part.share ?? 0)) * 100;
  if (largest === 0 || part.relative_change === null) return 0;
  return Math.max(0, Math.min(1, Math.abs(part.relative_change) / largest)) * 100;
}

function barValue(part: BreakdownPart, breakdown: FindingBreakdown): string {
  if (breakdown.mode === 'share') return `${Math.round((part.share ?? 0) * 100)}%`;
  if (part.relative_change === null) return '–';
  return `${part.relative_change > 0 ? '+' : ''}${Math.round(part.relative_change * 100)}%`;
}

type ScopeChipProps = {
  finding: Pick<Finding, 'comparison_json'> | null | undefined;
  onClick?: () => void;
  /** Set when the chip shows/hides the breakdown in place; adds an arrow and aria-expanded. */
  expanded?: boolean;
};

/** "1 of 6 pods" chip for a finding with a breakdown; nothing otherwise. */
export function PluginScopeChip({ finding, onClick, expanded }: ScopeChipProps) {
  const breakdown = finding ? findingBreakdown(finding) : null;
  const scope = breakdownScopeLabel(breakdown);
  if (!breakdown || !scope) return null;
  const tone = spreadTone(breakdown);
  const chipStyle: React.CSSProperties = { ...styles.chip, width: 'fit-content', color: tone, borderColor: `${tone}66`, background: 'transparent' };
  const action = expanded === undefined ? ' Click for the full breakdown.' : expanded ? ' Click to hide the breakdown.' : ' Click to show the breakdown.';
  const title = `${breakdownSentence(breakdown)}${onClick ? action : ''}`;
  return onClick ? (
    <button
      type="button"
      title={title}
      aria-expanded={expanded}
      onClick={onClick}
      style={{ ...chipStyle, cursor: 'pointer', font: 'inherit', fontSize: 12 }}
    >
      {scope}{expanded === undefined ? '' : expanded ? ' \u25be' : ' \u25b8'}
    </button>
  ) : (
    <span title={title} style={chipStyle}>{scope}</span>
  );
}

/** "Where the change came from": per-pod bars and the likely next step, or why there's no breakdown. */
export function PluginBreakdownSection({ breakdown }: { breakdown: FindingBreakdown }) {
  if (breakdown.status !== 'ok') {
    return (
      <p style={{ ...styles.muted, fontSize: 12, margin: 0, border: '1px dashed rgba(204, 204, 220, 0.2)', borderRadius: 8, padding: 10 }}>
        Breakdown by pod not available: {breakdownUnavailableReason(breakdown)}
      </p>
    );
  }
  const parts = breakdown.top ?? [];
  const largest = Math.max(0, ...parts.map((part) => Math.abs(part.relative_change ?? 0)));
  const label = breakdown.label ?? 'pod';
  return (
    <div data-testid="plugin-finding-breakdown" style={{ ...styles.stack, gap: 8, border: '1px solid rgba(204, 204, 220, 0.12)', borderRadius: 8, padding: 14 }}>
      <div style={styles.row}>
        <strong>Where the change came from</strong>
        <PluginScopeChip finding={{ comparison_json: { breakdown } }} />
      </div>
      <div>{breakdownSentence(breakdown)}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {parts.map((part) => (
          <div
            key={part.value}
            title={`${label} ${part.value}: ${formatValue(part.before)} → ${formatValue(part.after)}`}
            style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 170px) 1fr 52px', gap: 8, alignItems: 'center', fontSize: 12 }}
          >
            <span style={{ fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {part.value}{part.new ? ' ✦' : ''}
            </span>
            <span style={{ height: 8, borderRadius: 4, background: TRACK, overflow: 'hidden' }}>
              <span style={{ display: 'block', height: '100%', width: `${barWidth(part, breakdown, largest)}%`, background: part.moved ? HOT : IDLE, borderRadius: 4 }} />
            </span>
            <span style={{ ...styles.muted, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{barValue(part, breakdown)}</span>
          </div>
        ))}
        {breakdown.others && breakdown.others.count > 0 ? (
          <span style={{ ...styles.muted, fontSize: 12 }}>
            + {breakdown.others.count} other {breakdown.others.count === 1 ? label : `${label}s`}
            {breakdown.others.moved > 0 ? `, ${breakdown.others.moved} of them also changed` : ', unchanged'}
          </span>
        ) : null}
      </div>
      <span style={{ ...styles.muted, fontSize: 12 }}>
        {parts.some((part) => part.new) ? `✦ new ${label}: no data before the change. ` : ''}
        {breakdown.mode === 'share' ? 'Bars: share of the total change.' : `Bars: change compared with each ${label}’s own normal level.`}
      </span>
      <div><strong>Likely next step:</strong> {breakdownNextStep(breakdown)}</div>
    </div>
  );
}

/** The scope chip, opening the breakdown right below it on click - for lists without a details panel. */
export function PluginBreakdownDisclosure({ finding }: { finding: Pick<Finding, 'comparison_json'> }) {
  const [open, setOpen] = useState(false);
  const breakdown = findingBreakdown(finding);
  if (!breakdown || !breakdownScopeLabel(breakdown)) return null;
  return (
    <div style={{ ...styles.stack, gap: 8, marginTop: 6 }}>
      <PluginScopeChip finding={finding} expanded={open} onClick={() => setOpen((value) => !value)} />
      {open ? <PluginBreakdownSection breakdown={breakdown} /> : null}
    </div>
  );
}
