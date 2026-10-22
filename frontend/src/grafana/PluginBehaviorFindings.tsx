import React, { useState } from 'react';
import type { BehaviorFinding } from '../types';
import { conditionsPassed, formatChange, overlapMinutes, parseUtc, patternFindingsHref, patternParts } from '../utils/combinedPatterns';
import { findingLevel } from '../utils/findingLevel';
import { createCaseFromBehavior } from './backendClient';
import { LOCK_REASONS, usePermissions } from './permissions';
import { styles } from './plainUi';
import { useWebUiHref } from './webUiLink';

// Behavior findings (correlated, cross-metric patterns) with Create Case / Open Case, in the Grafana
// plugin's own styling. Same endpoint as the web UI's Behavior Intelligence page. The parent opens
// the case, so it can show it in the investigation drawer it already has.

export type PluginBehaviorFindingRow = {
  id: number;
  title: string;
  summary: string;
  severity: string;
  confidence: number;
  service?: string | null;
  case_id?: number | null;
} & Partial<Pick<BehaviorFinding,
  'definition_id' | 'definition_version' | 'input_metrics_json' | 'facts_json' | 'matched_conditions_json'
  | 'correlation_json' | 'occurrence_count' | 'last_seen_at'>>;

/** Where the symptom rows' "Part of" chip scrolls to. */
export const behaviorAnchor = (id: number) => `plugin-behavior-${id}`;

// Told apart by lightness as well as hue, as in the web UI's pattern cards.
const PART_COLORS = ['#2dd4bf', '#fbbf24', '#a78bfa', '#6e9fff'];
const chip: React.CSSProperties = { ...styles.chip, padding: '3px 9px', fontSize: 11 };

function clock(value: string | null): string | null {
  const time = parseUtc(value);
  return Number.isFinite(time) ? new Date(time).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : null;
}

/** What the match saw: each metric with its shape, change and window, then why it matched. */
function MatchEvidence({ finding }: { finding: PluginBehaviorFindingRow }) {
  const parts = patternParts({ input_metrics_json: finding.input_metrics_json ?? {}, facts_json: finding.facts_json ?? {} });
  if (!parts.length) return null;
  const conditions = conditionsPassed({ matched_conditions_json: finding.matched_conditions_json ?? [] });
  const overlap = overlapMinutes({ correlation_json: finding.correlation_json ?? {} });
  const seen = finding.occurrence_count ?? 1;
  return (
    <>
      <div aria-label="Metrics in this pattern" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {parts.map((part, index) => {
          const change = formatChange(part.change);
          const start = clock(part.start);
          const end = clock(part.end);
          return (
            <div key={part.alias} data-testid="plugin-behavior-metric" style={{ ...styles.rowBetween, gap: 10, padding: '6px 10px', borderRadius: 6, background: 'rgba(204, 204, 220, 0.05)' }}>
              <span style={{ fontFamily: 'monospace', fontSize: 12, overflowWrap: 'anywhere', minWidth: 0 }}>
                <span aria-hidden style={{ color: PART_COLORS[index % PART_COLORS.length] }}>● </span>{part.metric}
              </span>
              <span style={{ fontSize: 12 }}>
                {part.shape}
                {change ? <strong style={{ color: '#ff7381' }}> {change}</strong> : null}
                {start && end ? <span style={styles.muted}> · {start} – {end}</span> : null}
              </span>
            </div>
          );
        })}
      </div>
      <div style={{ ...styles.row, gap: 6 }}>
        {overlap !== null ? (
          <span style={{ ...chip, color: '#73bf69', borderColor: 'rgba(115, 191, 105, 0.5)' }} title="The rule checks that the metrics changed at the same time, not just in the same run.">
            Both at the same time · {overlap} min
          </span>
        ) : null}
        {conditions.total ? <span style={chip}>{conditions.passed} of {conditions.total} conditions passed</span> : null}
        <span style={chip}>{seen > 1 ? `Seen ${seen} times` : 'Seen once'}</span>
      </div>
    </>
  );
}

/** "Open in Ops Signals": the match's card on the web UI's Findings page, when its address is set. */
function OpenInWebUi({ finding }: { finding: PluginBehaviorFindingRow }) {
  const href = useWebUiHref(finding.last_seen_at ? patternFindingsHref({ id: finding.id, last_seen_at: finding.last_seen_at }) : null);
  return href ? <a href={href} target="_blank" rel="noreferrer" style={{ color: '#6e9fff', fontSize: 12 }}>Open in Ops Signals ↗</a> : null;
}

const LEVEL_TONE = { error: '#f2495c', warning: '#ffb357', default: '#8a95a5' } as const;

export function PluginBehaviorFindings({ backendUrl, findings, onOpenCase, frame }: {
  backendUrl: string;
  findings: PluginBehaviorFindingRow[];
  onOpenCase: (caseId: number) => void;
  /** Replaces the default bordered box, e.g. with styles.card where it sits among the page's cards. */
  frame?: React.CSSProperties;
}) {
  const { canEdit } = usePermissions();
  const managePatterns = useWebUiHref('/behavior-intelligence?tab=patterns');
  // Cases created here, so the row says Open Case without reloading the findings.
  const [createdCases, setCreatedCases] = useState<Record<number, number>>({});
  const [creatingId, setCreatingId] = useState<number | null>(null);
  const [error, setError] = useState('');

  if (!findings.length) return null;

  const createCase = async (finding: PluginBehaviorFindingRow) => {
    setCreatingId(finding.id);
    setError('');
    try {
      const created = await createCaseFromBehavior(backendUrl, finding.id);
      setCreatedCases((current) => ({ ...current, [finding.id]: created.case_id }));
      onOpenCase(created.case_id);
    } catch {
      setError(`Could not create a case for "${finding.title}". Check the backend connection and retry.`);
    } finally {
      setCreatingId(null);
    }
  };

  return (
    <section data-testid="plugin-behavior-findings" style={frame ? { ...styles.stack, gap: 10, ...frame } : { ...styles.stack, gap: 10, border: '1px solid rgba(204, 204, 220, 0.12)', borderRadius: 8, padding: 14 }}>
      <div style={{ ...styles.rowBetween, alignItems: 'baseline' }}>
        <div>
          <strong>Behavior findings</strong>
          <div style={{ ...styles.helperText, marginTop: 2 }}>
            Patterns across several metrics, such as a memory leak driving resource exhaustion. Usually closer to the cause than a single-metric finding.
          </div>
        </div>
        {managePatterns ? <a href={managePatterns} target="_blank" rel="noreferrer" style={{ color: '#6e9fff', fontSize: 12 }}>Manage patterns in Ops Signals ↗</a> : null}
      </div>
      {findings.map((finding) => {
        const caseId = createdCases[finding.id] ?? finding.case_id ?? null;
        const level = findingLevel(finding.severity);
        const tone = LEVEL_TONE[level.chip];
        return (
          <div key={finding.id} id={behaviorAnchor(finding.id)} data-testid="plugin-behavior-finding" style={{ ...styles.rowBetween, alignItems: 'flex-start', border: '1px solid rgba(204, 204, 220, 0.14)', borderRadius: 8, padding: 12, scrollMarginTop: 80 }}>
            <div style={{ minWidth: 0, flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div>
                <div style={{ ...styles.row, gap: 8 }}>
                  <strong>{finding.title}</strong>
                  <span style={{ ...styles.chip, color: tone, borderColor: `${tone}66` }}>{level.label}</span>
                  {finding.input_metrics_json && Object.keys(finding.input_metrics_json).length > 1 ? (
                    <span style={{ ...styles.helperText, margin: 0 }}>{Object.keys(finding.input_metrics_json).length} metrics combined</span>
                  ) : null}
                </div>
                {finding.summary ? <div style={{ ...styles.muted, fontSize: 13, marginTop: 4 }}>{finding.summary}</div> : null}
              </div>
              <MatchEvidence finding={finding} />
              <div style={{ ...styles.row, gap: 10 }}>
                <span style={{ ...styles.helperText, margin: 0 }}>
                  {[
                    finding.service,
                    `Confidence ${Math.round(finding.confidence * 100)}%`,
                    finding.definition_id ? `rule ${finding.definition_id}${finding.definition_version ? ` v${finding.definition_version}` : ''}` : null,
                    caseId ? `Case #${caseId}` : null,
                  ].filter(Boolean).join(' · ')}
                </span>
                <OpenInWebUi finding={finding} />
              </div>
            </div>
            {caseId ? (
              <button type="button" style={{ ...styles.button, background: 'rgba(204, 204, 220, 0.08)' }} onClick={() => onOpenCase(caseId)}>Open Case</button>
            ) : (
              <button
                type="button"
                style={{ ...styles.button, ...(creatingId !== null || !canEdit ? styles.buttonDisabled : {}) }}
                disabled={creatingId !== null || !canEdit}
                title={canEdit ? undefined : LOCK_REASONS.createCase}
                onClick={() => createCase(finding)}
              >
                {creatingId === finding.id ? 'Creating...' : `${canEdit ? '' : '🔒 '}Create Case`}
              </button>
            )}
          </div>
        );
      })}
      {error ? <div style={{ ...styles.helperText, color: '#ff7381' }}>{error}</div> : null}
    </section>
  );
}
