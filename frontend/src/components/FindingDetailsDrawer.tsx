import { Box, Chip, CircularProgress, Drawer, List, ListItem, ListItemText, Stack, Tooltip, Typography } from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import { Line, LineChart, ResponsiveContainer, Tooltip as RechartsTooltip, XAxis, YAxis } from 'recharts';
import { api } from '../api/queries';
import { LinkedAlerts } from './AlertComponents';
import type { Finding, Signal } from '../types';
import { groupSignalsByAnalyzer, signalGroupChipLabel, signalGroupTooltip } from '../utils/signalGroups';

type Props = {
  open: boolean;
  finding: Finding | null;
  signals?: Signal[];
  onClose: () => void;
};

// Source badge shown next to the ingested-data chart - the answer to "where did this data come
// from, so I can backtrack if something looks wrong." One label/color per ingestion path this
// app supports; unrecognized providers fall back to their raw value rather than a wrong label.
const PROVIDER_LABELS: Record<string, string> = {
  otel: 'OTLP',
  prometheus: 'Prometheus',
  datadog: 'Datadog',
  csv: 'CSV',
  generic: 'CSV',
  custom: 'CSV',
};

const PROVIDER_COLORS: Record<string, string> = {
  otel: '#6d28d9',
  prometheus: '#e4581f',
  datadog: '#632ca6',
  csv: '#0f766e',
  generic: '#0f766e',
  custom: '#0f766e',
};

function providerLabel(provider?: string | null): string {
  if (!provider) return 'Unknown source';
  return PROVIDER_LABELS[provider] ?? provider;
}

function providerColor(provider?: string | null): string {
  if (!provider) return '#64748b';
  return PROVIDER_COLORS[provider] ?? '#64748b';
}

export function FindingDetailsDrawer({ open, finding, signals = [], onClose }: Props) {
  const analysisRunId = finding?.analysis_run_id;

  const analysisRunQuery = useQuery({
    queryKey: ['finding-drawer-analysis-run', analysisRunId],
    queryFn: () => api.analysisRun(analysisRunId!),
    enabled: open && Boolean(analysisRunId),
  });

  const timeseriesQuery = useQuery({
    queryKey: ['finding-drawer-timeseries', finding?.service, finding?.metric_name, analysisRunId],
    queryFn: () => api.timeseries(finding!.service!, finding!.metric_name, analysisRunId!),
    enabled: open && Boolean(finding?.service) && Boolean(analysisRunId),
  });

  if (!finding) return null;

  const getHealthColor = (status?: string): 'error' | 'warning' | 'success' | 'default' => {
    switch (status?.toLowerCase()) {
      case 'critical':
        return 'error';
      case 'significant':
        return 'warning';
      case 'normal':
        return 'success';
      default:
        return 'default';
    }
  };

  const getCategoryLabel = (category?: string): string => {
    if (!category) return 'Insight';
    return category
      .split('_')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  };

  const matchedSignals = finding.signal_ids
    .map((signalId) => signals.find((signal) => signal.id === signalId))
    .filter((signal): signal is Signal => Boolean(signal))
    .filter((signal) => signal.severity ? signal.severity.toLowerCase() !== 'low' : signal.importance_score >= 0.55);

  const signalGroups = groupSignalsByAnalyzer(matchedSignals);

  return (
    <Drawer anchor="right" open={open} onClose={onClose}>
      <Box sx={{ width: { xs: '100vw', md: 560 }, p: 3, overflowY: 'auto' }}>
        <Typography variant="h5">{finding.title}</Typography>
        
        <Stack direction="row" spacing={1} sx={{ my: 2, flexWrap: 'wrap', gap: 1 }}>
          <Chip 
            label={finding.health_status.charAt(0).toUpperCase() + finding.health_status.slice(1)} 
            color={getHealthColor(finding.health_status)}
          />
          <Chip label={`Category: ${getCategoryLabel(finding.category)}`} />
          <Chip label={`Importance: ${finding.importance_score.toFixed(2)}`} />
          <Chip label={`Priority: P${finding.investigation_priority}`} variant="outlined" />
        </Stack>

        <LinkedAlerts findingId={finding.id} />

        <Box sx={{ mb: 3, p: 2, backgroundColor: '#f5f5f5', borderRadius: 1 }}>
          <Stack direction="row" spacing={0.75} alignItems="flex-start">
            {finding.ai_summary && (
              <Chip label="AI" size="small" variant="outlined" color="info" sx={{ height: 18, fontSize: '0.65rem', mt: 0.25 }} />
            )}
            <Typography variant="body2">{finding.ai_summary ?? finding.summary}</Typography>
          </Stack>
        </Box>

        <List dense>
          <ListItem>
            <ListItemText primary="Metric" secondary={finding.metric_name} />
          </ListItem>
          {finding.service && (
            <ListItem>
              <ListItemText primary="Service" secondary={finding.service} />
            </ListItem>
          )}
          <ListItem>
            <ListItemText 
              primary="Evidence (Supporting Signals)" 
              secondary={`${matchedSignals.length} supporting signal${matchedSignals.length !== 1 ? 's' : ''} detected`}
            />
          </ListItem>
          {finding.signal_ids.length > 0 && (
            <ListItem>
              <ListItemText 
                primary="Signals used"
                secondary={
                  <Stack component="span" spacing={0.75} sx={{ mt: 1, flexWrap: 'wrap' }}>
                    {signalGroups.length > 0
                      ? signalGroups.map((group) => (
                          <Tooltip key={group.key} title={<span style={{ whiteSpace: 'pre-line' }}>{signalGroupTooltip(group)}</span>} arrow>
                            <Chip
                              label={signalGroupChipLabel(group)}
                              size="small"
                              variant="outlined"
                              sx={{ mr: 0.5, mb: 0.5 }}
                            />
                          </Tooltip>
                        ))
                      : <Typography variant="caption" color="text.secondary">No problem-signals matched.</Typography>}
                  </Stack>
                }
              />
            </ListItem>
          )}
        </List>

        {analysisRunId && (
          <>
            <Stack direction="row" alignItems="center" spacing={1.5} sx={{ mt: 3, mb: 1 }}>
              <Typography variant="h6">Ingested Data</Typography>
              {analysisRunQuery.data && (
                <Chip
                  size="small"
                  label={providerLabel(analysisRunQuery.data.provider)}
                  sx={{ bgcolor: providerColor(analysisRunQuery.data.provider), color: '#fff', fontWeight: 700 }}
                />
              )}
            </Stack>
            {analysisRunQuery.data && (
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5 }}>
                {analysisRunQuery.data.sample_count} points · {analysisRunQuery.data.status} · run {analysisRunId.slice(0, 8)}
              </Typography>
            )}

            {timeseriesQuery.isLoading && (
              <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
                <CircularProgress size={24} />
              </Box>
            )}
            {timeseriesQuery.isError && (
              <Typography variant="body2" color="error">
                Could not load the ingested data for this finding.
              </Typography>
            )}
            {timeseriesQuery.data && timeseriesQuery.data.length === 0 && (
              <Typography variant="body2" color="text.secondary">
                No raw points found for this analysis run.
              </Typography>
            )}
            {timeseriesQuery.data && timeseriesQuery.data.length > 0 && (
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={timeseriesQuery.data}>
                  <XAxis
                    dataKey="timestamp"
                    tickFormatter={(value: string) => new Date(value).toLocaleString(undefined, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                    tickLine={false}
                    axisLine={false}
                    minTickGap={40}
                  />
                  <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={40} />
                  <RechartsTooltip labelFormatter={(value: string) => new Date(value).toLocaleString()} />
                  <Line type="monotone" dataKey="value" stroke="#4f46e5" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </>
        )}

        {Object.keys(finding.comparison_json).length > 0 && (
          <>
            <Typography variant="h6" sx={{ mt: 3, mb: 2 }}>Comparison Analysis</Typography>
            <Box sx={{ backgroundColor: '#f5f5f5', p: 2, borderRadius: 1, maxHeight: 300, overflowY: 'auto' }}>
              <Typography variant="caption" component="pre" sx={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap', fontSize: '0.75rem' }}>
                {JSON.stringify(finding.comparison_json, null, 2)}
              </Typography>
            </Box>
          </>
        )}
      </Box>
    </Drawer>
  );
}
