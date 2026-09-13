import type { AnalysisRun, BehaviorFinding, Finding, Signal } from '../types';
import type {
  GrafanaAnalysisFinding,
  GrafanaAnalysisResult,
  GrafanaAnalysisSignal,
  GrafanaBehaviorFinding,
  GrafanaQueryTarget,
} from './contracts';

function stableId(source: string) {
  return source.replace(/[^a-zA-Z0-9]+/g, '-').toLowerCase();
}

function toGrafanaSignal(signal: Signal): GrafanaAnalysisSignal {
  return {
    id: signal.id,
    analyzer_id: signal.analyzer_id ?? signal.signal_type,
    signal_type: signal.signal_type,
    summary: signal.summary ?? 'Signal detected.',
    severity: signal.severity,
    confidence: signal.confidence,
    importance_score: signal.importance_score,
    start_time: signal.start_time,
    end_time: signal.end_time,
    evidence: signal.evidence,
  };
}

function toGrafanaFinding(finding: Finding): GrafanaAnalysisFinding {
  return {
    id: finding.id ?? 0,
    title: finding.title,
    summary: finding.summary,
    category: finding.category,
    health_status: finding.health_status,
    importance_score: finding.importance_score,
    investigation_priority: finding.investigation_priority,
    signal_ids: finding.signal_ids,
    comparison_json: finding.comparison_json,
  };
}

function toGrafanaBehaviorFinding(finding: BehaviorFinding): GrafanaBehaviorFinding {
  return {
    id: finding.id,
    title: finding.title,
    summary: finding.summary,
    severity: finding.severity,
    confidence: finding.confidence,
    correlation: finding.correlation_json,
  };
}

export function buildMockAnalysis(target: GrafanaQueryTarget, runs: AnalysisRun[]): GrafanaAnalysisResult {
  const recentRun = runs.find((run) => run.service === target.service && run.metric_name === target.metric);
  const runId = recentRun?.id ?? `grafana-${stableId(target.datasource)}-${stableId(target.service)}-${stableId(target.metric)}`;

  const signal = toGrafanaSignal({
    id: `${runId}-signal-1`,
    signal_type: 'anomaly',
    analyzer_id: 'baseline_shift',
    metric_name: target.metric,
    service: target.service,
    severity: 'medium',
    confidence: 0.86,
    importance_score: 0.74,
    start_time: target.timeRange.from || recentRun?.start_time || '',
    end_time: target.timeRange.to || recentRun?.end_time || '',
    summary: 'Detected a sustained shift in the selected metric.',
    evidence: {
      source: 'prometheus',
      datasource: target.datasource,
    },
    analysis_run_id: runId,
  });

  const finding = toGrafanaFinding({
    id: 1,
    service: target.service,
    metric_name: target.metric,
    title: 'Operational finding: sustained behavior shift',
    summary: 'The selected metric shows a sustained shift that should be reviewed with the underlying evidence.',
    category: 'behavioral',
    health_status: 'warning',
    importance_score: 0.78,
    investigation_priority: 2,
    signal_ids: [signal.id],
      comparison_json: {
        source: target.datasource,
        time_range: { from: target.timeRange.from, to: target.timeRange.to },
      },
    analysis_run_id: runId,
    created_at: new Date().toISOString(),
  });

  const behaviorFinding = toGrafanaBehaviorFinding({
    id: 1,
    behavior_id: 'service-degradation-pattern',
    definition_id: 'service_degradation_pattern',
    definition_version: 1,
    title: 'Possible service degradation pattern',
    summary: 'Multiple signals support a higher-level operational issue.',
    category: 'degradation',
    severity: 'high',
    service: target.service,
    analysis_run_id: runId,
    input_metrics_json: { primary: target.metric },
    facts_json: { trend: 'shifted', confidence: 0.86 },
    occurrence_count: 1,
    last_seen_at: new Date().toISOString(),
    evidence_json: ['signal.evidence.datasource', 'signal.evidence.source'],
    matched_conditions_json: [
      { fact: 'trend', operator: 'equals', value: 'shifted', passed: true, group: 'all' },
      { fact: 'confidence', operator: 'gte', value: 0.8, passed: true, group: 'all' },
    ],
    confidence: 0.91,
    correlation_json: { window: 'aligned', overlap: 'strong' },
    case_id: null,
    created_at: new Date().toISOString(),
  });

  return {
    runId,
    status: 'complete',
    datasource: target.datasource,
    service: target.service,
    metric: target.metric,
    from: target.timeRange.from,
    to: target.timeRange.to,
    summary: recentRun ? 'Analysis replayed from backend history.' : 'Mock analysis executed against the selected Prometheus context.',
    signals: [signal],
    findings: [finding],
    behaviorFindings: [behaviorFinding],
    timeseries: [
      {
        timestamp: target.timeRange.from || new Date().toISOString(),
        value: 0.42,
        service: target.service,
        metric_name: target.metric,
        analysis_run_id: runId,
      },
      {
        timestamp: target.timeRange.to || new Date().toISOString(),
        value: 0.74,
        service: target.service,
        metric_name: target.metric,
        analysis_run_id: runId,
      },
    ],
    analysisRuns: runs,
  };
}
