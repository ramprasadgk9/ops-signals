import React, { useState } from 'react';
import { findingLevel } from '../utils/findingLevel';
import { createCaseFromBehavior } from './backendClient';
import { styles } from './plainUi';

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
};

const LEVEL_TONE = { error: '#f2495c', warning: '#ffb357', default: '#8a95a5' } as const;

export function PluginBehaviorFindings({ backendUrl, findings, onOpenCase, frame }: {
  backendUrl: string;
  findings: PluginBehaviorFindingRow[];
  onOpenCase: (caseId: number) => void;
  /** Replaces the default bordered box, e.g. with styles.card where it sits among the page's cards. */
  frame?: React.CSSProperties;
}) {
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
      <div>
        <strong>Behavior findings</strong>
        <div style={{ ...styles.helperText, marginTop: 2 }}>
          Patterns across several metrics, such as a memory leak driving resource exhaustion. Usually closer to the cause than a single-metric finding.
        </div>
      </div>
      {findings.map((finding) => {
        const caseId = createdCases[finding.id] ?? finding.case_id ?? null;
        const level = findingLevel(finding.severity);
        const tone = LEVEL_TONE[level.chip];
        return (
          <div key={finding.id} data-testid="plugin-behavior-finding" style={{ ...styles.rowBetween, alignItems: 'flex-start', border: '1px solid rgba(204, 204, 220, 0.14)', borderRadius: 8, padding: 12 }}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ ...styles.row, gap: 8 }}>
                <strong>{finding.title}</strong>
                <span style={{ ...styles.chip, color: tone, borderColor: `${tone}66` }}>{level.label}</span>
              </div>
              {finding.summary ? <div style={{ ...styles.muted, fontSize: 13, marginTop: 4 }}>{finding.summary}</div> : null}
              <div style={{ ...styles.helperText, marginTop: 4 }}>
                {[finding.service, `Confidence ${Math.round(finding.confidence * 100)}%`, caseId ? `Case #${caseId}` : null].filter(Boolean).join(' · ')}
              </div>
            </div>
            {caseId ? (
              <button type="button" style={{ ...styles.button, background: 'rgba(204, 204, 220, 0.08)' }} onClick={() => onOpenCase(caseId)}>Open Case</button>
            ) : (
              <button
                type="button"
                style={{ ...styles.button, ...(creatingId !== null ? styles.buttonDisabled : {}) }}
                disabled={creatingId !== null}
                onClick={() => createCase(finding)}
              >
                {creatingId === finding.id ? 'Creating...' : 'Create Case'}
              </button>
            )}
          </div>
        );
      })}
      {error ? <div style={{ ...styles.helperText, color: '#ff7381' }}>{error}</div> : null}
    </section>
  );
}
