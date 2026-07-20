import React, { useEffect, useMemo, useState } from 'react';
import {
  answerQuestion,
  createCaseFromFinding,
  getCase,
  indexCaseMemory,
  listAvailableQuestions,
  updateCaseInvestigation,
  updateCaseRca,
  updateCaseResolution,
} from './backendClient';
import { Card, Chip, Field, styles } from './plainUi';
import type {
  GrafanaAnalysisFinding,
  GrafanaAnalysisResult,
  GrafanaAnalysisSignal,
  GrafanaCase,
  GrafanaCaseCreateResponse,
  GrafanaQuestion,
  GrafanaQuestionAnswer,
} from './contracts';

const steps = ['Finding', 'Investigation', 'Root Cause', 'Resolution', 'Publish Knowledge'] as const;
type DrawerStep = typeof steps[number];

function humanize(value?: string | null) {
  if (!value) return 'Not available';
  return value
    .split(/[_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function formatNumber(value: number | null | undefined, digits = 2) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : 'n/a';
}

function formatPercent(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value * 100)}%` : 'n/a';
}

function confidenceLabel(value: number | null | undefined) {
  if (value == null) return 'Unknown';
  if (value >= 0.75) return 'High';
  if (value >= 0.45) return 'Medium';
  return 'Low';
}

function formatDate(value?: string | null) {
  if (!value) return 'n/a';
  return new Date(value).toLocaleString();
}

function buttonStyle(variant: 'primary' | 'secondary' | 'danger' = 'secondary', disabled = false): React.CSSProperties {
  const base = variant === 'primary' ? styles.button : { ...styles.button, background: 'transparent', border: '1px solid rgba(204, 204, 220, 0.28)' };
  const danger = variant === 'danger' ? { ...base, borderColor: 'rgba(242, 73, 92, 0.55)', color: '#ff8f99' } : base;
  return disabled ? { ...danger, ...styles.buttonDisabled } : danger;
}

function StatusPill({ children, tone = 'neutral' }: { children: React.ReactNode; tone?: 'success' | 'warning' | 'danger' | 'neutral' }) {
  const color = tone === 'success' ? '#3fcf8e' : tone === 'warning' ? '#ffb357' : tone === 'danger' ? '#ff7381' : 'rgba(204, 204, 220, 0.78)';
  return <span style={{ ...styles.chip, color, background: 'rgba(24, 27, 31, 0.8)' }}>{children}</span>;
}

function statusTone(value?: string | null): 'success' | 'warning' | 'danger' | 'neutral' {
  const normalized = (value ?? '').toLowerCase();
  if (normalized.includes('resolved') || normalized.includes('indexed') || normalized.includes('complete') || normalized.includes('normal')) return 'success';
  if (normalized.includes('stale') || normalized.includes('pending') || normalized.includes('progress')) return 'warning';
  if (normalized.includes('critical') || normalized.includes('failed') || normalized.includes('significant')) return 'danger';
  return 'neutral';
}

function metricStats(result: GrafanaAnalysisResult, selectedFinding: GrafanaAnalysisFinding | null) {
  const values = result.timeseries.map((point) => point.value);
  const peak = values.length ? Math.max(...values) : null;
  const current = values.length ? values[values.length - 1] : null;
  const average = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
  return {
    current,
    average,
    peak,
    anomalyWindows: selectedFinding?.signal_ids.length ?? result.signals.length,
  };
}

function MetricTimeline({ result, selectedFinding }: { result: GrafanaAnalysisResult; selectedFinding: GrafanaAnalysisFinding | null }) {
  const width = 920;
  const height = 250;
  const padding = 34;
  const points = result.timeseries ?? [];
  const sampledPoints = points.length > 520 ? points.filter((_, index) => index % Math.ceil(points.length / 520) === 0) : points;
  const values = sampledPoints.map((point) => point.value);
  const min = values.length ? Math.min(...values) : 0;
  const max = values.length ? Math.max(...values) : 1;
  const range = max - min || 1;
  const stats = metricStats(result, selectedFinding);

  const path = sampledPoints
    .map((point, index) => {
      const x = padding + (index / Math.max(1, sampledPoints.length - 1)) * (width - padding * 2);
      const y = height - padding - ((point.value - min) / range) * (height - padding * 2);
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(' ');

  const anomalyCount = Math.min(selectedFinding?.signal_ids.length ?? 0, 16);

  return (
    <Card>
      <div style={styles.stack}>
        <div style={styles.rowBetween}>
          <h3 style={{ margin: 0 }}>Metric timeline</h3>
          <button type="button" style={buttonStyle()}>Auto</button>
        </div>
        <div style={styles.compactStats}>
          <div><span style={styles.label}>Current</span><strong>{formatNumber(stats.current)}</strong></div>
          <div><span style={styles.label}>Average</span><strong>{formatNumber(stats.average)}</strong></div>
          <div><span style={styles.label}>Peak</span><strong>{formatNumber(stats.peak)}</strong></div>
          <div><span style={styles.label}>Anomaly windows</span><strong>{stats.anomalyWindows}</strong></div>
        </div>
        {points.length === 0 ? (
          <p style={{ ...styles.muted, margin: 0 }}>No time-series samples were returned for this run.</p>
        ) : (
          <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${result.metric} timeline`} style={{ width: '100%', height: 260 }}>
            <rect x="0" y="0" width={width} height={height} rx="8" fill="rgba(5, 8, 12, 0.5)" />
            {[0, 1, 2, 3].map((line) => {
              const y = padding + line * ((height - padding * 2) / 3);
              return <line key={line} x1={padding} x2={width - padding} y1={y} y2={y} stroke="rgba(204, 204, 220, 0.16)" />;
            })}
            {Array.from({ length: anomalyCount }).map((_, index) => {
              const x = padding + ((index + 1) / (anomalyCount + 1)) * (width - padding * 2);
              return <rect key={index} x={x - 7} y={padding} width={14} height={height - padding * 2} fill="rgba(242, 73, 92, 0.18)" />;
            })}
            <line x1={padding} x2={width - padding} y1={height - padding - 42} y2={height - padding - 42} stroke="rgba(204, 204, 220, 0.45)" strokeDasharray="6 6" />
            <path d={path} fill="none" stroke="#5794f2" strokeWidth="3" />
            <text x={padding} y={height - 10} fill="rgba(204, 204, 220, 0.72)" fontSize="12">{new Date(points[0].timestamp).toLocaleDateString()}</text>
            <text x={width - padding} y={height - 10} fill="rgba(204, 204, 220, 0.72)" fontSize="12" textAnchor="end">{new Date(points[points.length - 1].timestamp).toLocaleDateString()}</text>
          </svg>
        )}
        <div style={styles.row}>
          <StatusPill>{result.metric}</StatusPill>
          <StatusPill>Baseline</StatusPill>
          <StatusPill tone="danger">Anomaly window</StatusPill>
        </div>
        {points[0]?.timestamp?.startsWith('2014-') ? (
          <div style={styles.infoNote}>Sample dataset: February 14-28, 2014</div>
        ) : null}
      </div>
    </Card>
  );
}

function PrimaryFindingCard({
  finding,
  onInvestigate,
  onCreateCase,
  onViewEvidence,
  isBusy,
}: {
  finding: GrafanaAnalysisFinding | null;
  onInvestigate: () => void;
  onCreateCase: () => void;
  onViewEvidence: () => void;
  isBusy: boolean;
}) {
  if (!finding) {
    return (
      <Card>
        <h2 style={{ marginTop: 0 }}>No finding selected</h2>
        <p style={{ ...styles.muted, marginBottom: 0 }}>Run analysis or select a finding to begin an investigation.</p>
      </Card>
    );
  }

  return (
    <div style={styles.primaryFinding}>
      <div style={styles.findingIcon}>⌁</div>
      <div style={styles.stack}>
        <div style={styles.rowBetween}>
          <StatusPill tone={statusTone(finding.health_status)}>{humanize(finding.health_status).toUpperCase()}</StatusPill>
          <button type="button" style={buttonStyle()}>...</button>
        </div>
        <h2 style={{ margin: 0 }}>{finding.title}</h2>
        <p style={{ ...styles.muted, margin: 0 }}>{finding.summary || 'Operational behavior changed during the selected window.'}</p>
        <div style={styles.row}>
          <StatusPill>Importance {formatNumber(finding.importance_score)}</StatusPill>
          <StatusPill>Confidence {formatNumber(finding.importance_score)}</StatusPill>
          <StatusPill>Category {humanize(finding.category)}</StatusPill>
        </div>
        <div style={styles.row}>
          <button type="button" style={buttonStyle('primary')} onClick={onInvestigate}>Investigate</button>
          <button type="button" style={buttonStyle('secondary', isBusy)} disabled={isBusy} onClick={onCreateCase}>
            {isBusy ? 'Creating...' : 'Create Case'}
          </button>
          <button type="button" style={buttonStyle()} onClick={onViewEvidence}>View Evidence</button>
        </div>
      </div>
    </div>
  );
}

function SuggestedQuestionsCard({
  questions,
  answer,
  onAsk,
}: {
  questions: GrafanaQuestion[];
  answer: GrafanaQuestionAnswer | null;
  onAsk: (question: GrafanaQuestion) => void;
}) {
  const visibleQuestions = questions.slice(0, 3);
  return (
    <Card>
      <div style={styles.stack}>
        <h3 style={{ margin: 0 }}>Suggested questions</h3>
        {(visibleQuestions.length ? visibleQuestions : [
          { id: 'what_changed', label: 'What changed?', description: '', contributors: [], available: false },
          { id: 'investigate_first', label: 'What should I investigate first?', description: '', contributors: [], available: false },
          { id: 'new_expected', label: 'Is this new or expected?', description: '', contributors: [], available: false },
        ]).map((question) => (
          <button key={question.id} type="button" style={styles.questionButton} disabled={!question.available} onClick={() => onAsk(question)}>
            <span>◌</span>
            <span>{question.label}</span>
          </button>
        ))}
        <button type="button" style={{ ...buttonStyle(), alignSelf: 'flex-start' }}>More questions →</button>
        {answer ? (
          <div style={styles.answerCard}>
            <div style={styles.row}>
              <StatusPill>{humanize(answer.status)}</StatusPill>
              <StatusPill>Priority: {humanize(answer.priority)}</StatusPill>
              <StatusPill>Confidence: {formatPercent(answer.confidence)}</StatusPill>
            </div>
            <h4 style={{ margin: '4px 0' }}>{answer.headline}</h4>
            <p style={{ margin: 0 }}>{answer.answer}</p>
          </div>
        ) : null}
      </div>
    </Card>
  );
}

function EvidenceSummaryCard({
  result,
  finding,
  signals,
  expanded,
  onToggle,
}: {
  result: GrafanaAnalysisResult;
  finding: GrafanaAnalysisFinding | null;
  signals: GrafanaAnalysisSignal[];
  expanded: boolean;
  onToggle: () => void;
}) {
  const stats = metricStats(result, finding);
  const earliest = result.timeseries[0]?.timestamp;
  return (
    <Card>
      <div style={styles.stack}>
        <div style={styles.rowBetween}>
          <h3 style={{ margin: 0 }}>Evidence</h3>
          <button type="button" style={buttonStyle()} onClick={onToggle}>{expanded ? 'Hide' : '⌄'}</button>
        </div>
        <div style={styles.evidenceHero}>
          <strong>{finding?.signal_ids.length ?? signals.length} anomaly windows</strong>
          <span style={styles.muted}>support this finding</span>
        </div>
        <div style={styles.detailGrid}>
          <span>Earliest anomaly</span><strong>{earliest ? new Date(earliest).toLocaleString() : 'n/a'}</strong>
          <span>Highest observed value</span><strong>{formatNumber(stats.peak)}</strong>
          <span>Baseline comparison</span><strong>Significantly different</strong>
          <span>Analyzer confidence</span><strong>{formatNumber(finding?.importance_score)}</strong>
        </div>
        <button type="button" style={buttonStyle()} onClick={onToggle}>View all {finding?.signal_ids.length ?? signals.length} signals</button>
        {expanded ? (
          <div style={styles.compactTable}>
            <div style={styles.tableHeader}>Window</div>
            <div style={styles.tableHeader}>Analyzer</div>
            <div style={styles.tableHeader}>Severity</div>
            <div style={styles.tableHeader}>Confidence</div>
            {signals.slice(0, 12).map((signal, index) => (
              <React.Fragment key={signal.id}>
                <div>{index + 1}</div>
                <div>{humanize(signal.signal_type)}</div>
                <div>{humanize(signal.severity)}</div>
                <div>{formatNumber(signal.confidence ?? signal.importance_score)}</div>
              </React.Fragment>
            ))}
          </div>
        ) : null}
      </div>
    </Card>
  );
}

function RecentInvestigationsTable({ caseDetails, onOpen }: { caseDetails: GrafanaCase | null; onOpen: () => void }) {
  return (
    <Card>
      <div style={styles.rowBetween}>
        <h3 style={{ margin: 0 }}>Recent investigations</h3>
        <button type="button" style={buttonStyle()}>View all cases</button>
      </div>
      <div style={styles.caseTable}>
        <div style={styles.tableHeader}>Case ID</div>
        <div style={styles.tableHeader}>Title</div>
        <div style={styles.tableHeader}>Status</div>
        <div style={styles.tableHeader}>Last updated</div>
        <div style={styles.tableHeader}>Knowledge state</div>
        {caseDetails ? (
          <button type="button" style={styles.tableRowButton} onClick={onOpen}>#{caseDetails.id}</button>
        ) : <div style={styles.muted}>-</div>}
        <div>{caseDetails?.case_title ?? 'No case created yet'}</div>
        <div>{caseDetails ? <StatusPill tone={statusTone(caseDetails.case_status)}>{humanize(caseDetails.case_status)}</StatusPill> : '-'}</div>
        <div>{formatDate(caseDetails?.updated_at)}</div>
        <div>{caseDetails ? <StatusPill tone={statusTone(caseDetails.memory_status)}>{memoryLabel(caseDetails.memory_status)}</StatusPill> : '-'}</div>
      </div>
    </Card>
  );
}

function memoryLabel(status?: string | null) {
  if (status === 'indexed') return 'Indexed';
  if (status === 'stale') return 'Needs republishing';
  if (status === 'failed') return 'Publish failed';
  if (status === 'not_indexed') return 'Not published';
  return humanize(status);
}

function InvestigationDrawer({
  open,
  caseResult,
  caseDetails,
  finding,
  result,
  backendUrl,
  onClose,
  onCaseChange,
  onError,
}: {
  open: boolean;
  caseResult: GrafanaCaseCreateResponse | null;
  caseDetails: GrafanaCase | null;
  finding: GrafanaAnalysisFinding | null;
  result: GrafanaAnalysisResult;
  backendUrl: string;
  onClose: () => void;
  onCaseChange: (caseDetails: GrafanaCase) => void;
  onError: (message: string) => void;
}) {
  const [activeStep, setActiveStep] = useState<DrawerStep>('Finding');
  const [investigationStatus, setInvestigationStatus] = useState('in_progress');
  const [investigationNote, setInvestigationNote] = useState('');
  const [rootCauseStatus, setRootCauseStatus] = useState('hypothesis');
  const [rootCauseSummary, setRootCauseSummary] = useState('');
  const [rootCauseConfidence, setRootCauseConfidence] = useState('0.6');
  const [rootCauseVerified, setRootCauseVerified] = useState(false);
  const [outcomeStatus, setOutcomeStatus] = useState('pending');
  const [outcomeSummary, setOutcomeSummary] = useState('');
  const [correctiveAction, setCorrectiveAction] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [lastSavedAt, setLastSavedAt] = useState('');

  useEffect(() => {
    if (!caseDetails) return;
    setInvestigationStatus(caseDetails.investigation_status || 'in_progress');
    setRootCauseStatus(caseDetails.root_cause_status || 'hypothesis');
    setRootCauseSummary(caseDetails.root_cause_summary ?? '');
    setRootCauseConfidence(String(caseDetails.root_cause_confidence ?? 0.6));
    setRootCauseVerified(caseDetails.root_cause_verified);
    setOutcomeStatus(caseDetails.outcome_status || 'pending');
    setOutcomeSummary(caseDetails.outcome_summary ?? '');
    setCorrectiveAction(caseDetails.corrective_action ?? '');
  }, [caseDetails]);

  if (!open) return null;

  const caseId = caseDetails?.id ?? caseResult?.case_id;
  const canSave = Boolean(caseId);

  const saveActiveStep = async () => {
    if (!caseId) return;
    setIsSaving(true);
    try {
      let updated: GrafanaCase | null = null;
      if (activeStep === 'Investigation') {
        updated = await updateCaseInvestigation(backendUrl, caseId, {
          investigation_status: investigationStatus,
          investigation_note: investigationNote.trim() || undefined,
        });
        setInvestigationNote('');
      } else if (activeStep === 'Root Cause') {
        const confidence = Number(rootCauseConfidence);
        updated = await updateCaseRca(backendUrl, caseId, {
          root_cause_status: rootCauseStatus,
          root_cause_summary: rootCauseSummary.trim() || null,
          root_cause_confidence: Number.isFinite(confidence) ? confidence : null,
          root_cause_verified: rootCauseVerified,
        });
      } else if (activeStep === 'Resolution') {
        updated = await updateCaseResolution(backendUrl, caseId, {
          outcome_status: outcomeStatus,
          outcome_summary: outcomeSummary.trim() || null,
          corrective_action: correctiveAction.trim() || null,
        });
      } else if (activeStep === 'Publish Knowledge') {
        await indexCaseMemory(backendUrl, caseId);
        updated = await getCase(backendUrl, caseId);
      }
      if (updated) {
        onCaseChange(updated);
        setLastSavedAt(new Date().toLocaleTimeString());
      }
    } catch {
      onError(`Could not save ${activeStep.toLowerCase()} update.`);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div style={styles.drawerBackdrop}>
      <aside style={styles.drawer}>
        <div style={styles.drawerHeader}>
          <div>
            <h2 style={{ margin: 0 }}>Investigation</h2>
            <p style={{ ...styles.muted, margin: '4px 0 0' }}>{caseId ? `Case #${caseId}` : 'Case not created yet'}</p>
          </div>
          <button type="button" style={buttonStyle()} onClick={onClose}>×</button>
        </div>
        <div style={styles.row}>
          <StatusPill tone={statusTone(caseDetails?.case_status)}>{humanize(caseDetails?.case_status ?? caseResult?.case_status ?? 'draft')}</StatusPill>
          <StatusPill tone={statusTone(caseDetails?.memory_status ?? caseResult?.memory_status)}>{memoryLabel(caseDetails?.memory_status ?? caseResult?.memory_status)}</StatusPill>
        </div>

        <div style={styles.stepList}>
          {steps.map((step, index) => {
            const complete =
              step === 'Finding' ||
              (step === 'Investigation' && Boolean(caseDetails?.investigation_notes.length)) ||
              (step === 'Root Cause' && Boolean(caseDetails?.root_cause_summary)) ||
              (step === 'Resolution' && Boolean(caseDetails?.corrective_action)) ||
              (step === 'Publish Knowledge' && caseDetails?.memory_status === 'indexed');
            return (
              <button key={step} type="button" style={activeStep === step ? styles.stepActive : styles.step} onClick={() => setActiveStep(step)}>
                <span style={styles.stepNumber}>{complete ? '✓' : index + 1}</span>
                <span>{step}</span>
              </button>
            );
          })}
        </div>

        <div style={styles.drawerBody}>
          {activeStep === 'Finding' ? (
            <div style={styles.stack}>
              <h3 style={{ margin: 0 }}>{finding?.title ?? 'Finding snapshot'}</h3>
              <p style={{ ...styles.muted, margin: 0 }}>{finding?.summary}</p>
              <div style={styles.detailGrid}>
                <span>Severity</span><strong>{humanize(finding?.health_status)}</strong>
                <span>Metric</span><strong>{result.metric}</strong>
                <span>Time range</span><strong>{result.from || result.to ? `${result.from} - ${result.to}` : 'Selected window'}</strong>
                <span>Importance</span><strong>{formatNumber(finding?.importance_score)}</strong>
                <span>Confidence</span><strong>{formatNumber(finding?.importance_score)}</strong>
                <span>Supporting signals</span><strong>{finding?.signal_ids.length ?? 0}</strong>
              </div>
            </div>
          ) : null}

          {activeStep === 'Investigation' ? (
            <div style={styles.stack}>
              <Field label="Investigation status">
                <select style={styles.input} value={investigationStatus} onChange={(event) => setInvestigationStatus(event.target.value)}>
                  <option value="not_started">Not started</option>
                  <option value="in_progress">In progress</option>
                  <option value="completed">Completed</option>
                </select>
              </Field>
              <Field label="Notes">
                <textarea style={{ ...styles.input, minHeight: 110 }} value={investigationNote} onChange={(event) => setInvestigationNote(event.target.value)} />
              </Field>
              {caseDetails?.investigation_notes.length ? (
                <div style={styles.stack}>
                  {caseDetails.investigation_notes.map((note, index) => (
                    <div key={`${note.timestamp ?? 'note'}-${index}`} style={styles.answerCard}>
                      <div style={styles.label}>{formatDate(note.timestamp)}</div>
                      <p style={{ margin: 0 }}>{note.note ?? JSON.stringify(note)}</p>
                    </div>
                  ))}
                </div>
              ) : <p style={styles.muted}>No investigation notes yet.</p>}
            </div>
          ) : null}

          {activeStep === 'Root Cause' ? (
            <div style={styles.stack}>
              {caseDetails?.root_cause_summary ? (
                <div style={styles.answerCard}>
                  <StatusPill tone={caseDetails.root_cause_verified ? 'success' : 'warning'}>{caseDetails.root_cause_verified ? 'Confirmed' : humanize(caseDetails.root_cause_status)}</StatusPill>
                  <p>{caseDetails.root_cause_summary}</p>
                  <div style={styles.detailGrid}>
                    <span>Confidence</span><strong>{confidenceLabel(caseDetails.root_cause_confidence)}</strong>
                    <span>Stored value</span><strong>{formatPercent(caseDetails.root_cause_confidence)}</strong>
                  </div>
                </div>
              ) : null}
              <Field label="Root cause status">
                <select style={styles.input} value={rootCauseStatus} onChange={(event) => setRootCauseStatus(event.target.value)}>
                  <option value="unknown">Unknown</option>
                  <option value="hypothesis">Hypothesis</option>
                  <option value="confirmed">Confirmed</option>
                  <option value="ruled_out">Ruled out</option>
                </select>
              </Field>
              <Field label="Root cause summary">
                <textarea style={{ ...styles.input, minHeight: 110 }} value={rootCauseSummary} onChange={(event) => setRootCauseSummary(event.target.value)} />
              </Field>
              <Field label="Confidence">
                <input style={styles.input} type="number" min="0" max="1" step="0.05" value={rootCauseConfidence} onChange={(event) => setRootCauseConfidence(event.target.value)} />
              </Field>
              <label style={styles.row}>
                <input type="checkbox" checked={rootCauseVerified} onChange={(event) => setRootCauseVerified(event.target.checked)} />
                <span>Root cause verified</span>
              </label>
            </div>
          ) : null}

          {activeStep === 'Resolution' ? (
            <div style={styles.stack}>
              {caseDetails?.corrective_action ? (
                <div style={styles.answerCard}>
                  <StatusPill tone={statusTone(caseDetails.outcome_status)}>{humanize(caseDetails.outcome_status)}</StatusPill>
                  <p><strong>Outcome:</strong> {caseDetails.outcome_summary || 'No outcome summary recorded.'}</p>
                  <p><strong>Corrective action:</strong> {caseDetails.corrective_action}</p>
                </div>
              ) : null}
              <Field label="Outcome status">
                <select style={styles.input} value={outcomeStatus} onChange={(event) => setOutcomeStatus(event.target.value)}>
                  <option value="pending">Pending</option>
                  <option value="mitigated">Mitigated</option>
                  <option value="resolved">Resolved</option>
                  <option value="won_t_fix">Won't fix</option>
                </select>
              </Field>
              <Field label="Outcome summary">
                <textarea style={{ ...styles.input, minHeight: 96 }} value={outcomeSummary} onChange={(event) => setOutcomeSummary(event.target.value)} />
              </Field>
              <Field label="Corrective action">
                <textarea style={{ ...styles.input, minHeight: 96 }} value={correctiveAction} onChange={(event) => setCorrectiveAction(event.target.value)} />
              </Field>
            </div>
          ) : null}

          {activeStep === 'Publish Knowledge' ? (
            <div style={styles.stack}>
              <StatusPill tone={statusTone(caseDetails?.memory_status)}>{memoryLabel(caseDetails?.memory_status)}</StatusPill>
              {caseDetails?.memory_status === 'stale' ? (
                <p>This case changed after it was indexed and needs to be republished.</p>
              ) : caseDetails?.memory_status === 'indexed' ? (
                <p>This investigation can be retrieved when a similar operational pattern occurs.</p>
              ) : (
                <p>This case has not been published to operational memory yet.</p>
              )}
            </div>
          ) : null}
        </div>

        <div style={styles.drawerFooter}>
          <div>
            <strong>{isSaving ? 'Saving changes...' : 'All changes saved'}</strong>
            <div style={styles.muted}>{lastSavedAt ? `Last saved ${lastSavedAt}` : 'Just now'}</div>
          </div>
          <button type="button" style={buttonStyle('primary', !canSave || isSaving)} disabled={!canSave || isSaving} onClick={saveActiveStep}>
            {activeStep === 'Publish Knowledge' ? 'Republish knowledge' : 'Save Case'}
          </button>
        </div>
      </aside>
    </div>
  );
}

export function PanelPreview({ result, backendUrl }: { result: GrafanaAnalysisResult | null; backendUrl: string }) {
  const [selectedFindingId, setSelectedFindingId] = useState<number | null>(null);
  const [questions, setQuestions] = useState<GrafanaQuestion[]>([]);
  const [questionAnswer, setQuestionAnswer] = useState<GrafanaQuestionAnswer | null>(null);
  const [caseResult, setCaseResult] = useState<GrafanaCaseCreateResponse | null>(null);
  const [caseDetails, setCaseDetails] = useState<GrafanaCase | null>(null);
  const [workflowError, setWorkflowError] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const [evidenceExpanded, setEvidenceExpanded] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const sortedFindings = useMemo(
    () => [...(result?.findings ?? [])].sort((a, b) => b.importance_score - a.importance_score),
    [result?.findings]
  );
  const selectedFinding = sortedFindings.find((finding) => finding.id === selectedFindingId) ?? sortedFindings[0] ?? null;
  const linkedSignals = selectedFinding
    ? result?.signals.filter((signal) => selectedFinding.signal_ids.includes(signal.id)) ?? []
    : [];

  useEffect(() => {
    setSelectedFindingId(sortedFindings[0]?.id ?? null);
    setQuestionAnswer(null);
    setCaseResult(null);
    setCaseDetails(null);
    setWorkflowError('');
    setDrawerOpen(false);
  }, [result?.runId, sortedFindings]);

  useEffect(() => {
    let active = true;
    setQuestions([]);
    if (!result?.runId || !result.service || !result.metric) return;
    listAvailableQuestions(backendUrl, {
      service: result.service,
      metric: result.metric,
      analysisRunId: result.runId,
    })
      .then((nextQuestions) => {
        if (active) setQuestions(nextQuestions);
      })
      .catch(() => {
        if (active) setWorkflowError('Could not load suggested questions for this analysis run.');
      });
    return () => {
      active = false;
    };
  }, [backendUrl, result?.metric, result?.runId, result?.service]);

  const createOrOpenCase = async () => {
    if (!selectedFinding) return;
    setIsBusy(true);
    setWorkflowError('');
    try {
      const createdCase = await createCaseFromFinding(backendUrl, selectedFinding.id);
      setCaseResult(createdCase);
      setCaseDetails(await getCase(backendUrl, createdCase.case_id));
      setDrawerOpen(true);
    } catch {
      setWorkflowError('Could not create an investigation case for this finding.');
    } finally {
      setIsBusy(false);
    }
  };

  if (!result) {
    return (
      <Card>
        <div style={styles.emptyHero}>
          <h2>Run analysis to open the investigation workspace</h2>
          <p>Choose a service and metric above. Results will appear as findings, timeline evidence, questions, and case workflow.</p>
        </div>
      </Card>
    );
  }

  const stats = metricStats(result, selectedFinding);

  return (
    <div style={styles.stack}>
      {workflowError ? <div style={styles.alert}>{workflowError}</div> : null}

      <Card>
        <div style={styles.summaryStrip}>
          <div style={styles.summaryItem}><span style={styles.summaryIcon}>▤</span><strong>{result.timeseries.length.toLocaleString()}</strong><span>Samples</span></div>
          <div style={styles.summaryItem}><span style={styles.summaryIcon}>⌁</span><strong>{result.signals.length}</strong><span>Signals</span></div>
          <div style={styles.summaryItem}><span style={styles.summaryIcon}>◇</span><strong>{result.findings.length}</strong><span>Findings</span></div>
          <div style={styles.summaryItem}><span style={styles.summaryIcon}>⌑</span><strong>{result.behaviorFindings.length}</strong><span>Behavior Findings</span></div>
          <details style={styles.runDetails}>
            <summary>Run details</summary>
            <div style={{ ...styles.detailGrid, marginTop: 12 }}>
              <span>Run ID</span><strong>{result.runId}</strong>
              <span>Data source</span><strong>{result.datasource}</strong>
              <span>Service</span><strong>{result.service}</strong>
              <span>Query window</span><strong>{result.from || result.to ? `${result.from} - ${result.to}` : 'Backend selected run window'}</strong>
              <span>Status</span><strong>{humanize(result.status)}</strong>
            </div>
          </details>
        </div>
      </Card>

      <div style={styles.contentGrid}>
        <main style={styles.stack}>
          <PrimaryFindingCard
            finding={selectedFinding}
            isBusy={isBusy}
            onInvestigate={() => setDrawerOpen(true)}
            onCreateCase={createOrOpenCase}
            onViewEvidence={() => setEvidenceExpanded((current) => !current)}
          />
          {sortedFindings.length > 1 ? (
            <Card>
              <div style={styles.row}>
                {sortedFindings.map((finding) => (
                  <button
                    key={finding.id}
                    type="button"
                    style={finding.id === selectedFinding?.id ? buttonStyle('primary') : buttonStyle()}
                    onClick={() => {
                      setSelectedFindingId(finding.id);
                      setQuestionAnswer(null);
                      setEvidenceExpanded(false);
                    }}
                  >
                    {finding.title}
                  </button>
                ))}
              </div>
            </Card>
          ) : null}
          <MetricTimeline result={result} selectedFinding={selectedFinding} />
          <RecentInvestigationsTable caseDetails={caseDetails} onOpen={() => setDrawerOpen(true)} />
        </main>

        <aside style={styles.stack}>
          <SuggestedQuestionsCard
            questions={questions}
            answer={questionAnswer}
            onAsk={async (question) => {
              setWorkflowError('');
              setQuestionAnswer(null);
              try {
                setQuestionAnswer(
                  await answerQuestion(backendUrl, {
                    questionId: question.id,
                    service: result.service,
                    metric: result.metric,
                    analysisRunId: result.runId,
                  })
                );
              } catch {
                setWorkflowError('Could not answer the selected investigation question.');
              }
            }}
          />
          <EvidenceSummaryCard
            result={result}
            finding={selectedFinding}
            signals={linkedSignals.length ? linkedSignals : result.signals}
            expanded={evidenceExpanded}
            onToggle={() => setEvidenceExpanded((current) => !current)}
          />
          <Card>
            <div style={styles.detailGrid}>
              <span>Current</span><strong>{formatNumber(stats.current)}</strong>
              <span>Peak</span><strong>{formatNumber(stats.peak)}</strong>
              <span>Finding category</span><strong>{humanize(selectedFinding?.category)}</strong>
            </div>
          </Card>
        </aside>
      </div>

      <InvestigationDrawer
        open={drawerOpen}
        caseResult={caseResult}
        caseDetails={caseDetails}
        finding={selectedFinding}
        result={result}
        backendUrl={backendUrl}
        onClose={() => setDrawerOpen(false)}
        onCaseChange={setCaseDetails}
        onError={setWorkflowError}
      />
    </div>
  );
}
