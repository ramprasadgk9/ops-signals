import React, { useEffect, useMemo, useState } from 'react';
import {
  askAssistantWithMemory,
  answerQuestion,
  createCaseFromFinding,
  getCase,
  indexCaseMemory,
  listCases,
  listAvailableQuestions,
  resetTestingOperationalData,
  updateCaseInvestigation,
  updateCaseRca,
  updateCaseResolution,
} from './backendClient';
import { Card, Chip, Field, styles } from './plainUi';
import { PluginBehaviorFindings } from './PluginBehaviorFindings';
import { PluginFindingTrust } from './PluginFindingTrust';
import { PluginSameFix } from './PluginSameFix';
import { PluginSeenBefore } from './PluginSeenBefore';
import type {
  GrafanaAnalysisFinding,
  GrafanaAnalysisResult,
  GrafanaAnalysisSignal,
  GrafanaCase,
  GrafanaCaseCreateResponse,
  GrafanaQuestion,
  GrafanaQuestionAnswer,
} from './contracts';
import type { AssistantChatResponse } from '../types';
import { findingLevel } from '../utils/findingLevel';

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

function truncateId(value: string, visibleChars = 8) {
  return value.length > visibleChars + 1 ? `${value.slice(0, visibleChars)}…` : value;
}

function formatDate(value?: string | null) {
  if (!value) return 'n/a';
  return new Date(value).toLocaleString();
}

function formatAxisTimestamp(value?: string | null, spanMs?: number) {
  if (!value) return 'n/a';
  const date = new Date(value);
  if (spanMs != null && spanMs <= 6 * 60 * 60 * 1000) {
    return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  }
  return date.toLocaleString([], { month: 'numeric', day: 'numeric', hour: 'numeric', minute: '2-digit' });
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
    signalWindows: selectedFinding?.signal_ids.length ?? result.signals.length,
  };
}

function signalsForFinding(result: GrafanaAnalysisResult, selectedFinding: GrafanaAnalysisFinding | null) {
  if (!selectedFinding?.signal_ids.length) return result.signals;
  const ids = new Set(selectedFinding.signal_ids);
  return result.signals.filter((signal) => ids.has(signal.id));
}

type AnalyzerRow = {
  id: string;
  displayName: string;
  finalScore: number;
  executed: boolean;
  statusLabel: string;
  reason: string | null;
  tone: 'success' | 'warning' | 'danger' | 'neutral';
};

// One row per router candidate, merging the router's own recommendation/score with what
// actually happened at execution time. This is the single source of truth for analyzer-routing
// display - it used to be duplicated as three separate, largely-overlapping renderings in
// AnalyzerRoutingSummary alone (a plain-text execution-status dump, four recommendation-bucket
// chip rows, and a third "why rejected" pass), plus a fourth near-copy in PrimaryFindingCard's
// no-finding branch. All of those now build off this one function and share <AnalyzerRowsList>.
function buildAnalyzerRows(result: GrafanaAnalysisResult): AnalyzerRow[] {
  const routing = result.analyzerRouting ?? [];
  const executions = result.analyzerExecutions ?? [];
  const executionById = new Map(executions.map((item) => [item.router_analyzer_id, item]));
  return routing.map((item) => {
    const execution = executionById.get(item.analyzer_id);
    const executed = execution?.execution_status === 'completed';
    const tone: AnalyzerRow['tone'] =
      executed || item.recommendation === 'RECOMMENDED'
        ? 'success'
        : item.recommendation === 'OPTIONAL'
        ? 'warning'
        : item.recommendation === 'REJECTED'
        ? 'danger'
        : 'neutral';
    const reason =
      execution?.execution_reason ||
      [...(item.reasons ?? []), ...(item.warnings ?? [])].slice(0, 2).join(' ') ||
      null;
    return {
      id: item.analyzer_id,
      displayName: item.display_name,
      finalScore: item.final_score,
      executed,
      statusLabel: executed ? 'Executed' : humanize(item.recommendation),
      reason,
      tone,
    };
  });
}

function AnalyzerRowLine({ row }: { row: AnalyzerRow }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', padding: '4px 0' }}>
      <StatusPill tone={row.tone}>{row.statusLabel}</StatusPill>
      <strong>{row.displayName}</strong>
      <span style={styles.muted}>{formatNumber(row.finalScore)}</span>
      {row.reason ? <span style={styles.muted}>· {row.reason}</span> : null}
    </div>
  );
}

function AnalyzerRowsList({ rows, emptyExecutedLabel }: { rows: AnalyzerRow[]; emptyExecutedLabel: string }) {
  const [showOtherAnalyzers, setShowOtherAnalyzers] = useState(false);
  if (!rows.length) return null;
  const executedRows = rows.filter((row) => row.executed);
  const otherRows = rows.filter((row) => !row.executed);
  return (
    <div style={styles.stack}>
      <span style={styles.label}>
        Analyzers considered ({executedRows.length} executed of {rows.length})
      </span>
      {executedRows.length ? (
        executedRows.map((row) => <AnalyzerRowLine key={row.id} row={row} />)
      ) : (
        <span style={styles.muted}>{emptyExecutedLabel}</span>
      )}
      {otherRows.length ? (
        <>
          <button
            type="button"
            style={{ ...buttonStyle(), alignSelf: 'flex-start', marginTop: 6 }}
            onClick={() => setShowOtherAnalyzers((current) => !current)}
          >
            {showOtherAnalyzers ? 'Hide other analyzers' : `Show ${otherRows.length} other analyzer${otherRows.length === 1 ? '' : 's'} considered`}
          </button>
          {showOtherAnalyzers ? (
            <div style={{ marginTop: 4 }}>
              {otherRows.map((row) => (
                <AnalyzerRowLine key={row.id} row={row} />
              ))}
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function AnalyzerRoutingSummary({ result }: { result: GrafanaAnalysisResult }) {
  const routing = result.analyzerRouting ?? [];
  const rows = buildAnalyzerRows(result);
  // Fallback for older backends that only ever returned the flat executed-name list, with no
  // router metadata to build a merged row from.
  const executedFallback = routing.length === 0 ? result.executedAnalyzers ?? [] : [];

  return (
    <div style={{ ...styles.stack, marginTop: 14, paddingTop: 14, borderTop: '1px solid rgba(204, 204, 220, 0.14)' }}>
      {routing.length === 0 ? (
        <div style={styles.infoNote}>
          Analyzer router metadata was not returned for this run. Restart the backend and refresh the Grafana plugin bundle to show recommended, optional, not recommended, and rejected analyzers.
        </div>
      ) : null}
      <div style={styles.detailGrid}>
        <span>Prometheus source</span><strong>{result.datasourceUid ? `${result.datasource} (${result.datasourceUid})` : result.datasource}</strong>
        <span>Selection mode</span><strong>{humanize(result.analyzerSelectionMode ?? 'all')}</strong>
      </div>
      {executedFallback.length ? (
        <div style={styles.stack}>
          <span style={styles.label}>Executed analyzers</span>
          <div style={styles.row}>
            {executedFallback.map((item) => (
              <StatusPill key={item} tone="success">{humanize(item)}</StatusPill>
            ))}
          </div>
        </div>
      ) : null}
      <AnalyzerRowsList rows={rows} emptyExecutedLabel="None of the router's candidates executed for this run." />
    </div>
  );
}

function questionIdForPrompt(prompt: string) {
  const normalized = prompt.toLowerCase();
  if (normalized.includes('root cause') || normalized.includes('rca')) return 'baseline_changes';
  if (normalized.includes('investigate') || normalized.includes('first') || normalized.includes('priority')) return 'investigation_priority';
  if (normalized.includes('unusual') || normalized.includes('detected') || normalized.includes('happen')) return 'unusual_activity';
  if (normalized.includes('trend') || normalized.includes('increase') || normalized.includes('decrease')) return 'long_term_trends';
  if (normalized.includes('health') || normalized.includes('healthy')) return 'service_health';
  if (normalized.includes('new') || normalized.includes('expected') || normalized.includes('normal')) return 'behavior_novelty';
  return 'what_changed';
}

function isAnalyzerRoutingPrompt(prompt: string) {
  const normalized = prompt.toLowerCase();
  return (
    normalized.includes('analyzer') ||
    normalized.includes('recommended') ||
    normalized.includes('optional') ||
    normalized.includes('rejected') ||
    normalized.includes('why did') ||
    normalized.includes('why didn') ||
    normalized.includes('which') && normalized.includes('ran') ||
    ['ruptures', 'stumpy', 'prophet', 'river', 'kats', 'darts', 'alibi', 'trend regression', 'adtk', 'pyod'].some((name) => normalized.includes(name))
  );
}

function analyzerNameFromPrompt(prompt: string) {
  const normalized = prompt.toLowerCase();
  const aliases = [
    ['ruptures', 'ruptures'],
    ['stumpy', 'stumpy'],
    ['prophet', 'prophet'],
    ['river', 'river'],
    ['kats', 'kats'],
    ['darts', 'darts'],
    ['alibi', 'alibi_detect'],
    ['trend regression', 'trend_regression'],
    ['trend', 'trend_regression'],
    ['adtk', 'adtk'],
    ['pyod', 'pyod'],
  ];
  return aliases.find(([label]) => normalized.includes(label))?.[1] ?? null;
}

function localAssistantAnswer(
  prompt: string,
  result: GrafanaAnalysisResult,
  finding: GrafanaAnalysisFinding | null,
  signals: GrafanaAnalysisSignal[]
): GrafanaQuestionAnswer {
  const routing = result.analyzerRouting ?? [];
  const recommended = routing.filter((item) => item.recommendation === 'RECOMMENDED');
  const optional = routing.filter((item) => item.recommendation === 'OPTIONAL');
  const rejected = routing.filter((item) => item.recommendation === 'REJECTED');
  const executed = result.executedAnalyzers ?? [];
  const stats = metricStats(result, finding);
  const sampleCount = result.sampleCount ?? result.timeseries.length;
  const rejectedReason = rejected[0] ? [...(rejected[0].reasons ?? []), ...(rejected[0].warnings ?? [])][0] : '';
  const normalized = prompt.toLowerCase();
  const requestedAnalyzer = analyzerNameFromPrompt(prompt);
  const requestedDecision = requestedAnalyzer
    ? routing.find((item) => item.analyzer_id === requestedAnalyzer || item.display_name.toLowerCase().includes(requestedAnalyzer.replace('_', ' ')))
    : null;

  let headline = 'Current investigation summary';
  let answer = `${result.metric} for ${result.service} returned ${sampleCount.toLocaleString()} Prometheus samples. `;
  if (finding) {
    answer += `The top finding is "${finding.title}" with importance ${formatNumber(finding.importance_score)}. `;
  } else {
    answer += 'No operational finding was emitted for this run. ';
  }

  if (isAnalyzerRoutingPrompt(prompt)) {
    headline = requestedDecision ? `${requestedDecision.display_name} routing explanation` : 'Analyzer routing summary';
    answer += `Selection mode is ${humanize(result.analyzerSelectionMode ?? 'all')}. `;
    if (requestedDecision) {
      const concreteRan = executed.includes(requestedDecision.analyzer_id);
      const mappedRan =
        requestedDecision.analyzer_id === 'ruptures'
          ? executed.some((item) => item === 'ruptures' || item === 'baseline_shift')
          : requestedDecision.analyzer_id === 'trend_regression'
            ? executed.includes('trend')
            : requestedDecision.analyzer_id === 'adtk' || requestedDecision.analyzer_id === 'pyod'
              ? executed.includes('anomaly_zscore')
              : concreteRan;
      const reasons = [...(requestedDecision.reasons ?? []), ...(requestedDecision.warnings ?? [])].slice(0, 3);
      answer += `${requestedDecision.display_name} was ${requestedDecision.recommendation.toLowerCase().replace(/_/g, ' ')} with score ${requestedDecision.final_score.toFixed(2)}. `;
      answer += mappedRan
        ? `It ran because recommended-only mode allowed it or one of its mapped pipeline analyzers. `
        : `It did not run because recommended-only mode only executes router decisions marked RECOMMENDED. `;
      if (reasons.length) answer += `Reason: ${reasons.join(' ')}`;
    } else {
      answer += `Executed analyzers: ${executed.length ? executed.map(humanize).join(', ') : 'none'}. `;
      answer += `Recommended: ${recommended.length ? recommended.map((item) => `${item.display_name} ${item.final_score.toFixed(2)}`).join(', ') : 'none'}. `;
      answer += `Optional: ${optional.length ? optional.map((item) => `${item.display_name} ${item.final_score.toFixed(2)}`).join(', ') : 'none'}. `;
      if (!executed.length && rejectedReason) answer += `The first rejection reason is: ${rejectedReason}`;
    }
  } else if (normalized.includes('root cause') || normalized.includes('rca')) {
    headline = 'Likely root-cause direction';
    answer += signals.length
      ? `Start from the emitted signals: ${signals.slice(0, 3).map((signal) => `${humanize(signal.analyzer_id)} reported ${humanize(signal.severity)}`).join('; ')}.`
      : 'No root cause can be claimed yet because no analyzer emitted a signal. Check sample count, router eligibility, and whether the selected window contains a visible change.';
  } else if (normalized.includes('next') || normalized.includes('investigate') || normalized.includes('first')) {
    headline = 'What to investigate first';
    answer += signals.length
      ? 'Start with the highest-confidence signal, then compare the selected time window with deployment, traffic, and infrastructure change events.'
      : 'First confirm enough samples were collected, then rerun with a 15-30 minute window and inspect router eligibility reasons.';
  } else {
    answer += `Current value is ${formatNumber(stats.current)}, average is ${formatNumber(stats.average)}, and peak is ${formatNumber(stats.peak)}. `;
    answer += recommended.length
      ? `The router currently recommends ${recommended.map((item) => item.display_name).join(', ')}.`
      : 'The router did not recommend an analyzer strongly enough for execution in recommended-only mode.';
  }

  return {
    question_id: questionIdForPrompt(prompt),
    headline,
    answer,
    status: 'answered_from_run_context',
    priority: finding ? 'medium' : 'low',
    confidence: signals.length || routing.length ? 0.74 : 0.5,
    key_points: [
      `${sampleCount.toLocaleString()} samples returned`,
      `${signals.length} signals emitted`,
      `${recommended.length} analyzers recommended`,
      `${executed.length} analyzers executed`,
    ],
    evidence_signal_ids: signals.map((signal) => signal.id),
  };
}

function assistantChatToQuestionAnswer(response: AssistantChatResponse): GrafanaQuestionAnswer {
  return {
    question_id: response.intent,
    headline: response.intent === 'historical' ? 'Memory-backed answer' : 'Assistant answer',
    answer: response.answer,
    status: `assistant_${response.intent}`,
    priority: response.sources.length ? 'medium' : 'low',
    confidence: response.sources.length ? Math.min(0.95, Math.max(0.55, response.sources[0].score)) : 0.5,
    key_points: response.sources.length
      ? response.sources.slice(0, 4).map((source) => `${source.source_type}: ${source.title}${source.section ? ` > ${source.section}` : ''} (${source.score.toFixed(2)})`)
      : response.limitations.slice(0, 3),
    evidence_signal_ids: [],
  };
}

function buildAssistantMemoryPrompt(
  prompt: string,
  result: GrafanaAnalysisResult,
  finding: GrafanaAnalysisFinding | null,
  signals: GrafanaAnalysisSignal[]
) {
  const routing = result.analyzerRouting ?? [];
  return [
    `User question: ${prompt}`,
    "",
    "Current Grafana run context:",
    `analysis_run_id: ${result.runId}`,
    `service: ${result.service}`,
    `metric_name: ${result.metric}`,
    `time_window: ${result.from} - ${result.to}`,
    `sample_count: ${result.sampleCount ?? result.timeseries.length}`,
    `selection_mode: ${result.analyzerSelectionMode ?? 'all'}`,
    `executed_analyzers: ${(result.executedAnalyzers ?? []).join(', ') || 'none'}`,
    `router_recommended: ${routing.filter((item) => item.recommendation === 'RECOMMENDED').map((item) => `${item.display_name} ${item.final_score.toFixed(2)}`).join(', ') || 'none'}`,
    `router_optional: ${routing.filter((item) => item.recommendation === 'OPTIONAL').map((item) => `${item.display_name} ${item.final_score.toFixed(2)}`).join(', ') || 'none'}`,
    `top_finding: ${finding ? `${finding.title} - ${finding.summary}` : 'none'}`,
    `signals: ${signals.length ? signals.slice(0, 5).map((signal) => `${signal.analyzer_id}:${signal.severity}:${signal.summary}`).join(' | ') : 'none'}`,
    "",
    "Answer using current run evidence first. Include historical/vector memory context only when relevant.",
  ].join("\n");
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
  const findingSignals = signalsForFinding(result, selectedFinding).filter((signal) => signal.start_time && signal.end_time);
  const firstTs = points[0] ? new Date(points[0].timestamp).getTime() : 0;
  const lastTs = points[points.length - 1] ? new Date(points[points.length - 1].timestamp).getTime() : firstTs;
  const spanMs = Math.max(1, lastTs - firstTs);
  const averageY = height - padding - (((stats.average ?? min) - min) / range) * (height - padding * 2);

  const path = sampledPoints
    .map((point, index) => {
      const x = padding + (index / Math.max(1, sampledPoints.length - 1)) * (width - padding * 2);
      const y = height - padding - ((point.value - min) / range) * (height - padding * 2);
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(' ');

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
          <div><span style={styles.label}>Signal windows</span><strong>{stats.signalWindows}</strong></div>
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
            {findingSignals.slice(0, 16).map((signal) => {
              const start = new Date(signal.start_time as string).getTime();
              const end = new Date(signal.end_time as string).getTime();
              const x1 = padding + ((Math.max(firstTs, start) - firstTs) / spanMs) * (width - padding * 2);
              const x2 = padding + ((Math.min(lastTs, end) - firstTs) / spanMs) * (width - padding * 2);
              const rectWidth = Math.max(4, x2 - x1);
              return (
                <rect key={signal.id} x={x1} y={padding} width={rectWidth} height={height - padding * 2} fill="rgba(242, 73, 92, 0.18)">
                  <title>{`${humanize(signal.analyzer_id)} ${humanize(signal.signal_type)} · ${formatDate(signal.start_time)} - ${formatDate(signal.end_time)} · confidence ${formatNumber(signal.confidence ?? signal.importance_score)}`}</title>
                </rect>
              );
            })}
            <line x1={padding} x2={width - padding} y1={averageY} y2={averageY} stroke="rgba(204, 204, 220, 0.45)" strokeDasharray="6 6" />
            <path d={path} fill="none" stroke="#5794f2" strokeWidth="3" />
            <text x={padding} y={height - 10} fill="rgba(204, 204, 220, 0.72)" fontSize="12">{formatAxisTimestamp(points[0].timestamp, spanMs)}</text>
            <text x={width - padding} y={height - 10} fill="rgba(204, 204, 220, 0.72)" fontSize="12" textAnchor="end">{formatAxisTimestamp(points[points.length - 1].timestamp, spanMs)}</text>
          </svg>
        )}
        <div style={styles.row}>
          <StatusPill>Observed {result.metric}</StatusPill>
          <StatusPill>Current-window average</StatusPill>
          <StatusPill tone="danger">Signal window</StatusPill>
        </div>
        {points[0]?.timestamp?.startsWith('2014-') ? (
          <div style={styles.infoNote}>Sample dataset: February 14-28, 2014</div>
        ) : null}
      </div>
    </Card>
  );
}

function PrimaryFindingCard({
  result,
  backendUrl,
  finding,
  onInvestigate,
  onCreateCase,
  onViewEvidence,
  isBusy,
}: {
  result: GrafanaAnalysisResult;
  backendUrl: string;
  finding: GrafanaAnalysisFinding | null;
  onInvestigate: () => void;
  onCreateCase: () => void;
  onViewEvidence: () => void;
  isBusy: boolean;
}) {
  if (!finding) {
    const routing = result.analyzerRouting ?? [];
    const rows = buildAnalyzerRows(result);
    return (
      <Card>
        <div style={styles.stack}>
          <div style={styles.rowBetween}>
            <div>
              <h2 style={{ margin: 0 }}>No operational finding detected</h2>
              <p style={{ ...styles.muted, margin: '6px 0 0' }}>
                Prometheus returned {result.sampleCount?.toLocaleString() ?? result.timeseries.length.toLocaleString()} samples for {result.metric}; the executed analyzers did not emit problem signals.
              </p>
            </div>
            <StatusPill tone="success">{humanize(result.status).toUpperCase()}</StatusPill>
          </div>
          <div style={styles.detailGrid}>
            <span>Prometheus datasource</span><strong>{result.datasourceUid ? `${result.datasource} (${result.datasourceUid})` : result.datasource}</strong>
            <span>Selection mode</span><strong>{humanize(result.analyzerSelectionMode ?? 'all')}</strong>
          </div>
          <AnalyzerRowsList rows={rows} emptyExecutedLabel="None of the router's candidates executed for this run." />
          {routing.length === 0 ? (
            <div style={styles.infoNote}>
              Analyzer router metadata was not returned for this run. Restart the backend and refresh Grafana to show the full testing-phase routing table.
            </div>
          ) : null}
        </div>
      </Card>
    );
  }

  return (
    <div style={styles.primaryFinding}>
      <div style={styles.findingIcon}>⌁</div>
      <div style={styles.stack}>
        <div style={styles.rowBetween}>
          <StatusPill tone={({ error: 'danger', warning: 'warning', default: 'neutral' } as const)[findingLevel(finding.health_status).chip]}>{`${findingLevel(finding.health_status).label} importance`.toUpperCase()}</StatusPill>
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
        <PluginFindingTrust backendUrl={backendUrl} findingId={finding.id} trust={finding.trust} service={result.service} />
      </div>
    </div>
  );
}

function AskOpsSignalsCard({
  result,
  finding,
  signals,
  questions,
  answer,
  isBusy,
  onAsk,
}: {
  result: GrafanaAnalysisResult;
  finding: GrafanaAnalysisFinding | null;
  signals: GrafanaAnalysisSignal[];
  questions: GrafanaQuestion[];
  answer: GrafanaQuestionAnswer | null;
  isBusy: boolean;
  onAsk: (prompt: string) => void;
}) {
  const [prompt, setPrompt] = useState('');
  const suggestedPrompts = [
    'Summarize this investigation',
    'Why was this detected?',
    'What is the root cause?',
    'What should I investigate first?',
    'Which analyzers ran?',
  ];
  const visibleQuestions = questions.slice(0, 2);
  const ask = (nextPrompt: string) => {
    const trimmed = nextPrompt.trim();
    if (!trimmed) return;
    onAsk(trimmed);
    setPrompt('');
  };

  return (
    <Card>
      <div style={styles.stack}>
        <div style={styles.rowBetween}>
          <div>
            <h3 style={{ margin: 0 }}>Ask Ops Signals</h3>
            <p style={{ ...styles.muted, margin: '4px 0 0' }}>Grounded in this run, router decisions, signals, and case context.</p>
          </div>
          <StatusPill>Beta</StatusPill>
        </div>
        <div style={styles.infoNote}>
          Ask about this {finding ? 'finding' : 'run'}, analyzer routing, evidence, or next investigation step.
          <div style={{ ...styles.detailGrid, marginTop: 10 }}>
            <span>Run</span><strong>{result.runId.slice(0, 8)}</strong>
            <span>Signals</span><strong>{signals.length}</strong>
            <span>Selection mode</span><strong>{humanize(result.analyzerSelectionMode ?? 'all')}</strong>
          </div>
        </div>
        <div style={styles.row}>
          {suggestedPrompts.map((item) => (
            <button key={item} type="button" style={{ ...styles.chip, background: 'transparent', color: 'inherit', cursor: isBusy ? 'not-allowed' : 'pointer' }} disabled={isBusy} onClick={() => ask(item)}>
              {item}
            </button>
          ))}
        </div>
        {visibleQuestions.length ? (
          <div style={styles.stack}>
            <span style={styles.label}>Evidence-backed catalog questions</span>
            {visibleQuestions.map((question) => (
              <button key={question.id} type="button" style={styles.questionButton} disabled={isBusy || !question.available} onClick={() => ask(question.label)}>
                <span>◌</span>
                <span>{question.label}</span>
              </button>
            ))}
          </div>
        ) : null}
        <div style={styles.row}>
          <input
            style={{ ...styles.input, flex: 1 }}
            value={prompt}
            placeholder="Ask anything about this run..."
            onChange={(event) => setPrompt(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') ask(prompt);
            }}
          />
          <button type="button" style={buttonStyle('primary', isBusy)} disabled={isBusy} onClick={() => ask(prompt)}>
            {isBusy ? 'Asking...' : 'Ask'}
          </button>
        </div>
        {answer ? (
          <div style={styles.answerCard}>
            <div style={styles.row}>
              <StatusPill>{humanize(answer.status)}</StatusPill>
              <StatusPill>Priority: {humanize(answer.priority)}</StatusPill>
              <StatusPill>Confidence: {formatPercent(answer.confidence)}</StatusPill>
            </div>
            <h4 style={{ margin: '4px 0' }}>{answer.headline}</h4>
            <p style={{ margin: 0 }}>{answer.answer}</p>
            {answer.key_points.length ? (
              <div style={styles.infoNote}>
                Evidence: {answer.key_points.slice(0, 4).join(' | ')}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </Card>
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
  const findingSignals = signalsForFinding(result, finding);
  const datedSignals = findingSignals.filter((signal) => signal.start_time);
  const earliest = datedSignals
    .map((signal) => signal.start_time as string)
    .sort((left, right) => new Date(left).getTime() - new Date(right).getTime())[0];
  const comparisonType = finding?.comparison_json?.comparison_label ?? 'selected time window';
  return (
    <Card>
      <div style={styles.stack}>
        <div style={styles.rowBetween}>
          <h3 style={{ margin: 0 }}>Evidence</h3>
          <button type="button" style={buttonStyle()} onClick={onToggle}>{expanded ? 'Hide' : '⌄'}</button>
        </div>
        <div style={styles.evidenceHero}>
          <strong>{finding?.signal_ids.length ?? signals.length} signal windows</strong>
          <span style={styles.muted}>support this finding</span>
        </div>
        <div style={styles.detailGrid}>
          <span>Earliest signal</span><strong>{earliest ? new Date(earliest).toLocaleString() : 'n/a'}</strong>
          <span>Highest observed value</span><strong>{formatNumber(stats.peak)}</strong>
          <span>Reference comparison</span><strong>{String(comparisonType)}</strong>
          <span>Analyzer confidence</span><strong>{formatNumber(findingSignals[0]?.confidence ?? finding?.importance_score)}</strong>
        </div>
        <button type="button" style={buttonStyle()} onClick={onToggle}>View all {finding?.signal_ids.length ?? signals.length} signals</button>
        {expanded ? (
          <div style={styles.compactTable}>
            <div style={styles.tableHeader}>Window</div>
            <div style={styles.tableHeader}>Analyzer</div>
            <div style={styles.tableHeader}>Severity</div>
            <div style={styles.tableHeader}>Confidence</div>
            {findingSignals.slice(0, 12).map((signal) => (
              <React.Fragment key={signal.id}>
                <div>{signal.start_time ? `${formatAxisTimestamp(signal.start_time)} - ${formatAxisTimestamp(signal.end_time)}` : signal.id.slice(0, 8)}</div>
                <div>{humanize(signal.analyzer_id || signal.signal_type)}</div>
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

function RecentInvestigationsTable({
  caseDetails,
  onOpenCase,
  onViewAllCases,
}: {
  caseDetails: GrafanaCase | null;
  onOpenCase: () => void;
  onViewAllCases: () => void;
}) {
  return (
    <Card>
      <div style={styles.rowBetween}>
        <h3 style={{ margin: 0 }}>Recent investigations</h3>
        <button type="button" style={buttonStyle()} onClick={onViewAllCases}>View all cases</button>
      </div>
      <div style={styles.caseTable}>
        <div style={styles.tableHeader}>Case ID</div>
        <div style={styles.tableHeader}>Title</div>
        <div style={styles.tableHeader}>Status</div>
        <div style={styles.tableHeader}>Last updated</div>
        <div style={styles.tableHeader}>Knowledge state</div>
        {caseDetails ? (
          <button type="button" style={styles.tableRowButton} onClick={onOpenCase}>#{caseDetails.id}</button>
        ) : <div style={styles.muted}>-</div>}
        <div>{caseDetails?.case_title ?? 'No case created yet'}</div>
        <div>{caseDetails ? <StatusPill tone={statusTone(caseDetails.case_status)}>{humanize(caseDetails.case_status)}</StatusPill> : '-'}</div>
        <div>{formatDate(caseDetails?.updated_at)}</div>
        <div>{caseDetails ? <StatusPill tone={statusTone(caseDetails.memory_status)}>{memoryLabel(caseDetails.memory_status)}</StatusPill> : '-'}</div>
      </div>
    </Card>
  );
}

function CasesDrawer({
  open,
  cases,
  isLoading,
  onClose,
  onOpenCase,
}: {
  open: boolean;
  cases: GrafanaCase[];
  isLoading: boolean;
  onClose: () => void;
  onOpenCase: (caseItem: GrafanaCase) => void;
}) {
  if (!open) return null;
  return (
    <div style={styles.drawerBackdrop}>
      <aside style={styles.drawer}>
        <div style={styles.drawerHeader}>
          <div>
            <h2 style={{ margin: 0 }}>Recent Cases</h2>
            <p style={{ ...styles.muted, margin: '4px 0 0' }}>Saved investigations for the current service and metric.</p>
          </div>
          <button type="button" style={buttonStyle()} onClick={onClose}>×</button>
        </div>
        <div style={styles.drawerBody}>
          {isLoading ? (
            <p style={styles.muted}>Loading cases...</p>
          ) : cases.length === 0 ? (
            <p style={styles.muted}>No cases were found for this service and metric yet.</p>
          ) : (
            <div style={styles.stack}>
              {cases.map((caseItem) => (
                <div key={caseItem.id} style={styles.answerCard}>
                  <div style={styles.rowBetween}>
                    <strong>#{caseItem.id} {caseItem.case_title}</strong>
                    <StatusPill tone={statusTone(caseItem.case_status)}>{humanize(caseItem.case_status)}</StatusPill>
                  </div>
                  <div style={{ ...styles.detailGrid, marginTop: 10 }}>
                    <span>Updated</span><strong>{formatDate(caseItem.updated_at)}</strong>
                    <span>Knowledge</span><strong>{memoryLabel(caseItem.memory_status)}</strong>
                  </div>
                  <div style={{ marginTop: 12 }}>
                    <button type="button" style={buttonStyle('primary')} onClick={() => onOpenCase(caseItem)}>Open case</button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

function memoryLabel(status?: string | null) {
  if (status === 'indexed') return 'Indexed';
  if (status === 'stale') return 'Needs republishing';
  if (status === 'failed') return 'Publish failed';
  if (status === 'not_indexed') return 'Not published';
  return humanize(status);
}

/** The finding a case was opened from, rebuilt from the case's stored snapshot, for when the
 * drawer is opened from case history rather than from a finding in the current run. */
export function caseSnapshotFinding(caseDetails: GrafanaCase | null): GrafanaAnalysisFinding | null {
  const snapshot = caseDetails?.finding_snapshot;
  if (!caseDetails || !snapshot) return null;
  const text = (value: unknown) => (typeof value === 'string' ? value : '');
  return {
    id: typeof snapshot.id === 'number' ? snapshot.id : caseDetails.finding_id,
    title: text(snapshot.title) || caseDetails.case_title,
    summary: text(snapshot.summary),
    category: text(snapshot.category),
    health_status: text(snapshot.health_status),
    importance_score: typeof snapshot.importance_score === 'number' ? snapshot.importance_score : 0,
    investigation_priority: typeof snapshot.investigation_priority === 'number' ? snapshot.investigation_priority : 0,
    signal_ids: Array.isArray(snapshot.signal_ids) ? snapshot.signal_ids.map(String) : [],
  };
}

/** The case workflow (Finding → Publish Knowledge). Opened from a finding in the current run, it is
 * given that run's `result`; opened from case history there is no run, so `result` is omitted and
 * the Finding step reads the case's stored snapshot instead. */
export function InvestigationDrawer({
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
  result?: GrafanaAnalysisResult | null;
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
  const [learningOutcomeStatus, setLearningOutcomeStatus] = useState('');
  const [rootCauseCategory, setRootCauseCategory] = useState('');
  const [resolutionSummary, setResolutionSummary] = useState('');
  const [outcomeSummary, setOutcomeSummary] = useState('');
  const [correctiveAction, setCorrectiveAction] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [lastSavedAt, setLastSavedAt] = useState('');
  const [saveError, setSaveError] = useState('');

  useEffect(() => {
    if (!caseDetails) return;
    setInvestigationStatus(caseDetails.investigation_status || 'in_progress');
    setRootCauseStatus(caseDetails.root_cause_status || 'hypothesis');
    setRootCauseSummary(caseDetails.root_cause_summary ?? '');
    setRootCauseConfidence(String(caseDetails.root_cause_confidence ?? 0.6));
    setRootCauseVerified(caseDetails.root_cause_verified);
    setOutcomeStatus(caseDetails.outcome_status || 'pending');
    setLearningOutcomeStatus('');
    setRootCauseCategory('');
    setResolutionSummary('');
    setOutcomeSummary(caseDetails.outcome_summary ?? '');
    setCorrectiveAction(caseDetails.corrective_action ?? '');
  }, [caseDetails]);

  if (!open) return null;

  const caseId = caseDetails?.id ?? caseResult?.case_id;
  const shownFinding = finding ?? caseSnapshotFinding(caseDetails);
  const snapshotMetric = caseDetails?.finding_snapshot?.metric_name;
  const snapshotService = caseDetails?.finding_snapshot?.service;
  const canSave = Boolean(caseId);

  const saveActiveStep = async () => {
    if (!caseId) return;
    setIsSaving(true);
    setSaveError('');
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
          learning_outcome_status: learningOutcomeStatus || null,
          root_cause_category: rootCauseCategory.trim() || null,
          resolution_summary: resolutionSummary.trim() || outcomeSummary.trim() || null,
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
      const message = `Could not save ${activeStep.toLowerCase()} update.`;
      setSaveError(message);
      onError(message);
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
              <h3 style={{ margin: 0 }}>{shownFinding?.title ?? 'Finding snapshot'}</h3>
              <p style={{ ...styles.muted, margin: 0 }}>{shownFinding?.summary}</p>
              <div style={styles.detailGrid}>
                <span>Importance</span><strong>{findingLevel(shownFinding?.health_status).label}</strong>
                {result ? (
                  <>
                    <span>Metric</span><strong>{result.metric}</strong>
                    <span>Time range</span><strong>{result.from || result.to ? `${result.from} - ${result.to}` : 'Selected window'}</strong>
                  </>
                ) : (
                  <>
                    <span>Service</span><strong>{typeof snapshotService === 'string' && snapshotService ? snapshotService : '-'}</strong>
                    <span>Metric</span><strong>{typeof snapshotMetric === 'string' && snapshotMetric ? snapshotMetric : '-'}</strong>
                    <span>Case opened</span><strong>{formatDate(caseDetails?.created_at)}</strong>
                  </>
                )}
                <span>Importance</span><strong>{formatNumber(shownFinding?.importance_score)}</strong>
                <span>Confidence</span><strong>{formatNumber(shownFinding?.importance_score)}</strong>
                <span>Supporting signals</span><strong>{shownFinding?.signal_ids.length ?? 0}</strong>
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
              <Field label="Did the original finding help explain the issue?">
                <select style={styles.input} value={learningOutcomeStatus} onChange={(event) => setLearningOutcomeStatus(event.target.value)}>
                  <option value="">Select when resolving or closing</option>
                  <option value="confirmed">Yes, it was confirmed</option>
                  <option value="partially_confirmed">Partially</option>
                  <option value="rejected">No, it was incorrect</option>
                  <option value="inconclusive">Could not determine</option>
                </select>
              </Field>
              <Field label="Outcome summary">
                <textarea style={{ ...styles.input, minHeight: 96 }} value={outcomeSummary} onChange={(event) => setOutcomeSummary(event.target.value)} />
              </Field>
              <Field label="Root cause category">
                <input style={styles.input} value={rootCauseCategory} placeholder="deployment_change, capacity, dependency, unknown" onChange={(event) => setRootCauseCategory(event.target.value)} />
              </Field>
              <Field label="Resolution summary">
                <textarea style={{ ...styles.input, minHeight: 96 }} value={resolutionSummary} onChange={(event) => setResolutionSummary(event.target.value)} />
              </Field>
              <Field label="Corrective action">
                <textarea style={{ ...styles.input, minHeight: 96 }} value={correctiveAction} onChange={(event) => setCorrectiveAction(event.target.value)} />
              </Field>
              {caseId ? <PluginSameFix backendUrl={backendUrl} caseId={caseId} refreshKey={caseDetails?.updated_at} /> : null}
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
            <strong>{isSaving ? 'Saving changes...' : saveError ? 'Not saved' : 'All changes saved'}</strong>
            <div style={saveError ? { color: '#ff7381' } : styles.muted}>{saveError || (lastSavedAt ? `Last saved ${lastSavedAt}` : 'Just now')}</div>
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
  const [caseList, setCaseList] = useState<GrafanaCase[]>([]);
  const [casesDrawerOpen, setCasesDrawerOpen] = useState(false);
  const [isLoadingCases, setIsLoadingCases] = useState(false);
  const [workflowError, setWorkflowError] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const [assistantBusy, setAssistantBusy] = useState(false);
  const [assistantConversationId, setAssistantConversationId] = useState<string | null>(null);
  const [isResettingTestData, setIsResettingTestData] = useState(false);
  const [evidenceExpanded, setEvidenceExpanded] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  // The drawer shows a behavior case's own snapshot, not the selected single-metric finding.
  const [drawerForBehavior, setDrawerForBehavior] = useState(false);

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
    setCaseList([]);
    setWorkflowError('');
    setAssistantConversationId(null);
    setDrawerOpen(false);
    setDrawerForBehavior(false);
    setCasesDrawerOpen(false);
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
      setDrawerForBehavior(false);
      setDrawerOpen(true);
    } catch {
      setWorkflowError('Could not create an investigation case for this finding.');
    } finally {
      setIsBusy(false);
    }
  };

  const openBehaviorCase = async (caseId: number) => {
    setWorkflowError('');
    try {
      setCaseDetails(await getCase(backendUrl, caseId));
      setCaseResult(null);
      setDrawerForBehavior(true);
      setDrawerOpen(true);
    } catch {
      setWorkflowError(`Could not open case #${caseId}.`);
    }
  };

  const askAssistant = async (prompt: string) => {
    if (!result) return;
    setWorkflowError('');
    setAssistantBusy(true);
    try {
      if (isAnalyzerRoutingPrompt(prompt)) {
        setQuestionAnswer(localAssistantAnswer(prompt, result, selectedFinding, linkedSignals.length ? linkedSignals : result.signals));
        return;
      }
      const memoryAnswer = await askAssistantWithMemory(backendUrl, {
        message: buildAssistantMemoryPrompt(prompt, result, selectedFinding, linkedSignals.length ? linkedSignals : result.signals),
        caseId: caseDetails?.id ?? null,
        conversationId: assistantConversationId,
      });
      setAssistantConversationId(memoryAnswer.conversation_id);
      setQuestionAnswer(assistantChatToQuestionAnswer(memoryAnswer));
      return;
    } catch {
      try {
      const questionId = questionIdForPrompt(prompt);
      const backendAnswer = await answerQuestion(backendUrl, {
        questionId,
        service: result.service,
        metric: result.metric,
        analysisRunId: result.runId,
      });
      const hasUsefulAnswer = backendAnswer.status !== 'unknown' && backendAnswer.confidence > 0;
      setQuestionAnswer(
        hasUsefulAnswer
          ? backendAnswer
          : localAssistantAnswer(prompt, result, selectedFinding, linkedSignals.length ? linkedSignals : result.signals)
      );
      } catch {
      setQuestionAnswer(localAssistantAnswer(prompt, result, selectedFinding, linkedSignals.length ? linkedSignals : result.signals));
      }
    } finally {
      setAssistantBusy(false);
    }
  };

  const clearTestingData = async () => {
    const confirmed = window.confirm(
      'Testing only: clear Ops Signals runs, timeseries, signals, findings, cases, question answers, and case vector memory? This cannot be undone.'
    );
    if (!confirmed) return;
    setIsResettingTestData(true);
    setWorkflowError('');
    try {
      const reset = await resetTestingOperationalData(backendUrl);
      const deleted = Object.entries(reset.deleted_rows)
        .map(([table, count]) => `${table}: ${count}`)
        .join(', ');
      setWorkflowError(`Testing data reset complete. Deleted ${deleted}. Vector memory: ${String(reset.vector_memory.status ?? 'unknown')}.`);
      setQuestionAnswer(null);
      setCaseResult(null);
      setCaseDetails(null);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      setWorkflowError(
        message.startsWith('Request failed: 404')
          ? 'Testing reset is disabled on this backend. Start it with OPS_SIGNALS_ENABLE_TESTING_API=true to use it.'
          : `Testing reset failed. ${message}`
      );
    } finally {
      setIsResettingTestData(false);
    }
  };

  const openCases = async () => {
    if (!result) return;
    setCasesDrawerOpen(true);
    setIsLoadingCases(true);
    setWorkflowError('');
    try {
      const cases = await listCases(backendUrl, {
        service: result.service,
        metricName: result.metric,
        limit: 25,
      });
      setCaseList(cases);
    } catch {
      setWorkflowError('Could not load recent cases.');
    } finally {
      setIsLoadingCases(false);
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
              <span>Run ID</span><strong title={result.runId} style={{ cursor: 'help' }}>{truncateId(result.runId)}</strong>
              <span>Data source</span><strong>{result.datasource}</strong>
              <span>Datasource UID</span><strong>{result.datasourceUid ?? 'n/a'}</strong>
              <span>Service</span><strong>{result.service}</strong>
              <span>Query window</span><strong>{result.from || result.to ? `${result.from} - ${result.to}` : 'Backend selected run window'}</strong>
              <span>Status</span><strong>{humanize(result.status)}</strong>
            </div>
            <AnalyzerRoutingSummary result={result} />
            <div style={{ ...styles.infoNote, marginTop: 12 }}>
              <button type="button" style={buttonStyle('danger', isResettingTestData)} disabled={isResettingTestData} onClick={clearTestingData}>
                {isResettingTestData ? 'Clearing test data...' : 'Clear DB for testing'}
              </button>
              <div style={{ marginTop: 6 }}>Testing only: clears analysis outputs and case vector memory, not configuration or app documentation.</div>
            </div>
          </details>
        </div>
      </Card>

      <div style={styles.contentGrid}>
        <main style={styles.stack}>
          <PrimaryFindingCard
            result={result}
            backendUrl={backendUrl}
            finding={selectedFinding}
            isBusy={isBusy}
            onInvestigate={() => {
              setDrawerForBehavior(false);
              setDrawerOpen(true);
            }}
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
          {selectedFinding ? <PluginSeenBefore backendUrl={backendUrl} findingId={selectedFinding.id} service={result.service} frame={styles.card} /> : null}
          <PluginBehaviorFindings backendUrl={backendUrl} findings={result.behaviorFindings} onOpenCase={openBehaviorCase} frame={styles.card} />
          <MetricTimeline result={result} selectedFinding={selectedFinding} />
          <RecentInvestigationsTable
            caseDetails={caseDetails}
            onOpenCase={() => setDrawerOpen(true)}
            onViewAllCases={openCases}
          />
        </main>

        <aside style={styles.stack}>
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
          <AskOpsSignalsCard
            result={result}
            finding={selectedFinding}
            signals={linkedSignals.length ? linkedSignals : result.signals}
            questions={questions}
            answer={questionAnswer}
            isBusy={assistantBusy}
            onAsk={askAssistant}
          />
        </aside>
      </div>

      <InvestigationDrawer
        open={drawerOpen}
        caseResult={caseResult}
        caseDetails={caseDetails}
        finding={drawerForBehavior ? null : selectedFinding}
        result={drawerForBehavior ? null : result}
        backendUrl={backendUrl}
        onClose={() => setDrawerOpen(false)}
        onCaseChange={setCaseDetails}
        onError={setWorkflowError}
      />
      <CasesDrawer
        open={casesDrawerOpen}
        cases={caseList}
        isLoading={isLoadingCases}
        onClose={() => setCasesDrawerOpen(false)}
        onOpenCase={(caseItem) => {
          setCaseDetails(caseItem);
          setCaseResult({
            case_id: caseItem.id,
            finding_id: caseItem.finding_id,
            case_status: caseItem.case_status,
            memory_status: caseItem.memory_status,
          });
          setCasesDrawerOpen(false);
          setDrawerForBehavior(false);
          setDrawerOpen(true);
        }}
      />
    </div>
  );
}
