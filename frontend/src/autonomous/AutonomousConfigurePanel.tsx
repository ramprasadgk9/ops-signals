import { Alert, Box, Button, Checkbox, Chip, FormControlLabel, MenuItem, Paper, Stack, TextField, Typography } from '@mui/material';
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';
import PreviewRoundedIcon from '@mui/icons-material/PreviewRounded';
import EditRoundedIcon from '@mui/icons-material/EditRounded';
import PauseRoundedIcon from '@mui/icons-material/PauseRounded';
import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/queries';
import { buildAutonomousPreviewRequest } from '../grafana/autonomousPreviewModel';
import type { AutonomousPolicy, AutonomousPreviewRequest, AutonomousPreviewResponse, AutonomousRunResponse, MonitoringCategory } from '../grafana/contracts';

function buildPreviewRequestFromPolicy(policy: AutonomousPolicy): AutonomousPreviewRequest {
  return {
    datasource: 'prometheus',
    backend: policy.backend,
    ...(policy.connection_id ? { connection_id: policy.connection_id } : {}),
    scope: policy.scope,
    monitoring_selection: policy.monitoring_selection,
    monitoring_categories: policy.monitoring_selection.categories,
    execution: policy.execution,
    custom_constraints: {
      include_patterns: policy.monitoring_selection.custom_constraints?.include_patterns ?? [],
      exclude_patterns: policy.monitoring_selection.custom_constraints?.exclude_patterns ?? [],
      required_labels: policy.monitoring_selection.custom_constraints?.required_labels ?? {},
      explicit_metrics: policy.monitoring_selection.custom_constraints?.explicit_metrics ?? [],
    },
  };
}

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

const schedulePresets = [5, 15, 30, 60, 360];
const MAX_SHOWN_WARNINGS = 5;

function formatSchedule(minutes: number): string {
  if (minutes % 60 === 0) return `${minutes / 60}h`;
  return `${minutes}m`;
}

function formatRelativeToNow(iso: string | null): string {
  if (!iso) return 'n/a';
  const target = new Date(iso).getTime();
  const diffMs = target - Date.now();
  const diffMinutes = Math.round(diffMs / 60000);
  if (Math.abs(diffMinutes) < 1) return 'now';
  const label = new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  return diffMinutes > 0 ? `${label} (in ${diffMinutes}m)` : `${label} (${Math.abs(diffMinutes)}m ago)`;
}

type Props = {
  onRunComplete: (result: AutonomousRunResponse) => void;
  /** Called with null when the preview no longer applies (another connection was picked). */
  onPreviewComplete?: (result: AutonomousPreviewResponse | null) => void;
  enableCategoryRequest?: MonitoringCategory | null;
  onEnableCategoryHandled?: () => void;
  previewNowSignal?: boolean;
  onPreviewNowHandled?: () => void;
  onPreviewNowStateChange?: (isLoading: boolean) => void;
};

function ScheduledPolicyCard({ policy, connectionName, onEdit, onPause, onResume, isTogglingStatus }: {
  policy: AutonomousPolicy;
  /** Shown only when there is more than one Prometheus connection. */
  connectionName?: string | null;
  onEdit: () => void;
  onPause: () => void;
  onResume: () => void;
  isTogglingStatus: boolean;
}) {
  const categoryTitles = policy.monitoring_selection.categories
    .map((id) => categories.find((c) => c.id === id)?.title ?? id)
    .join(', ');
  const scopeLabel = [
    ...(connectionName ? [connectionName] : []),
    policy.scope.all_services ? 'all services' : `${policy.scope.services.length} service(s)`,
    policy.scope.all_namespaces ? 'all namespaces' : `${policy.scope.namespaces.length} namespace(s)`,
    ...(policy.scope.all_clusters === false ? [`${policy.scope.clusters?.length ?? 0} cluster(s)`] : []),
  ].join(' · ');

  return (
    <Paper variant="outlined" sx={{ p: 2.5, mb: 3, borderRadius: 2 }}>
      <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ md: 'flex-start' }} gap={2} sx={{ mb: 2 }}>
        <Box>
          <Chip
            size="small"
            label={policy.enabled ? 'Scheduled · Active' : 'Scheduled · Paused'}
            color={policy.enabled ? 'success' : 'default'}
            sx={{ mb: 1, fontWeight: 700 }}
          />
          <Typography variant="h6" sx={{ fontWeight: 800 }}>{policy.name}</Typography>
          <Typography variant="body2" color="text.secondary">
            {categoryTitles} &middot; {scopeLabel} &middot; every {policy.schedule_minutes ? formatSchedule(policy.schedule_minutes) : 'n/a'}
          </Typography>
        </Box>
        <Stack direction="row" gap={1}>
          <Button size="small" startIcon={<EditRoundedIcon />} variant="outlined" onClick={onEdit}>Edit</Button>
          {policy.enabled ? (
            <Button size="small" startIcon={<PauseRoundedIcon />} variant="outlined" disabled={isTogglingStatus} onClick={onPause} title="Stop scheduled runs. The schedule is kept and can be resumed.">Pause</Button>
          ) : (
            <Button size="small" variant="outlined" disabled={isTogglingStatus} onClick={onResume}>Resume</Button>
          )}
        </Stack>
      </Stack>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr 1fr', sm: 'repeat(4, 1fr)' }, gap: 2, pt: 2, borderTop: '1px solid', borderColor: 'divider' }}>
        <Box>
          <Typography variant="caption" color="text.secondary" sx={{ textTransform: 'uppercase', letterSpacing: 0.5 }}>Last run</Typography>
          <Typography sx={{ fontWeight: 700 }}>{policy.last_run_status ? policy.last_run_status : 'Not run yet'}</Typography>
        </Box>
        <Box>
          <Typography variant="caption" color="text.secondary" sx={{ textTransform: 'uppercase', letterSpacing: 0.5 }}>Next run</Typography>
          <Typography sx={{ fontWeight: 700 }}>{policy.enabled ? formatRelativeToNow(policy.next_run_at) : 'Paused'}</Typography>
        </Box>
        <Box>
          <Typography variant="caption" color="text.secondary" sx={{ textTransform: 'uppercase', letterSpacing: 0.5 }}>Health</Typography>
          <Typography sx={{ fontWeight: 700, color: policy.consecutive_failures > 0 ? 'error.main' : 'success.main' }}>
            {policy.consecutive_failures > 0 ? `${policy.consecutive_failures} failed in a row` : 'Healthy'}
          </Typography>
        </Box>
        <Box>
          <Typography variant="caption" color="text.secondary" sx={{ textTransform: 'uppercase', letterSpacing: 0.5 }}>Max metrics / run</Typography>
          <Typography sx={{ fontWeight: 700 }}>{policy.execution.max_metrics_per_run}</Typography>
        </Box>
      </Box>
    </Paper>
  );
}

export function AutonomousConfigurePanel({ onRunComplete, onPreviewComplete, enableCategoryRequest, onEnableCategoryHandled, previewNowSignal, onPreviewNowHandled, onPreviewNowStateChange }: Props) {
  const queryClient = useQueryClient();
  const [environment, setEnvironment] = useState('production');
  const [serviceLabel, setServiceLabel] = useState('service');
  const [namespaceLabel, setNamespaceLabel] = useState('namespace');
  const [environmentLabel, setEnvironmentLabel] = useState('env');
  const [allServices, setAllServices] = useState(true);
  const [allNamespaces, setAllNamespaces] = useState(true);
  const [selectedServices, setSelectedServices] = useState<string[]>([]);
  const [selectedNamespaces, setSelectedNamespaces] = useState<string[]>([]);
  const [allClusters, setAllClusters] = useState(true);
  const [selectedClusters, setSelectedClusters] = useState<string[]>([]);
  const [selectedCategories, setSelectedCategories] = useState<MonitoringCategory[]>(['performance', 'capacity', 'availability']);
  const [analysisWindow, setAnalysisWindow] = useState('24h');
  const [executionInterval, setExecutionInterval] = useState('1m');
  const [maxMetricsPerRun, setMaxMetricsPerRun] = useState('500');
  const [maxParallelJobs, setMaxParallelJobs] = useState('20');
  const [customExplicitMetrics, setCustomExplicitMetrics] = useState('');
  const [customIncludePatterns, setCustomIncludePatterns] = useState('');
  const [customExcludePatterns, setCustomExcludePatterns] = useState('');
  const [scheduleMode, setScheduleMode] = useState<'run_once' | 'scheduled'>('run_once');
  const [scheduleMinutes, setScheduleMinutes] = useState(30);
  const [isEditing, setIsEditing] = useState(false);
  const [connectionId, setConnectionId] = useState('default');

  const applyPolicyToForm = (policy: AutonomousPolicy) => {
    setConnectionId(policy.connection_id ?? 'default');
    setEnvironment(policy.scope.environment ?? 'production');
    setServiceLabel(policy.scope.service_label);
    setNamespaceLabel(policy.scope.namespace_label);
    setEnvironmentLabel(policy.scope.environment_label);
    setAllServices(policy.scope.all_services);
    setSelectedServices(policy.scope.services);
    setAllNamespaces(policy.scope.all_namespaces);
    setSelectedNamespaces(policy.scope.namespaces);
    setAllClusters(policy.scope.all_clusters ?? true);
    setSelectedClusters(policy.scope.clusters ?? []);
    setSelectedCategories(policy.monitoring_selection.categories);
    setCustomExplicitMetrics((policy.monitoring_selection.custom_constraints?.explicit_metrics ?? []).join(','));
    setCustomIncludePatterns((policy.monitoring_selection.custom_constraints?.include_patterns ?? []).join(','));
    setCustomExcludePatterns((policy.monitoring_selection.custom_constraints?.exclude_patterns ?? []).join(','));
    setExecutionInterval(policy.execution.interval);
    setAnalysisWindow(policy.execution.analysis_window);
    setMaxMetricsPerRun(String(policy.execution.max_metrics_per_run));
    setMaxParallelJobs(String(policy.execution.max_parallel_jobs));
    setScheduleMode(policy.schedule_minutes ? 'scheduled' : 'run_once');
    if (policy.schedule_minutes) setScheduleMinutes(policy.schedule_minutes);
  };

  const connectionsQuery = useQuery({
    queryKey: ['prometheus-connections'],
    queryFn: () => api.prometheusConnections(),
    retry: false,
  });
  const connections = connectionsQuery.data?.connections ?? [];
  // `default` is the backend's alias for the default connection; show that connection by its own id.
  const effectiveConnectionId = connectionId === 'default' ? connections.find((c) => c.is_default)?.id ?? 'default' : connectionId;
  const connectionNameFor = (id: string | undefined) => {
    if (connections.length < 2) return null;
    const resolved = !id || id === 'default' ? connections.find((c) => c.is_default) : connections.find((c) => c.id === id);
    return resolved?.name ?? id ?? null;
  };
  const changeConnection = (id: string) => {
    // Another tenant has other services and clusters; keep no selection from the previous one,
    // and no preview: it was for the other tenant and would read as this one's.
    setConnectionId(id);
    setSelectedServices([]);
    setSelectedNamespaces([]);
    setSelectedClusters([]);
    previewMutation.reset();
    onPreviewComplete?.(null);
  };

  const scopeQuery = useQuery({
    queryKey: ['autonomous-scope-options', connectionId, serviceLabel, namespaceLabel, environmentLabel, analysisWindow],
    queryFn: () => api.autonomousScopeOptions({ connection_id: connectionId, service_label: serviceLabel, namespace_label: namespaceLabel, environment_label: environmentLabel, window: analysisWindow }),
    retry: false,
  });

  const policiesQuery = useQuery({
    queryKey: ['autonomous-policies'],
    queryFn: () => api.autonomousListPolicies(),
  });
  const activePolicy = policiesQuery.data?.[0] ?? null;

  const request = useMemo(() => buildAutonomousPreviewRequest({
    backend: 'standalone-web',
    environment,
    allServices,
    selectedServices,
    allNamespaces,
    selectedNamespaces,
    allClusters,
    selectedClusters,
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
    connectionId,
  }), [connectionId, environment, allServices, selectedServices, allNamespaces, selectedNamespaces, allClusters, selectedClusters, serviceLabel, namespaceLabel, environmentLabel, selectedCategories, executionInterval, analysisWindow, maxMetricsPerRun, maxParallelJobs, customExplicitMetrics, customIncludePatterns, customExcludePatterns]);

  const previewMutation = useMutation({
    mutationFn: () => api.autonomousPreview(request),
    onSuccess: (result) => onPreviewComplete?.(result),
  });
  const previewPolicyMutation = useMutation({
    mutationFn: (policy: AutonomousPolicy) => api.autonomousPreview(buildPreviewRequestFromPolicy(policy)),
    onSuccess: (result) => onPreviewComplete?.(result),
  });
  const runMutation = useMutation({
    mutationFn: () => api.autonomousRunOnce(request),
    onSuccess: (result) => onRunComplete(result),
  });

  // Backend warnings (e.g. partial data from a Thanos store, discovery truncation) from the latest
  // run, or the latest preview when nothing has run yet. A run repeats its preview's warnings.
  const resultWarnings = useMemo(() => {
    const warnings = runMutation.data
      ? [...runMutation.data.warnings, ...runMutation.data.results.flatMap((job) => job.warnings ?? [])]
      : previewMutation.data?.warnings ?? [];
    return [...new Set(warnings)];
  }, [runMutation.data, previewMutation.data]);

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload = {
        name: 'Production coverage',
        datasource: request.datasource,
        backend: request.backend,
        connection_id: connectionId,
        scope: request.scope,
        monitoring_selection: request.monitoring_selection!,
        execution: request.execution,
        schedule_minutes: scheduleMode === 'scheduled' ? scheduleMinutes : null,
      };
      return activePolicy ? api.autonomousUpdatePolicy(activePolicy.id, payload) : api.autonomousSavePolicy(payload);
    },
    onSuccess: () => {
      setIsEditing(false);
      void queryClient.invalidateQueries({ queryKey: ['autonomous-policies'] });
    },
  });

  const statusMutation = useMutation({
    mutationFn: (enabled: boolean) => api.autonomousSetPolicyStatus(activePolicy!.id, enabled),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['autonomous-policies'] }),
  });

  const toggleCategory = (category: MonitoringCategory) => {
    setSelectedCategories((current) => current.includes(category) ? current.filter((item) => item !== category) : [...current, category]);
  };

  useEffect(() => {
    if (!enableCategoryRequest) return;
    if (activePolicy && !isEditing) {
      applyPolicyToForm(activePolicy);
      setIsEditing(true);
    }
    setSelectedCategories((current) => current.includes(enableCategoryRequest) ? current : [...current, enableCategoryRequest]);
    document.getElementById('autonomous-configure')?.scrollIntoView({ behavior: 'smooth' });
    onEnableCategoryHandled?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enableCategoryRequest]);

  useEffect(() => {
    if (!previewNowSignal || !activePolicy) return;
    previewPolicyMutation.mutate(activePolicy);
    onPreviewNowHandled?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewNowSignal]);

  useEffect(() => {
    onPreviewNowStateChange?.(previewPolicyMutation.isPending);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewPolicyMutation.isPending]);

  if (activePolicy && !isEditing) {
    return (
      <ScheduledPolicyCard
        policy={activePolicy}
        connectionName={connectionNameFor(activePolicy.connection_id)}
        onEdit={() => {
          applyPolicyToForm(activePolicy);
          setIsEditing(true);
        }}
        onPause={() => statusMutation.mutate(false)}
        onResume={() => statusMutation.mutate(true)}
        isTogglingStatus={statusMutation.isPending}
      />
    );
  }

  const requestError = previewMutation.error ?? runMutation.error ?? saveMutation.error ?? scopeQuery.error;

  return (
    <Paper id="autonomous-configure" variant="outlined" sx={{ p: 2.5, mb: 3, borderRadius: 2 }}>
      <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" gap={2} sx={{ mb: 2 }}>
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 900 }}>Configure Autonomous Analysis</Typography>
          <Typography variant="body2" color="text.secondary">Configure scope, preview planned metrics, then run once or schedule it to run automatically.</Typography>
        </Box>
        <Stack direction="row" gap={1} flexWrap="wrap">
          {activePolicy ? (
            <Button variant="text" onClick={() => setIsEditing(false)}>Cancel</Button>
          ) : null}
          <Button startIcon={<PreviewRoundedIcon />} variant="outlined" disabled={!selectedCategories.length || previewMutation.isPending} onClick={() => previewMutation.mutate()}>
            {previewMutation.isPending ? 'Previewing...' : 'Preview'}
          </Button>
          <Button startIcon={<PlayArrowRoundedIcon />} variant="outlined" disabled={!selectedCategories.length || runMutation.isPending} onClick={() => runMutation.mutate()}>
            {runMutation.isPending ? 'Running...' : 'Run once'}
          </Button>
          <Button
            variant="contained"
            disabled={!selectedCategories.length || saveMutation.isPending}
            onClick={() => saveMutation.mutate()}
          >
            {saveMutation.isPending ? 'Saving...' : scheduleMode === 'scheduled' ? 'Save & Schedule' : 'Save'}
          </Button>
        </Stack>
      </Stack>

      {requestError ? (
        <Alert severity="error" sx={{ mb: 2 }}>
          Autonomous request failed{requestError.message ? `: ${requestError.message}` : '. Check Prometheus configuration and backend logs.'}
        </Alert>
      ) : null}
      {runMutation.data ? <Alert severity="success" sx={{ mb: 2 }}>Run {runMutation.data.status}: {runMutation.data.executed_jobs} executed, {runMutation.data.failed_jobs} failed.</Alert> : null}
      {previewMutation.data ? (
        <Alert severity="info" sx={{ mb: 2 }}>
          {connectionNameFor(connectionId) ? `Preview of ${connectionNameFor(connectionId)}: found` : 'Preview found'} {previewMutation.data.metrics_discovered} metrics and planned {previewMutation.data.planned_jobs} jobs.
        </Alert>
      ) : null}
      {resultWarnings.length ? (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {resultWarnings.slice(0, MAX_SHOWN_WARNINGS).map((warning) => <div key={warning}>{warning}</div>)}
          {resultWarnings.length > MAX_SHOWN_WARNINGS ? <div>+{resultWarnings.length - MAX_SHOWN_WARNINGS} more warnings</div> : null}
        </Alert>
      ) : null}
      {saveMutation.isSuccess ? <Alert severity="success" sx={{ mb: 2 }}>{scheduleMode === 'scheduled' ? 'Scheduled - this policy will now run automatically.' : 'Saved.'}</Alert> : null}

      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: '1fr 1.4fr 1fr' }, gap: 2 }}>
        <Stack gap={1.2}>
          <Typography sx={{ fontWeight: 850 }}>1. Analysis Scope</Typography>
          {connections.length > 1 ? (
            <TextField
              select
              size="small"
              label="Prometheus connection"
              helperText="Which Prometheus / Mimir tenant to analyse."
              value={effectiveConnectionId}
              onChange={(e) => changeConnection(e.target.value)}
            >
              {connections.map((connection) => <MenuItem key={connection.id} value={connection.id}>{connection.name}</MenuItem>)}
            </TextField>
          ) : null}
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
          {(scopeQuery.data?.clusters ?? []).length > 1 || !allClusters ? (
            <>
              <FormControlLabel control={<Checkbox checked={allClusters} onChange={(e) => setAllClusters(e.target.checked)} />} label="All clusters" />
              <TextField
                select
                size="small"
                label="Clusters"
                helperText={`Each cluster is analysed separately (label "${scopeQuery.data?.cluster_label ?? 'cluster'}").`}
                SelectProps={{ multiple: true }}
                disabled={allClusters}
                value={selectedClusters}
                onChange={(e) => setSelectedClusters(typeof e.target.value === 'string' ? e.target.value.split(',') : e.target.value as string[])}
              >
                {(scopeQuery.data?.clusters ?? []).map((cluster) => <MenuItem key={cluster} value={cluster}>{cluster}</MenuItem>)}
              </TextField>
            </>
          ) : null}
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
          <Typography variant="caption" color="text.secondary">Mode</Typography>
          <Stack direction="row" gap={1}>
            <Chip
              label="One-time"
              color={scheduleMode === 'run_once' ? 'primary' : 'default'}
              variant={scheduleMode === 'run_once' ? 'filled' : 'outlined'}
              onClick={() => setScheduleMode('run_once')}
            />
            <Chip
              label="Scheduled"
              color={scheduleMode === 'scheduled' ? 'primary' : 'default'}
              variant={scheduleMode === 'scheduled' ? 'filled' : 'outlined'}
              onClick={() => setScheduleMode('scheduled')}
            />
          </Stack>
          {scheduleMode === 'scheduled' ? (
            <TextField select size="small" label="Run every" value={scheduleMinutes} onChange={(e) => setScheduleMinutes(Number(e.target.value))}>
              {schedulePresets.map((value) => <MenuItem key={value} value={value}>{formatSchedule(value)}</MenuItem>)}
            </TextField>
          ) : null}
          <TextField select size="small" label="Analysis window" value={analysisWindow} onChange={(e) => setAnalysisWindow(e.target.value)}>
            {['30m', '1h', '6h', '24h', '7d'].map((value) => <MenuItem key={value} value={value}>{value}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="Query resolution" value={executionInterval} onChange={(e) => setExecutionInterval(e.target.value)}>
            {['30s', '1m', '5m', '10m'].map((value) => <MenuItem key={value} value={value}>{value}</MenuItem>)}
          </TextField>
          <TextField size="small" type="number" label="Max metrics per run" value={maxMetricsPerRun} onChange={(e) => setMaxMetricsPerRun(e.target.value)} />
          <TextField
            size="small"
            type="number"
            label="Max parallel jobs"
            value={maxParallelJobs}
            onChange={(e) => setMaxParallelJobs(e.target.value)}
            helperText="Execution runs sequentially; reserved for future worker concurrency."
          />
        </Stack>
      </Box>
    </Paper>
  );
}
