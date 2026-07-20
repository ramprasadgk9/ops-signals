import type { AnalysisRun, BehaviorFinding, Finding, Signal } from '../types';
import type { GrafanaSourceConfig, PluginAnalysisResult } from './types';

export type MockAnalysisBundle = PluginAnalysisResult & {
  signalsList: Signal[];
  findingsList: Finding[];
  behaviorFindingsList: BehaviorFinding[];
  recentRun?: AnalysisRun;
};

function stableId(source: string) {
  return source.replace(/[^a-zA-Z0-9]+/g, '-').toLowerCase();
}

export function buildMockAnalysis(config: GrafanaSourceConfig, runs: AnalysisRun[]): MockAnalysisBundle {
  const recentRun = runs.find((run) => run.service === config.service && run.metric_name === config.metric);
  const runId = recentRun?.id ?? `grafana-${stableId(config.datasource)}-${stableId(config.service)}-${stableId(config.metric)}`;

  const signals: Signal[] = [
    {
      id: `${runId}-signal-1`,
      signal_type: 'anomaly',
      analyzer_id: 'baseline_shift',
      metric_name: config.metric,
      service: config.service,
      severity: 'medium',
      confidence: 0.86,
      importance_score: 0.74,
      start_time: config.timeRange.from || recentRun?.start_time || '',
      end_time: config.timeRange.to || recentRun?.end_time || '',
      summary: 'Detected a sustained shift in the selected metric.',
      evidence: {
        source: 'prometheus',
        datasource: config.datasource,
      },
      analysis_run_id: runId,
    },
  ];

  const findings: Finding[] = [
    {
      id: 1,
      service: config.service,
      metric_name: config.metric,
      title: 'Operational finding: sustained behavior shift',
      summary: 'The selected metric shows a sustained shift that should be reviewed with the underlying evidence.',
      category: 'behavioral',
      health_status: 'warning',
      importance_score: 0.78,
      investigation_priority: 2,
      signal_ids: signals.map((signal) => signal.id),
      comparison_json: {
        source: config.datasource,
        time_range: config.timeRange,
      },
      analysis_run_id: runId,
      created_at: new Date().toISOString(),
    },
  ];

  const behaviorFindings: BehaviorFinding[] = [
    {
      id: 1,
      behavior_id: 'cpu-throttling-like-pattern',
      definition_id: 'cpu_throttling_like_pattern',
      definition_version: 1,
      title: 'Possible service degradation pattern',
      summary: 'Multiple signals support a higher-level operational issue.',
      category: 'degradation',
      severity: 'high',
      service: config.service,
      analysis_run_id: runId,
      input_metrics_json: {
        primary: config.metric,
      },
      facts_json: {
        trend: 'shifted',
        confidence: 0.86,
      },
      evidence_json: ['signal.evidence.datasource', 'signal.evidence.source'],
      matched_conditions_json: [
        { fact: 'trend', operator: 'equals', value: 'shifted', passed: true, group: 'all' },
        { fact: 'confidence', operator: 'gte', value: 0.8, passed: true, group: 'all' },
      ],
      confidence: 0.91,
      correlation_json: {
        window: 'aligned',
        overlap: 'strong',
      },
      case_id: null,
      created_at: new Date().toISOString(),
    },
  ];

  return {
    runId,
    datasource: config.datasource,
    service: config.service,
    metric: config.metric,
    from: config.timeRange.from,
    to: config.timeRange.to,
    status: 'complete',
    summary: recentRun ? 'Analysis replayed from backend history.' : 'Mock analysis executed against the selected Prometheus context.',
    signals: signals.length,
    findings: findings.length,
    memoryMatches: 1,
    knowledgeMatches: behaviorFindings.length,
    signalsList: signals,
    findingsList: findings,
    behaviorFindingsList: behaviorFindings,
    recentRun,
  };
}
