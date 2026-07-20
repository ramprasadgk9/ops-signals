export type GrafanaSourceConfig = {
  datasource: string;
  service: string;
  metric: string;
  timeRange: {
    from: string;
    to: string;
  };
};

export type PluginAnalysisResult = {
  runId: string;
  datasource: string;
  service: string;
  metric: string;
  from: string;
  to: string;
  status: 'idle' | 'running' | 'complete' | 'error';
  summary: string;
  signals: number;
  findings: number;
  memoryMatches: number;
  knowledgeMatches: number;
};
