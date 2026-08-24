import { Alert, Box, Button, Checkbox, Chip, FormControlLabel, MenuItem, Paper, Stack, TextField, Typography } from '@mui/material';
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';
import PreviewRoundedIcon from '@mui/icons-material/PreviewRounded';
import { useMemo, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { buildAutonomousPreviewRequest } from '../grafana/autonomousPreviewModel';
import type { MonitoringCategory } from '../grafana/contracts';

const categories: Array<{ id: MonitoringCategory; title: string; detail: string }> = [
  { id: 'performance', title: 'Performance', detail: 'Latency, throughput, request rate' },
  { id: 'capacity', title: 'Capacity', detail: 'CPU, memory, disk, saturation' },
  { id: 'availability', title: 'Availability', detail: 'Errors, success rate, saturation' },
  { id: 'reliability', title: 'Reliability', detail: 'Exceptions, retries, timeouts' },
  { id: 'infrastructure', title: 'Infrastructure', detail: 'Nodes, containers, volumes' },
  { id: 'messaging', title: 'Messaging', detail: 'Kafka lag, queues, publish rate' },
  { id: 'kubernetes', title: 'Kubernetes', detail: 'Pods, deployments, restarts' },
  { id: 'custom', title: 'Custom', detail: 'Explicit metric filters' },
];

type Props = {
  onRunComplete: () => void;
};

export function AutonomousConfigurePanel({ onRunComplete }: Props) {
  const [environment, setEnvironment] = useState('production');
  const [serviceLabel, setServiceLabel] = useState('service');
  const [namespaceLabel, setNamespaceLabel] = useState('namespace');
  const [environmentLabel, setEnvironmentLabel] = useState('env');
  const [allServices, setAllServices] = useState(true);
  const [allNamespaces, setAllNamespaces] = useState(true);
  const [selectedServices, setSelectedServices] = useState<string[]>([]);
  const [selectedNamespaces, setSelectedNamespaces] = useState<string[]>([]);
  const [selectedCategories, setSelectedCategories] = useState<MonitoringCategory[]>(['performance', 'capacity', 'availability']);
  const [analysisWindow, setAnalysisWindow] = useState('24h');
  const [executionInterval, setExecutionInterval] = useState('1m');
  const [maxMetricsPerRun, setMaxMetricsPerRun] = useState('500');
  const [maxParallelJobs, setMaxParallelJobs] = useState('20');
  const [customExplicitMetrics, setCustomExplicitMetrics] = useState('');
  const [customIncludePatterns, setCustomIncludePatterns] = useState('');
  const [customExcludePatterns, setCustomExcludePatterns] = useState('');

  const scopeQuery = useQuery({
    queryKey: ['autonomous-scope-options', serviceLabel, namespaceLabel, environmentLabel],
    queryFn: () => api.autonomousScopeOptions({ service_label: serviceLabel, namespace_label: namespaceLabel, environment_label: environmentLabel }),
    retry: false,
  });

  const request = useMemo(() => buildAutonomousPreviewRequest({
    backend: 'standalone-web',
    environment,
    allServices,
    selectedServices,
    allNamespaces,
    selectedNamespaces,
    serviceLabel,
    namespaceLabel,
    environmentLabel,
    selectedCategories,
    executionInterval,
    analysisWindow,
    maxMetricsPerRun,
    maxParallelJobs,
    customExplicitMetrics,
    customIncludePatterns,
    customExcludePatterns,
  }), [environment, allServices, selectedServices, allNamespaces, selectedNamespaces, serviceLabel, namespaceLabel, environmentLabel, selectedCategories, executionInterval, analysisWindow, maxMetricsPerRun, maxParallelJobs, customExplicitMetrics, customIncludePatterns, customExcludePatterns]);

  const previewMutation = useMutation({ mutationFn: () => api.autonomousPreview(request) });
  const runMutation = useMutation({
    mutationFn: () => api.autonomousRunOnce(request),
    onSuccess: () => onRunComplete(),
  });

  const toggleCategory = (category: MonitoringCategory) => {
    setSelectedCategories((current) => current.includes(category) ? current.filter((item) => item !== category) : [...current, category]);
  };

  return (
    <Paper variant="outlined" sx={{ p: 2.5, mb: 3, borderRadius: 2 }}>
      <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" gap={2} sx={{ mb: 2 }}>
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 900 }}>Configure Autonomous Analysis</Typography>
          <Typography variant="body2" color="text.secondary">Configure scope, preview planned metrics, then execute one autonomous run.</Typography>
        </Box>
        <Stack direction="row" gap={1}>
          <Button startIcon={<PreviewRoundedIcon />} variant="outlined" disabled={!selectedCategories.length || previewMutation.isPending} onClick={() => previewMutation.mutate()}>
            {previewMutation.isPending ? 'Previewing...' : 'Preview'}
          </Button>
          <Button startIcon={<PlayArrowRoundedIcon />} variant="contained" disabled={!selectedCategories.length || runMutation.isPending} onClick={() => runMutation.mutate()}>
            {runMutation.isPending ? 'Running...' : 'Run once'}
          </Button>
        </Stack>
      </Stack>

      {(previewMutation.error || runMutation.error || scopeQuery.error) ? <Alert severity="error" sx={{ mb: 2 }}>Autonomous request failed. Check Prometheus configuration and backend logs.</Alert> : null}
      {runMutation.data ? <Alert severity="success" sx={{ mb: 2 }}>Run {runMutation.data.status}: {runMutation.data.executed_jobs} executed, {runMutation.data.failed_jobs} failed.</Alert> : null}
      {previewMutation.data ? <Alert severity="info" sx={{ mb: 2 }}>Preview found {previewMutation.data.metrics_discovered} metrics and planned {previewMutation.data.planned_jobs} jobs.</Alert> : null}

      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: '1fr 1.4fr 1fr' }, gap: 2 }}>
        <Stack gap={1.2}>
          <Typography sx={{ fontWeight: 850 }}>1. Analysis Scope</Typography>
          <TextField select size="small" label="Environment" value={environment} onChange={(e) => setEnvironment(e.target.value)}>
            <MenuItem value="production">Production</MenuItem>
            <MenuItem value="staging">Staging</MenuItem>
            <MenuItem value="all">All environments</MenuItem>
          </TextField>
          <TextField size="small" label="Environment label" value={environmentLabel} onChange={(e) => setEnvironmentLabel(e.target.value)} />
          <TextField size="small" label="Service label" value={serviceLabel} onChange={(e) => setServiceLabel(e.target.value)} />
          <FormControlLabel control={<Checkbox checked={allServices} onChange={(e) => setAllServices(e.target.checked)} />} label="All discovered services" />
          <TextField select size="small" label="Services" SelectProps={{ multiple: true }} disabled={allServices} value={selectedServices} onChange={(e) => setSelectedServices(typeof e.target.value === 'string' ? e.target.value.split(',') : e.target.value as string[])}>
            {(scopeQuery.data?.services ?? []).map((service) => <MenuItem key={service} value={service}>{service}</MenuItem>)}
          </TextField>
          <TextField size="small" label="Namespace label" value={namespaceLabel} onChange={(e) => setNamespaceLabel(e.target.value)} />
          <FormControlLabel control={<Checkbox checked={allNamespaces} onChange={(e) => setAllNamespaces(e.target.checked)} />} label="All namespaces" />
          <TextField select size="small" label="Namespaces" SelectProps={{ multiple: true }} disabled={allNamespaces} value={selectedNamespaces} onChange={(e) => setSelectedNamespaces(typeof e.target.value === 'string' ? e.target.value.split(',') : e.target.value as string[])}>
            {(scopeQuery.data?.namespaces ?? []).map((namespace) => <MenuItem key={namespace} value={namespace}>{namespace}</MenuItem>)}
          </TextField>
        </Stack>

        <Stack gap={1.2}>
          <Typography sx={{ fontWeight: 850 }}>2. Monitoring Categories</Typography>
          <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)' }, gap: 1 }}>
            {categories.map((item) => (
              <Button key={item.id} variant={selectedCategories.includes(item.id) ? 'contained' : 'outlined'} onClick={() => toggleCategory(item.id)} sx={{ justifyContent: 'space-between', textAlign: 'left', minHeight: 72, textTransform: 'none' }}>
                <span><strong>{item.title}</strong><br /><small>{item.detail}</small></span>
                {selectedCategories.includes(item.id) ? <span>✓</span> : null}
              </Button>
            ))}
          </Box>
          {selectedCategories.includes('custom') ? (
            <Stack gap={1}>
              <TextField size="small" label="Explicit metrics, comma-separated" value={customExplicitMetrics} onChange={(e) => setCustomExplicitMetrics(e.target.value)} />
              <TextField size="small" label="Include patterns, comma-separated" value={customIncludePatterns} onChange={(e) => setCustomIncludePatterns(e.target.value)} />
              <TextField size="small" label="Exclude patterns, comma-separated" value={customExcludePatterns} onChange={(e) => setCustomExcludePatterns(e.target.value)} />
            </Stack>
          ) : null}
        </Stack>

        <Stack gap={1.2}>
          <Typography sx={{ fontWeight: 850 }}>3. Execution Limits</Typography>
          <Chip label="Mode: Run once" />
          <TextField select size="small" label="Analysis window" value={analysisWindow} onChange={(e) => setAnalysisWindow(e.target.value)}>
            {['30m', '1h', '6h', '24h', '7d'].map((value) => <MenuItem key={value} value={value}>{value}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="Analysis interval" value={executionInterval} onChange={(e) => setExecutionInterval(e.target.value)}>
            {['30s', '1m', '5m', '10m'].map((value) => <MenuItem key={value} value={value}>{value}</MenuItem>)}
          </TextField>
          <TextField size="small" type="number" label="Max metrics per run" value={maxMetricsPerRun} onChange={(e) => setMaxMetricsPerRun(e.target.value)} />
          <TextField size="small" type="number" label="Max parallel jobs" value={maxParallelJobs} onChange={(e) => setMaxParallelJobs(e.target.value)} />
        </Stack>
      </Box>
    </Paper>
  );
}
