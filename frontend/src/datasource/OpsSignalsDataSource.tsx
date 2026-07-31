import { useMemo, useState } from 'react';
import { Alert, Box, Button, Paper, Stack, Typography } from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { ErrorState } from '../components/ErrorState';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { buildMockAnalysis } from '../grafana/mockAnalysis';
import type { GrafanaAnalysisResult, GrafanaQueryTarget } from '../grafana/contracts';
import { PanelPreview } from '../grafana/PanelPreview';
import { ConfigEditor } from './ConfigEditor';
import { QueryEditor } from './QueryEditor';
import { QueryEditorHelp } from './QueryEditorHelp';
import type { OpsSignalsDataSourceOptions, OpsSignalsQuery } from './types';

const defaultTarget: GrafanaQueryTarget = {
  datasource: 'Prometheus',
  service: '',
  metric: '',
  timeRange: {
    from: '',
    to: '',
  },
};

export function OpsSignalsDataSource() {
  const defaultBackendUrl = import.meta.env.VITE_OPS_SIGNALS_BACKEND_URL ?? 'http://localhost:8002';
  const [target, setTarget] = useState<GrafanaQueryTarget>(defaultTarget);
  const [result, setResult] = useState<GrafanaAnalysisResult | null>(null);
  const [options, setOptions] = useState<OpsSignalsDataSourceOptions>({
    url: defaultBackendUrl,
    defaultService: '',
  });
  const [query, setQuery] = useState<OpsSignalsQuery>({
    refId: 'A',
    service: '',
    metric: '',
    from: '',
    to: '',
  });

  const servicesQuery = useQuery({ queryKey: ['grafana-plugin-services'], queryFn: api.services });
  const metricsQuery = useQuery({
    queryKey: ['grafana-plugin-metrics', query.service],
    queryFn: () => api.metrics(query.service),
    enabled: Boolean(query.service),
  });
  const runsQuery = useQuery({ queryKey: ['grafana-plugin-analysis-runs'], queryFn: api.analysisRuns });

  const mockResult = useMemo(
    () => (query.service && query.metric ? buildMockAnalysis({ datasource: 'Prometheus', service: query.service, metric: query.metric, timeRange: { from: query.from, to: query.to } }, runsQuery.data ?? []) : null),
    [query, runsQuery.data]
  );
  const queryPreview = useMemo(() => ({ ...query }), [query]);

  if (servicesQuery.isLoading || runsQuery.isLoading) return <LoadingSkeleton />;
  if (servicesQuery.error || runsQuery.error) return <ErrorState message="Failed to load plugin context" />;

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <Paper sx={{ p: 3 }}>
        <Stack spacing={1}>
          <Typography variant="overline" color="primary">
            Grafana Datasource Surface
          </Typography>
          <Typography variant="h4">Ops Signals</Typography>
          <Typography variant="body2" color="text.secondary">
            This datasource-oriented view selects the query target and produces the structured analysis payload shared by the app and panel modules.
          </Typography>
        </Stack>
      </Paper>

      <Paper sx={{ p: 3 }}>
        <Stack spacing={2}>
          <ConfigEditor options={options} onChange={setOptions} />
          <QueryEditor
            query={queryPreview}
            services={servicesQuery.data ?? []}
            metrics={metricsQuery.data ?? []}
            onChange={setQuery}
          />
          <QueryEditorHelp />
          <Typography variant="h6">Query Builder</Typography>
          <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', md: 'repeat(4, 1fr)' } }}>
            <Box>
              <Typography variant="caption" color="text.secondary">Backend URL</Typography>
              <Typography variant="body2">{options.url}</Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">Default Service</Typography>
              <Typography variant="body2">{options.defaultService || 'n/a'}</Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">Query Service</Typography>
              <Typography variant="body2">{query.service || 'n/a'}</Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">Query Metric</Typography>
              <Typography variant="body2">{query.metric || 'n/a'}</Typography>
            </Box>
          </Box>

          <Button
            variant="contained"
            onClick={() => {
              const nextTarget = {
                datasource: 'Prometheus',
                service: query.service || options.defaultService || '',
                metric: query.metric,
                timeRange: { from: query.from, to: query.to },
              };
              setTarget(nextTarget);
              setResult(buildMockAnalysis(nextTarget, runsQuery.data ?? []));
            }}
            disabled={!mockResult}
          >
            Run Analysis
          </Button>
        </Stack>
      </Paper>

      {result && (
        <Alert severity="info">
          {result.summary} The resulting payload is ready to hand off to the panel module or a future Grafana backend bridge.
        </Alert>
      )}

      <PanelPreview result={result} backendUrl={options.url || defaultBackendUrl} />
    </Box>
  );
}
