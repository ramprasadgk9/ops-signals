import { useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { ErrorState } from '../components/ErrorState';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import type { GrafanaSourceConfig, PluginAnalysisResult } from './types';
import { buildMockAnalysis } from './mockAnalysis';

const defaultConfig: GrafanaSourceConfig = {
  datasource: 'Prometheus',
  service: '',
  metric: '',
  timeRange: {
    from: '',
    to: '',
  },
};

function ResultMetric({ label, value }: { label: string; value: string | number }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="h6">{value}</Typography>
    </Box>
  );
}

export function OpsSignalsPlugin() {
  const [config, setConfig] = useState<GrafanaSourceConfig>(defaultConfig);
  const [analysisState, setAnalysisState] = useState<PluginAnalysisResult | null>(null);

  const servicesQuery = useQuery({ queryKey: ['grafana-plugin-services'], queryFn: api.services });
  const metricsQuery = useQuery({
    queryKey: ['grafana-plugin-metrics', config.service],
    queryFn: () => api.metrics(config.service),
    enabled: Boolean(config.service),
  });
  const runsQuery = useQuery({ queryKey: ['grafana-plugin-analysis-runs'], queryFn: api.analysisRuns });
  const findingsQuery = useQuery({
    queryKey: ['grafana-plugin-findings', config.service, config.metric, analysisState?.runId],
    queryFn: () => api.findings(config.service || undefined, config.metric || undefined, analysisState?.runId),
    enabled: Boolean(analysisState?.runId),
  });
  const behaviorQuery = useQuery({
    queryKey: ['grafana-plugin-behavior-findings', analysisState?.runId, config.service],
    queryFn: () => api.behaviorFindings(analysisState?.runId, config.service || undefined),
    enabled: Boolean(analysisState?.runId),
  });

  const selectedRun = useMemo(
    () => runsQuery.data?.find((run) => run.service === config.service && run.metric_name === config.metric),
    [config.metric, config.service, runsQuery.data]
  );
  const mockAnalysis = useMemo(
    () => (config.service && config.metric ? buildMockAnalysis(config, runsQuery.data ?? []) : null),
    [config, runsQuery.data]
  );

  if (servicesQuery.isLoading || runsQuery.isLoading) return <LoadingSkeleton />;
  if (servicesQuery.error || runsQuery.error) return <ErrorState message="Failed to load plugin context" />;

  const memoryMatches = Math.max(0, (analysisState?.findings ?? 0) - Math.max(0, findingsQuery.data?.length ?? 0));

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <Paper sx={{ p: 3 }}>
        <Stack spacing={1}>
          <Typography variant="overline" color="primary">
            Grafana Plugin Surface
          </Typography>
          <Typography variant="h4">Ops Signals</Typography>
          <Typography variant="body2" color="text.secondary">
            This surface is shaped like a Grafana app plugin: pick a datasource, choose a service and metric, then run analysis
            against Prometheus samples or the backend analysis history.
          </Typography>
        </Stack>
      </Paper>

      <Paper sx={{ p: 3 }}>
        <Stack spacing={2}>
          <Typography variant="h6">Query Builder</Typography>
          <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', md: 'repeat(4, 1fr)' } }}>
            <Box>
              <TextField
                fullWidth
                label="Datasource"
                value={config.datasource}
                onChange={(event) => setConfig((current) => ({ ...current, datasource: event.target.value }))}
                helperText="Grafana Prometheus datasource"
              />
            </Box>
            <Box>
              <TextField
                fullWidth
                label="Service"
                value={config.service}
                onChange={(event) => setConfig((current) => ({ ...current, service: event.target.value, metric: '' }))}
                select
                SelectProps={{ native: true }}
                helperText="Backed by your service catalog"
              >
                <option value="" />
                {(servicesQuery.data ?? []).map((service) => (
                  <option key={service} value={service}>
                    {service}
                  </option>
                ))}
              </TextField>
            </Box>
            <Box>
              <TextField
                fullWidth
                label="Metric"
                value={config.metric}
                onChange={(event) => setConfig((current) => ({ ...current, metric: event.target.value }))}
                select
                SelectProps={{ native: true }}
                helperText="Prometheus metric"
                disabled={!config.service}
              >
                <option value="" />
                {(metricsQuery.data ?? []).map((metric) => (
                  <option key={metric} value={metric}>
                    {metric}
                  </option>
                ))}
              </TextField>
            </Box>
            <Box>
              <TextField
                fullWidth
                label="Time range"
                value={config.timeRange.from && config.timeRange.to ? `${config.timeRange.from} → ${config.timeRange.to}` : ''}
                onChange={() => undefined}
                helperText="Grafana time picker will own this later"
              />
            </Box>
          </Box>

          <Box>
            <Button
              variant="contained"
              onClick={() => mockAnalysis && setAnalysisState(mockAnalysis)}
              disabled={!config.service || !config.metric}
            >
              Run Analysis
            </Button>
          </Box>
        </Stack>
      </Paper>

      {analysisState && (
        <Alert severity="info">
          {analysisState.summary} Grafana should send the PromQL sample set to Ops Signals, and Ops Signals should return a structured
          result payload for rendering in panels or drilldowns.
        </Alert>
      )}

      <Paper sx={{ p: 3 }}>
        <Stack spacing={2}>
          <Typography variant="h6">Result Summary</Typography>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} divider={<Divider flexItem orientation="vertical" />}>
            <ResultMetric label="Signals" value={analysisState?.signals ?? 0} />
            <ResultMetric label="Findings" value={analysisState?.findings ?? 0} />
            <ResultMetric label="Operational Memory" value={analysisState?.memoryMatches ?? 0} />
            <ResultMetric label="Behavior Knowledge" value={analysisState?.knowledgeMatches ?? 0} />
          </Stack>
          {mockAnalysis && (
            <Box>
              <Typography variant="caption" color="text.secondary">
                Contract preview
              </Typography>
              <Box component="pre" sx={{ m: 0, mt: 1, p: 2, borderRadius: 2, bgcolor: 'background.default', overflow: 'auto' }}>
                {JSON.stringify(
                  {
                    runId: mockAnalysis.runId,
                    datasource: mockAnalysis.datasource,
                    service: mockAnalysis.service,
                    metric: mockAnalysis.metric,
                    timeRange: { from: mockAnalysis.from, to: mockAnalysis.to },
                    status: mockAnalysis.status,
                    signals: mockAnalysis.signalsList,
                    findings: mockAnalysis.findingsList,
                    behaviorFindings: mockAnalysis.behaviorFindingsList,
                  },
                  null,
                  2
                )}
              </Box>
            </Box>
          )}
          <Box>
            <Typography variant="body2" color="text.secondary">
              This is the right place to attach:
            </Typography>
            <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: 'wrap' }}>
              <Chip label="timeline" />
              <Chip label="signal evidence" />
              <Chip label="behavior reasoning" />
              <Chip label="case creation" />
            </Stack>
          </Box>
        </Stack>
      </Paper>
    </Box>
  );
}
