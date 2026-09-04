import { useMemo, useState, type ReactNode } from 'react';
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Tab,
  Tabs,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import AddchartRoundedIcon from '@mui/icons-material/AddchartRounded';
import CableRoundedIcon from '@mui/icons-material/CableRounded';
import ContentCopyRoundedIcon from '@mui/icons-material/ContentCopyRounded';
import ErrorOutlineRoundedIcon from '@mui/icons-material/ErrorOutlineRounded';
import InsightsRoundedIcon from '@mui/icons-material/InsightsRounded';
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';
import QueryStatsRoundedIcon from '@mui/icons-material/QueryStatsRounded';
import RemoveRedEyeRoundedIcon from '@mui/icons-material/RemoveRedEyeRounded';
import SaveRoundedIcon from '@mui/icons-material/SaveRounded';
import ScheduleRoundedIcon from '@mui/icons-material/ScheduleRounded';
import StorageRoundedIcon from '@mui/icons-material/StorageRounded';
import UploadRoundedIcon from '@mui/icons-material/UploadRounded';
import WifiTetheringRoundedIcon from '@mui/icons-material/WifiTetheringRounded';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../api/queries';
import { panelSx, ui } from '../standalone/theme';
import type { AnalyzerExecution, CsvAnalyzerRoutingDecision, DirectPrometheusAnalysisResponse, PrometheusPreviewResponse, ValidationFinding, ValidationSignal } from '../types';

type Provider = 'generic' | 'prometheus' | 'datadog';
type Mode = 'csv' | 'prometheus';
type TimePreset = '1h' | '6h' | '24h' | '3d' | '7d' | 'custom';

const ANALYZER_OPTIONS = [
  { id: 'all', label: 'All (Router)' },
  { id: 'ruptures', label: 'Ruptures' },
  { id: 'stumpy', label: 'STUMPY' },
  { id: 'prophet', label: 'Prophet' },
  { id: 'baseline_shift', label: 'Baseline Shift' },
  { id: 'anomaly_zscore', label: 'Anomaly Z-Score' },
  { id: 'pyod_outlier', label: 'PyOD Outlier' },
  { id: 'trend', label: 'Trend' },
];

const PRESETS: Array<{ id: TimePreset; label: string; ms: number | null }> = [
  { id: '1h', label: 'Last 1 hour', ms: 60 * 60 * 1000 },
  { id: '6h', label: 'Last 6 hours', ms: 6 * 60 * 60 * 1000 },
  { id: '24h', label: 'Last 24 hours', ms: 24 * 60 * 60 * 1000 },
  { id: '3d', label: 'Last 3 days', ms: 3 * 24 * 60 * 60 * 1000 },
  { id: '7d', label: 'Last 7 days', ms: 7 * 24 * 60 * 60 * 1000 },
  { id: 'custom', label: 'Custom', ms: null },
];

const LAB_SCENARIOS = [
  { label: 'Baseline shift', service: 'ruptures-lab', metric: 'ops_signal_lab_value', analyzer: 'ruptures' },
  { label: 'Trend', service: 'trend-lab', metric: 'ops_signal_lab_value', analyzer: 'trend' },
  { label: 'Spike', service: 'spike-lab', metric: 'ops_signal_lab_value', analyzer: 'pyod_outlier' },
  { label: 'Seasonal', service: 'forecast-lab', metric: 'ops_signal_lab_value', analyzer: 'prophet' },
  { label: 'Mixed', service: 'mixed-lab', metric: 'ops_signal_lab_value', analyzer: 'baseline_shift' },
];
const LAB_SERVICE_NAMES = new Set(LAB_SCENARIOS.map((scenario) => scenario.service));

function isoForDatetimeLocal(value: Date) {
  const local = new Date(value.getTime() - value.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

function rangeForPreset(preset: TimePreset) {
  const selected = PRESETS.find((item) => item.id === preset);
  const end = new Date();
  const start = new Date(end.getTime() - (selected?.ms ?? 24 * 60 * 60 * 1000));
  return { start, end };
}

function parseStepMs(value: string) {
  const match = value.trim().toLowerCase().match(/^(\d+(?:\.\d+)?)([smhd]?)$/);
  if (!match) return null;
  const amount = Number(match[1]);
  const unit = match[2] || 's';
  const multipliers: Record<string, number> = { s: 1000, m: 60_000, h: 3_600_000, d: 86_400_000 };
  return amount * multipliers[unit];
}

function buildPromql(metric: string, service: string) {
  const trimmedMetric = metric.trim();
  const trimmedService = service.trim();
  if (!trimmedMetric || !trimmedService) return trimmedMetric;
  return `${trimmedMetric}{service="${trimmedService}"}`;
}

function formatRangeDate(value: Date | string | null | undefined) {
  if (!value) return 'n/a';
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return 'n/a';
  return date.toLocaleString(undefined, { month: '2-digit', day: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' });
}

function formatNumber(value: number | null | undefined) {
  return typeof value === 'number' ? value.toLocaleString() : 'n/a';
}

function minMaxAvg(preview: PrometheusPreviewResponse | null) {
  const values = preview?.series.flatMap((series) => series.samples.map((sample) => sample.value).filter((value): value is number => typeof value === 'number' && !Number.isNaN(value))) ?? [];
  if (!values.length) return { min: null, max: null, avg: null };
  const min = Math.min(...values);
  const max = Math.max(...values);
  const avg = values.reduce((total, value) => total + value, 0) / values.length;
  return { min, max, avg };
}

function FieldLabel({ children }: { children: string }) {
  return <Typography sx={{ fontSize: 13, fontWeight: 800, color: '#334155', mb: 0.8 }}>{children}</Typography>;
}

function SummaryRow({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={1.5}>
      <Stack direction="row" alignItems="center" spacing={1.2}>
        <Box sx={{ color: '#0f766e', display: 'flex' }}>{icon}</Box>
        <Typography sx={{ fontSize: 13, color: '#334155', fontWeight: 700 }}>{label}</Typography>
      </Stack>
      <Typography sx={{ fontSize: 13, color: ui.text, fontWeight: 850, textAlign: 'right' }}>{value}</Typography>
    </Stack>
  );
}

function routerBucketLabel(decision: CsvAnalyzerRoutingDecision) {
  const recommendation = String(decision.recommendation ?? '').toUpperCase();
  if (recommendation === 'RECOMMENDED') return 'Recommended';
  if (recommendation === 'OPTIONAL') return 'Optional';
  if (recommendation === 'REJECTED') return 'Rejected';
  return 'Not Recommended';
}

function executionChipSx(status?: string) {
  const normalized = String(status ?? 'skipped').toLowerCase();
  if (normalized === 'completed') return { bgcolor: '#dcfce7', color: '#166534', fontWeight: 850 };
  if (normalized === 'failed') return { bgcolor: '#fee2e2', color: '#991b1b', fontWeight: 850 };
  if (normalized === 'unavailable') return { bgcolor: '#fef3c7', color: '#92400e', fontWeight: 850 };
  return { bgcolor: '#f1f5f9', color: '#475569', fontWeight: 850 };
}

function RouterDecisionPanel({
  decisions,
  executions = [],
  executedAnalyzers = [],
}: {
  decisions: CsvAnalyzerRoutingDecision[];
  executions?: AnalyzerExecution[];
  executedAnalyzers?: string[];
}) {
  const buckets = ['Recommended', 'Optional', 'Not Recommended', 'Rejected'];
  const executionByAnalyzer = new Map(
    executions
      .filter((execution) => execution.router_analyzer_id)
      .map((execution) => [execution.router_analyzer_id as string, execution]),
  );
  const completedExecutions = executions.filter((execution) => execution.execution_status === 'completed');
  const failedExecutions = executions.filter((execution) => execution.execution_status === 'failed');
  const selectedSkippedExecutions = executions.filter(
    (execution) => execution.selected && execution.execution_status === 'skipped',
  );
  const executedLabel = executedAnalyzers.length
    ? executedAnalyzers.join(', ')
    : completedExecutions
      .flatMap((execution) => execution.executed_pipeline_analyzer_ids ?? [])
      .join(', ') || 'none';
  const hasExecutionSnapshots = executions.length > 0;
  return (
    <Card variant="outlined">
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="h6">Router Decisions</Typography>
          {decisions.length ? (
            <Box sx={{ border: '1px solid #bae6fd', bgcolor: '#ecfeff', borderRadius: '8px', px: 2, py: 1.5 }}>
              <Typography sx={{ fontSize: 13, color: '#0f766e', fontWeight: 850 }}>
                Executed analyzers: {executedLabel}
              </Typography>
              {!hasExecutionSnapshots ? (
                <Typography sx={{ fontSize: 12, color: '#92400e', mt: 0.5 }}>
                  Execution details were not returned for this run. Re-run analysis after backend/frontend restart to confirm selected vs skipped analyzers.
                </Typography>
              ) : null}
              {selectedSkippedExecutions.length ? (
                <Typography sx={{ fontSize: 12, color: '#0f766e', mt: 0.5 }}>
                  Recommended but not executed: {selectedSkippedExecutions.map((execution) => execution.display_name ?? execution.router_analyzer_id).join(', ')}.
                </Typography>
              ) : null}
              {failedExecutions.length ? (
                <Typography sx={{ fontSize: 12, color: ui.red, mt: 0.5 }}>
                  Failed analyzer executions: {failedExecutions.map((execution) => execution.display_name ?? execution.router_analyzer_id).join(', ')}.
                </Typography>
              ) : null}
            </Box>
          ) : null}
          {decisions.length === 0 ? (
            <Typography variant="body2" color="text.secondary">No router decisions returned yet.</Typography>
          ) : (
            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: 'repeat(4, 1fr)' }, gap: 2 }}>
              {buckets.map((bucket) => {
                const items = decisions.filter((decision) => routerBucketLabel(decision) === bucket);
                return (
                  <Card key={bucket} variant="outlined" sx={{ p: 1.5 }}>
                    <Stack spacing={1}>
                      <Typography sx={{ fontSize: 13, fontWeight: 900 }}>{bucket}</Typography>
                      {items.length === 0 ? (
                        <Typography variant="caption" color="text.secondary">None</Typography>
                      ) : items.map((decision) => {
                        const displayReason = decision.routing_reason ?? decision.explanation ?? decision.reasons?.[0];
                        const execution = decision.analyzer_id ? executionByAnalyzer.get(decision.analyzer_id) : undefined;
                        const ranIds = execution?.executed_pipeline_analyzer_ids ?? [];
                        const failedIds = execution?.failed_pipeline_analyzer_ids ?? [];
                        const executionStatus = execution?.execution_status ?? (hasExecutionSnapshots ? 'not selected' : 'unavailable');
                        return (
                          <Box key={`${bucket}-${decision.analyzer_id ?? decision.display_name}`} sx={{ borderTop: `1px solid ${ui.border}`, pt: 1 }}>
                            <Stack direction="row" spacing={0.8} flexWrap="wrap" alignItems="center">
                              <Chip size="small" label={decision.analyzer_id ?? decision.display_name ?? 'unknown'} />
                              <Chip size="small" variant="outlined" label={`score ${typeof decision.final_score === 'number' ? decision.final_score.toFixed(2) : 'n/a'}`} />
                              <Chip size="small" variant="outlined" label={decision.eligible ? 'eligible' : 'ineligible'} />
                              <Chip size="small" label={`execution ${executionStatus}`} sx={executionChipSx(executionStatus)} />
                              {ranIds.length ? (
                                <Chip size="small" variant="outlined" label={`ran ${ranIds.join(', ')}`} />
                              ) : null}
                              {failedIds.length ? (
                                <Chip size="small" variant="outlined" color="error" label={`failed ${failedIds.join(', ')}`} />
                              ) : null}
                            </Stack>
                            {displayReason ? (
                              <Typography sx={{ color: ui.muted, fontSize: 12, mt: 0.8 }}>{displayReason}</Typography>
                            ) : null}
                            {execution?.execution_reason ? (
                              <Typography sx={{ color: execution.execution_status === 'failed' ? ui.red : ui.muted, fontSize: 12, mt: 0.8 }}>
                                Execution: {execution.execution_reason}
                              </Typography>
                            ) : null}
                          </Box>
                        );
                      })}
                    </Stack>
                  </Card>
                );
              })}
            </Box>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}

function buildDataQualityMessage(result: DirectPrometheusAnalysisResponse | null) {
  if (!result) return null;
  const decisions = (result.analyzer_routing ?? []) as CsvAnalyzerRoutingDecision[];
  if (!decisions.length) return null;
  const allRejected = decisions.every((decision) => String(decision.recommendation ?? '').toUpperCase() === 'REJECTED');
  const reasonText = decisions.map((decision) => [
    decision.routing_reason,
    decision.explanation,
    ...(decision.reasons ?? []),
  ].filter(Boolean).join(' ')).join(' ').toLowerCase();
  const sampleRejected = reasonText.includes('needs at least') && reasonText.includes('valid samples');
  const qualityRejected = decisions.some((decision) => {
    const decisionReasonText = [
      decision.routing_reason,
      decision.explanation,
      ...(decision.reasons ?? []),
    ].filter(Boolean).join(' ').toLowerCase();
    return decisionReasonText.includes('missing') || decisionReasonText.includes('invalid values');
  });
  if (!allRejected || (!qualityRejected && !sampleRejected)) return null;

  const samples = result.series[0]?.samples ?? [];
  const missingCount = samples.filter((sample) => sample.value === null || Number.isNaN(Number(sample.value))).length;
  const missingPercentage = samples.length ? (missingCount / samples.length) * 100 : null;
  const validCount = samples.length - missingCount;
  return {
    kind: sampleRejected ? 'sample_count' : missingCount > 0 ? 'missing' : 'invalid',
    missingPercentage,
    validCount,
    analyzerCount: decisions.length,
  };
}

export function ValidateDataPage() {
  const [mode, setMode] = useState<Mode>('csv');
  const [provider, setProvider] = useState<Provider>('prometheus');
  const [analyzerId, setAnalyzerId] = useState('all');
  const [service, setService] = useState('ruptures-lab');
  const [metricName, setMetricName] = useState('ops_signal_lab_value');
  const [metricNames, setMetricNames] = useState<string[]>(['ops_signal_lab_value']);
  const [interval, setInterval] = useState('5m');
  const [file, setFile] = useState<File | null>(null);
  const [resultSignals, setResultSignals] = useState<ValidationSignal[]>([]);
  const [resultFindings, setResultFindings] = useState<ValidationFinding[]>([]);
  const [routerDecisions, setRouterDecisions] = useState<CsvAnalyzerRoutingDecision[]>([]);
  const [previewRows, setPreviewRows] = useState<Array<Record<string, unknown>>>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [queryMode, setQueryMode] = useState<'simple' | 'advanced'>('simple');
  const [promQuery, setPromQuery] = useState(buildPromql(metricName, service));
  const [timePreset, setTimePreset] = useState<TimePreset>('24h');
  const defaultRange = useMemo(() => rangeForPreset('24h'), []);
  const [customStart, setCustomStart] = useState(isoForDatetimeLocal(defaultRange.start));
  const [customEnd, setCustomEnd] = useState(isoForDatetimeLocal(defaultRange.end));
  const [step, setStep] = useState('5m');
  const [connectionId, setConnectionId] = useState('default');
  const [promPreview, setPromPreview] = useState<PrometheusPreviewResponse | null>(null);
  const [promResult, setPromResult] = useState<DirectPrometheusAnalysisResponse | null>(null);
  const [promResults, setPromResults] = useState<DirectPrometheusAnalysisResponse[]>([]);
  const [promMessage, setPromMessage] = useState<string | null>(null);
  const [promError, setPromError] = useState<string | null>(null);
  const [createdCases, setCreatedCases] = useState<Record<number, number>>({});

  const capabilitiesQuery = useQuery({ queryKey: ['capabilities'], queryFn: () => api.capabilities() });
  const connectionsQuery = useQuery({ queryKey: ['prometheus-connections'], queryFn: api.prometheusConnections });
  const connectionConfigured = connectionsQuery.data?.connections.find((connection) => connection.id === connectionId)?.configured ?? false;
  const serviceLabelsQuery = useQuery({
    queryKey: ['prometheus-label-values', connectionId, 'service'],
    queryFn: () => api.prometheusLabelValues('service', connectionId),
    enabled: mode === 'prometheus' && connectionConfigured,
  });
  const metricLabelsQuery = useQuery({
    queryKey: ['prometheus-label-values', connectionId, '__name__'],
    queryFn: () => api.prometheusLabelValues('__name__', connectionId),
    enabled: mode === 'prometheus' && connectionConfigured,
  });

  const analyzerOptions = useMemo(() => {
    const merged = new Map(ANALYZER_OPTIONS.map((option) => [option.id, option]));
    (capabilitiesQuery.data ?? [])
      .filter((capability) => capability.enabled && capability.analyzer_id !== 'not_installed')
      .forEach((capability) => {
        if (!merged.has(capability.analyzer_id)) {
          merged.set(capability.analyzer_id, { id: capability.analyzer_id, label: capability.title || capability.analyzer_id });
        }
      });
    return Array.from(merged.values());
  }, [capabilitiesQuery.data]);

  const selectedRange = useMemo(() => {
    if (timePreset !== 'custom') return rangeForPreset(timePreset);
    return { start: new Date(customStart), end: new Date(customEnd) };
  }, [customEnd, customStart, timePreset]);

  const selectedMetricNames = queryMode === 'simple' ? (metricNames.length ? metricNames : [metricName]).filter(Boolean) : [metricName].filter(Boolean);
  const effectiveQuery = queryMode === 'simple' ? buildPromql(selectedMetricNames[0] ?? metricName, service) : promQuery;
  const rangeValid = selectedRange.start instanceof Date && selectedRange.end instanceof Date && !Number.isNaN(selectedRange.start.getTime()) && !Number.isNaN(selectedRange.end.getTime()) && selectedRange.start < selectedRange.end;
  const suggestedLabService = service.replace(/_/g, '-');
  const likelyLabServiceTypo = service.includes('_') && LAB_SERVICE_NAMES.has(suggestedLabService);
  const estimatedSamples = useMemo(() => {
    const stepMs = parseStepMs(step);
    if (!rangeValid || !stepMs || stepMs <= 0) return null;
    return Math.floor((selectedRange.end.getTime() - selectedRange.start.getTime()) / stepMs) + 1;
  }, [rangeValid, selectedRange.end, selectedRange.start, step]);
  const belowRouterMinimum = typeof estimatedSamples === 'number' && estimatedSamples < 30;

  const csvMutation = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('Select a CSV file first');
      const form = new FormData();
      form.set('file', file);
      form.set('provider', provider);
      form.set('analyzer_id', analyzerId);
      form.set('service', service);
      form.set('metric_name', metricName);
      form.set('interval', interval);
      return api.runCsvValidation(form);
    },
    onSuccess: (result) => {
      setError(null);
      const modeLabel = result.analyzer_selection_mode === 'manual_override' ? 'manual analyzer override' : 'router';
      const executed = result.executed_analyzers?.length ? ` Executed: ${result.executed_analyzers.join(', ')}.` : '';
      setMessage(`Preview generated via ${modeLabel} with ${result.sample_count} samples.${executed}`);
      setResultSignals(result.signals);
      setResultFindings(result.findings);
      setRouterDecisions((result.analyzer_routing ?? []) as CsvAnalyzerRoutingDecision[]);
      setPreviewRows(result.normalized_preview);
    },
    onError: (err: unknown) => {
      setMessage(null);
      setError(err instanceof Error ? err.message : 'Validation failed');
    },
  });

  const testConnectionMutation = useMutation({
    mutationFn: () => api.testPrometheusConnection(connectionId),
    onSuccess: (result) => {
      setPromError(null);
      setPromMessage(result.available ? `${result.message}${result.version ? ` (${result.version})` : ''}` : result.message);
    },
    onError: (err: unknown) => {
      setPromMessage(null);
      setPromError(err instanceof Error ? err.message : 'Connection test failed');
    },
  });

  const previewMutation = useMutation({
    mutationFn: async () => {
      if (queryMode !== 'simple' || selectedMetricNames.length <= 1) {
        return api.previewPrometheus({
          connection_id: connectionId,
          query: effectiveQuery,
          start: selectedRange.start.toISOString(),
          end: selectedRange.end.toISOString(),
          step,
        });
      }
      const previews = await Promise.all(selectedMetricNames.map((metric) =>
        api.previewPrometheus({
          connection_id: connectionId,
          query: buildPromql(metric, service),
          start: selectedRange.start.toISOString(),
          end: selectedRange.end.toISOString(),
          step,
        })
      ));
      const sampleCount = previews.reduce((total, item) => total + item.sample_count, 0);
      const seriesCount = previews.reduce((total, item) => total + item.series_count, 0);
      return { ...previews[0], sample_count: sampleCount, series_count: seriesCount, warnings: previews.flatMap((item) => item.warnings) };
    },
    onSuccess: (result) => {
      setPromError(null);
      const metricText = queryMode === 'simple' && selectedMetricNames.length > 1 ? ` across ${selectedMetricNames.length} metrics` : '';
      setPromMessage(result.sample_count ? `Preview returned ${result.sample_count} samples across ${result.series_count} series${metricText}.` : 'The query succeeded, but Prometheus returned no samples for the selected time range.');
      setPromPreview(result);
    },
    onError: (err: unknown) => {
      setPromMessage(null);
      setPromPreview(null);
      setPromError(err instanceof Error ? err.message : 'Preview failed');
    },
  });

  const runPrometheusMutation = useMutation({
    mutationFn: async () => {
      if (queryMode !== 'simple' || selectedMetricNames.length <= 1) {
        return [await api.runPrometheusAnalysis({
          connection_id: connectionId,
          query: effectiveQuery,
          service,
          metric: metricName,
          start: selectedRange.start.toISOString(),
          end: selectedRange.end.toISOString(),
          step,
          analyzer: analyzerId,
          execution_mode: 'persist',
        })];
      }
      const results: DirectPrometheusAnalysisResponse[] = [];
      for (const metric of selectedMetricNames) {
        results.push(await api.runPrometheusAnalysis({
          connection_id: connectionId,
          query: buildPromql(metric, service),
          service,
          metric,
          start: selectedRange.start.toISOString(),
          end: selectedRange.end.toISOString(),
          step,
          analyzer: analyzerId,
          execution_mode: 'persist',
        }));
      }
      return results;
    },
    onSuccess: (results) => {
      setPromError(null);
      const ranked = [...results].sort((left, right) =>
        (right.findings_count - left.findings_count)
        || (right.signal_count - left.signal_count)
        || (right.sample_count - left.sample_count)
      );
      setPromResults(results);
      setPromResult(ranked[0] ?? null);
      const signalCount = results.reduce((total, item) => total + item.signal_count, 0);
      const findingCount = results.reduce((total, item) => total + item.findings_count, 0);
      setPromMessage(
        results.length > 1
          ? `${results.length} analysis runs created with ${signalCount} signals and ${findingCount} findings. Showing ${ranked[0]?.metric_name ?? 'top metric'} first.`
          : `Analysis run ${results[0]?.analysis_run_id ?? 'unknown'} created with ${results[0]?.signal_count ?? 0} signals and ${results[0]?.findings_count ?? 0} findings.`
      );
    },
    onError: (err: unknown) => {
      setPromMessage(null);
      setPromError(err instanceof Error ? err.message : 'Prometheus analysis failed');
    },
  });

  const createCaseMutation = useMutation({
    mutationFn: (findingId: number) => api.createCase(findingId),
    onSuccess: (result) => {
      setCreatedCases((current) => ({ ...current, [result.finding_id]: result.case_id }));
      setPromError(null);
      setPromMessage(`Case #${result.case_id} is ready for finding #${result.finding_id}.`);
    },
    onError: (err: unknown) => {
      setPromMessage(null);
      setPromError(err instanceof Error ? err.message : 'Could not create case');
    },
  });

  const chartData = (promPreview?.series[0]?.samples ?? []).slice(-80).map((sample) => ({
    time: new Date(sample.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    value: sample.value,
  }));
  const resultChartData = (promResult?.series[0]?.samples ?? []).slice(-160).map((sample) => ({
    time: new Date(sample.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    value: sample.value,
  }));

  const connectionVerified = testConnectionMutation.data?.available === true;
  const connectionLabel = connectionVerified ? 'Connected' : connectionConfigured ? 'Configured' : 'Not configured';
  const serviceOptions = serviceLabelsQuery.data?.values ?? [];
  const metricOptions = [
    ...['ops_signal_lab_value', 'cpu_usage', 'request_latency_p95', 'error_rate'].filter((item) => metricLabelsQuery.data?.values.includes(item)),
    ...(metricLabelsQuery.data?.values ?? []).filter((item) => !['ops_signal_lab_value', 'cpu_usage', 'request_latency_p95', 'error_rate'].includes(item)),
  ];
  const previewStats = minMaxAvg(promPreview);
  const previewSamples = promPreview?.series[0]?.samples ?? [];
  const firstSample = previewSamples[0]?.timestamp;
  const lastSample = previewSamples[previewSamples.length - 1]?.timestamp;
  const primaryFinding = promResult?.findings[0];
  const primarySignal = promResult?.signals[0];
  const dataQualityMessage = buildDataQualityMessage(promResult);

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <Box>
        <Stack direction="row" alignItems="center" spacing={1.2}>
          <InsightsRoundedIcon sx={{ color: '#0f766e' }} />
          <Typography variant="h4" sx={{ fontWeight: 900 }}>New Analysis</Typography>
        </Stack>
        <Typography variant="body2" color="text.secondary">Analyze time-series data from CSV uploads or direct Prometheus queries.</Typography>
      </Box>

      <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={2}>
        <Tabs
          value={mode}
          onChange={(_, value) => setMode(value)}
          sx={{
            minHeight: 48,
            border: `1px solid ${ui.border}`,
            borderRadius: '8px',
            bgcolor: '#fff',
            '& .MuiTabs-indicator': { display: 'none' },
            '& .MuiTab-root': { minHeight: 48, px: 3, textTransform: 'none', fontWeight: 850, color: '#334155' },
            '& .Mui-selected': { color: '#0f766e', bgcolor: '#ecfeff', boxShadow: 'inset 0 -2px 0 #0f766e' },
          }}
        >
          <Tab value="csv" icon={<UploadRoundedIcon fontSize="small" />} iconPosition="start" label="CSV Upload" />
          <Tab value="prometheus" icon={<StorageRoundedIcon fontSize="small" />} iconPosition="start" label="Prometheus" />
        </Tabs>
        {mode === 'prometheus' ? (
          <Button startIcon={<CableRoundedIcon />} variant="outlined" sx={{ display: { xs: 'none', md: 'inline-flex' }, height: 44, borderColor: '#b6d5dd', color: '#0f766e', textTransform: 'none', fontWeight: 850 }}>
            Saved Connections
          </Button>
        ) : null}
      </Stack>

      {mode === 'csv' ? (
        <Card variant="outlined">
          <CardContent>
            <Stack spacing={2}>
              <Typography variant="h6">CSV Upload</Typography>
              <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
                <FormControl fullWidth><InputLabel>Provider</InputLabel><Select value={provider} label="Provider" onChange={(e) => setProvider(e.target.value as Provider)}><MenuItem value="prometheus">Prometheus CSV</MenuItem><MenuItem value="datadog">Datadog CSV</MenuItem><MenuItem value="generic">Generic CSV</MenuItem></Select></FormControl>
                <FormControl fullWidth><InputLabel>Analyzer</InputLabel><Select value={analyzerId} label="Analyzer" onChange={(e) => setAnalyzerId(e.target.value)}>{analyzerOptions.map((option) => <MenuItem key={option.id} value={option.id}>{option.label}</MenuItem>)}</Select></FormControl>
                <TextField fullWidth label="Service" value={service} onChange={(e) => setService(e.target.value)} />
                <TextField fullWidth label="Metric" value={metricName} onChange={(e) => setMetricName(e.target.value)} />
                <TextField fullWidth label="Interval" value={interval} onChange={(e) => setInterval(e.target.value)} />
              </Stack>
              <Box><Button variant="outlined" component="label">{file ? `Selected: ${file.name}` : 'Choose CSV File'}<input hidden type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Button></Box>
              <Box><Button variant="contained" disabled={csvMutation.isPending || !file} onClick={() => { setMessage(null); setError(null); csvMutation.mutate(); }}>{csvMutation.isPending ? <CircularProgress size={20} color="inherit" /> : 'Validate Data'}</Button></Box>
              {message ? <Alert severity="success">{message}</Alert> : null}
              {error ? <Alert severity="error">{error}</Alert> : null}
            </Stack>
          </CardContent>
        </Card>
      ) : (
        <Card variant="outlined" sx={{ bgcolor: ui.surface, border: `1px solid ${ui.border}`, borderRadius: '8px', boxShadow: '0 18px 45px rgba(15, 23, 42, 0.06)', overflow: 'hidden' }}>
          <CardContent sx={{ p: 2.5 }}>
            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', xl: '1fr 300px' }, gap: 2.5 }}>
              <Stack spacing={2.2}>
                {!connectionConfigured ? <Alert severity="warning">Prometheus is not configured. Add OPS_SIGNALS_PROMETHEUS_URL and restart the backend.</Alert> : null}
                <Box>
                  <FieldLabel>Connection</FieldLabel>
                  <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}>
                    <FormControl fullWidth>
                      <Select size="small" value={connectionId} onChange={(e) => setConnectionId(e.target.value)} sx={{ height: 44, bgcolor: '#fff' }}>
                        {(connectionsQuery.data?.connections ?? [{ id: 'default', name: 'Default Prometheus', configured: false }]).map((connection) => (
                          <MenuItem key={connection.id} value={connection.id}>{connection.name}{connection.configured ? '' : ' (not configured)'}</MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                    <Chip label={connectionLabel} sx={{ height: 32, alignSelf: 'center', bgcolor: connectionVerified ? '#dcfce7' : connectionConfigured ? '#e0f2fe' : '#f8fafc', color: connectionVerified ? '#059669' : connectionConfigured ? '#0369a1' : '#64748b', fontWeight: 850 }} />
                    <Button startIcon={<WifiTetheringRoundedIcon />} variant="outlined" disabled={testConnectionMutation.isPending} onClick={() => testConnectionMutation.mutate()} sx={{ height: 44, minWidth: 170, borderColor: '#b6d5dd', color: '#0f766e', textTransform: 'none', fontWeight: 850 }}>
                      {testConnectionMutation.isPending ? <CircularProgress size={20} /> : 'Test Connection'}
                    </Button>
	                  </Stack>
	                </Box>

	                <Box>
	                  <FieldLabel>Lab Scenarios</FieldLabel>
	                  <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
	                    {LAB_SCENARIOS.map((scenario) => {
	                      const selected = service === scenario.service && metricName === scenario.metric && analyzerId === scenario.analyzer;
	                      return (
	                        <Chip
	                          key={scenario.label}
	                          label={`${scenario.label}: ${scenario.service}`}
	                          clickable
	                          color={selected ? 'primary' : 'default'}
	                          variant={selected ? 'filled' : 'outlined'}
	                          onClick={() => {
	                            setService(scenario.service);
	                            setMetricName(scenario.metric);
	                            setMetricNames([scenario.metric]);
	                            setAnalyzerId(scenario.analyzer);
	                            setQueryMode('simple');
	                            setPromQuery(buildPromql(scenario.metric, scenario.service));
	                            setPromPreview(null);
	                            setPromResult(null);
	                          }}
	                          sx={{ fontWeight: 800, borderColor: selected ? undefined : '#b6d5dd', bgcolor: selected ? '#009688' : '#fff', color: selected ? '#fff' : '#0f766e' }}
	                        />
	                      );
	                    })}
	                  </Stack>
	                  <Typography sx={{ mt: 0.8, color: ui.muted, fontSize: 12 }}>
	                    Lab scenarios are Prometheus service labels. Analyzer controls choose which detector runs.
	                  </Typography>
	                </Box>

	                <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(4, 1fr)' }, gap: 1.5 }}>
	                  <Box><FieldLabel>Query Mode</FieldLabel><FormControl fullWidth><Select size="small" value={queryMode} onChange={(e) => setQueryMode(e.target.value as 'simple' | 'advanced')} sx={{ height: 44 }}><MenuItem value="simple">Simple</MenuItem><MenuItem value="advanced">Advanced PromQL</MenuItem></Select></FormControl></Box>
	                  <Box>
	                    <FieldLabel>Service</FieldLabel>
	                    <Autocomplete
	                      freeSolo
	                      size="small"
	                      options={serviceOptions}
	                      value={service}
	                      loading={serviceLabelsQuery.isLoading}
	                      onInputChange={(_, value) => {
	                        setService(value);
	                        if (queryMode === 'simple') setPromQuery(buildPromql(metricName, value));
	                      }}
	                      renderInput={(params) => <TextField {...params} placeholder={serviceLabelsQuery.error ? 'Type service manually' : 'Select or type service'} />}
	                    />
	                  </Box>
	                  <Box>
	                    <FieldLabel>{queryMode === 'simple' ? 'Metrics' : 'Metric'}</FieldLabel>
	                    <Autocomplete
                        multiple={queryMode === 'simple'}
	                      freeSolo
	                      size="small"
	                      options={metricOptions}
	                      value={queryMode === 'simple' ? metricNames : metricName}
	                      loading={metricLabelsQuery.isLoading}
	                      onChange={(_, value) => {
                          if (queryMode !== 'simple') return;
                          const next = Array.isArray(value) ? value.map(String).filter(Boolean) : [];
                          setMetricNames(next);
                          setMetricName(next[0] ?? '');
                          setPromQuery(buildPromql(next[0] ?? '', service));
                          setPromPreview(null);
                          setPromResult(null);
                          setPromResults([]);
                        }}
	                      onInputChange={(_, value) => {
                          if (queryMode === 'simple') return;
                          setMetricName(value);
	                        setPromQuery(buildPromql(value, service));
	                      }}
	                      renderInput={(params) => <TextField {...params} placeholder={metricLabelsQuery.error ? 'Type metric manually' : 'Select or type metric'} />}
	                    />
	                  </Box>
	                  <Box><FieldLabel>Analyzer</FieldLabel><FormControl fullWidth><Select size="small" value={analyzerId} onChange={(e) => setAnalyzerId(e.target.value)} sx={{ height: 44 }}>{analyzerOptions.map((option) => <MenuItem key={option.id} value={option.id}>{option.label}</MenuItem>)}</Select></FormControl></Box>
	                </Box>

	                <Box>
	                  <FieldLabel>PromQL (auto-generated, editable)</FieldLabel>
	                  <TextField
	                    fullWidth
	                    value={effectiveQuery}
	                    onChange={(e) => { setQueryMode('advanced'); setPromQuery(e.target.value); }}
	                    multiline
	                    minRows={2}
	                    inputProps={{ 'aria-label': 'PromQL' }}
                    InputProps={{
                      endAdornment: <ContentCopyRoundedIcon sx={{ color: '#64748b', alignSelf: 'center' }} />,
                      sx: { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace', color: '#075985', fontWeight: 750 },
                    }}
                  />
                </Box>

	                <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(4, 1fr)' }, gap: 1.5 }}>
	                  <Box><FieldLabel>Time Window</FieldLabel><FormControl fullWidth><Select size="small" value={timePreset} onChange={(e) => setTimePreset(e.target.value as TimePreset)} sx={{ height: 44 }}>{PRESETS.map((preset) => <MenuItem key={preset.id} value={preset.id}>{preset.label}</MenuItem>)}</Select></FormControl></Box>
	                  <Box><FieldLabel>Start</FieldLabel><TextField size="small" fullWidth type="datetime-local" disabled={timePreset !== 'custom'} value={customStart} onChange={(e) => setCustomStart(e.target.value)} /></Box>
	                  <Box><FieldLabel>End</FieldLabel><TextField size="small" fullWidth type="datetime-local" disabled={timePreset !== 'custom'} value={customEnd} onChange={(e) => setCustomEnd(e.target.value)} /></Box>
                  <Box><FieldLabel>Step / Interval</FieldLabel><TextField size="small" fullWidth value={step} onChange={(e) => setStep(e.target.value)} /></Box>
                </Box>

                <Box sx={{ px: 1.4, py: 1.1, borderRadius: '8px', bgcolor: '#ecfeff', color: '#0f766e', fontSize: 13, fontWeight: 750 }}>
                  Request range: {rangeValid ? `${selectedRange.start.toISOString()} -> ${selectedRange.end.toISOString()} (${step} step)` : 'Start must be before end.'}
                  {typeof estimatedSamples === 'number' ? ` Estimated samples: ${estimatedSamples}.` : ''}
                </Box>

                {belowRouterMinimum ? (
                  <Alert severity="warning">
                    Router requires at least 30 samples. Increase the time window or reduce the step before running analysis.
                  </Alert>
                ) : null}
                {likelyLabServiceTypo ? (
                  <Alert severity="warning">
                    Did you mean <strong>{suggestedLabService}</strong>? Lab service labels use hyphens, not underscores.
                  </Alert>
                ) : null}

                <Stack direction="row" spacing={1.5}>
                  <Button startIcon={<RemoveRedEyeRoundedIcon />} variant="outlined" disabled={!connectionConfigured || !rangeValid || previewMutation.isPending} onClick={() => previewMutation.mutate()} sx={{ height: 44, borderColor: '#b6d5dd', color: '#0f766e', textTransform: 'none', fontWeight: 850 }}>
                    {previewMutation.isPending ? <CircularProgress size={20} /> : 'Preview Data'}
                  </Button>
                  <Button startIcon={<PlayArrowRoundedIcon />} variant="contained" disabled={!connectionConfigured || !rangeValid || belowRouterMinimum || runPrometheusMutation.isPending} onClick={() => runPrometheusMutation.mutate()} sx={{ height: 44, bgcolor: '#009688', textTransform: 'none', fontWeight: 850, boxShadow: '0 12px 22px rgba(0,150,136,0.22)' }}>
                    {runPrometheusMutation.isPending ? <CircularProgress size={20} color="inherit" /> : 'Run Analysis'}
                  </Button>
                </Stack>
                {promMessage ? <Alert severity="success">{promMessage}</Alert> : null}
                {promError ? <Alert severity="error">{promError}</Alert> : null}
              </Stack>

              <Box sx={{ border: `1px solid ${ui.border}`, borderRadius: '8px', p: 2, bgcolor: '#fbfdff' }}>
                <Typography sx={{ fontSize: 14, fontWeight: 900, mb: 0.3 }}>Preview Summary</Typography>
                <Typography sx={{ fontSize: 12, color: ui.muted, mb: 2 }}>{timePreset === 'custom' ? 'Custom range' : PRESETS.find((preset) => preset.id === timePreset)?.label}</Typography>
                <Box sx={{ height: 86, border: `1px solid ${ui.border}`, borderRadius: '6px', mb: 2, bgcolor: '#fff' }}>
	                  {chartData.length ? (
	                    <ResponsiveContainer><LineChart data={chartData}><Tooltip /><Line type="monotone" dataKey="value" stroke="#009688" dot={false} strokeWidth={2} /></LineChart></ResponsiveContainer>
	                  ) : (
	                    <Stack alignItems="center" justifyContent="center" sx={{ height: '100%', color: ui.muted, fontSize: 12 }}>Preview data appears here</Stack>
	                  )}
	                </Box>
                <Stack spacing={1.45}>
                  <SummaryRow icon={<QueryStatsRoundedIcon fontSize="small" />} label="Series Returned" value={formatNumber(promPreview?.series_count)} />
                  <SummaryRow icon={<AddchartRoundedIcon fontSize="small" />} label="Sample Count" value={formatNumber(promPreview?.sample_count)} />
                  <SummaryRow icon={<ScheduleRoundedIcon fontSize="small" />} label="Start (UTC)" value={formatRangeDate(firstSample ?? selectedRange.start)} />
                  <SummaryRow icon={<ScheduleRoundedIcon fontSize="small" />} label="End (UTC)" value={formatRangeDate(lastSample ?? selectedRange.end)} />
                  <SummaryRow icon={<ScheduleRoundedIcon fontSize="small" />} label="Step" value={step} />
                  <SummaryRow icon={<InsightsRoundedIcon fontSize="small" />} label="Min Value" value={previewStats.min == null ? 'n/a' : previewStats.min.toFixed(2)} />
                  <SummaryRow icon={<InsightsRoundedIcon fontSize="small" />} label="Max Value" value={previewStats.max == null ? 'n/a' : previewStats.max.toFixed(2)} />
                  <SummaryRow icon={<InsightsRoundedIcon fontSize="small" />} label="Avg Value" value={previewStats.avg == null ? 'n/a' : previewStats.avg.toFixed(2)} />
                </Stack>
                <Alert severity="info" sx={{ mt: 2, py: 0.5 }}>Preview shows up to 80 chart points.</Alert>
              </Box>
            </Box>
	          </CardContent>
	        </Card>
	      )}

	      {mode === 'prometheus' ? (
	        <>
	          <Card variant="outlined" sx={panelSx}>
	            <CardContent sx={{ p: 2 }}>
	              <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: 'repeat(3, 1fr)' }, gap: 2 }}>
	                <Stack direction="row" spacing={1.4}>
	                  <Box sx={{ color: '#0f766e', display: 'flex', pt: 0.2 }}><QueryStatsRoundedIcon /></Box>
	                  <Box>
	                    <Typography sx={{ fontSize: 14, fontWeight: 900, color: ui.text }}>Direct Prometheus</Typography>
	                    <Typography sx={{ fontSize: 13, color: ui.muted, mt: 0.4 }}>Queries Prometheus API directly from the Ops Signals backend.</Typography>
	                  </Box>
	                </Stack>
	                <Stack direction="row" spacing={1.4}>
	                  <Box sx={{ color: '#334155', display: 'flex', pt: 0.2 }}><SaveRoundedIcon /></Box>
	                  <Box>
	                    <Typography sx={{ fontSize: 14, fontWeight: 900, color: ui.text }}>Preview Is Read-Only</Typography>
	                    <Typography sx={{ fontSize: 13, color: ui.muted, mt: 0.4 }}>Preview does not save results. Run Analysis persists the analysis output.</Typography>
	                  </Box>
	                </Stack>
	                <Stack direction="row" spacing={1.4}>
	                  <Box sx={{ color: '#334155', display: 'flex', pt: 0.2 }}><ErrorOutlineRoundedIcon /></Box>
	                  <Box>
	                    <Typography sx={{ fontSize: 14, fontWeight: 900, color: ui.text }}>Limits & Safeguards</Typography>
	                    <Typography sx={{ fontSize: 13, color: ui.muted, mt: 0.4 }}>Large requests are bounded by the backend for predictable performance.</Typography>
	                  </Box>
	                </Stack>
	              </Box>
	            </CardContent>
	          </Card>
	          <Box sx={{ border: '1px solid #bae6fd', bgcolor: '#ecfeff', borderRadius: '8px', px: 2, py: 1.5 }}>
	            <Typography sx={{ fontSize: 13, color: '#0f766e', fontWeight: 750 }}>
	              Tip: Use Preview Data to validate your query and time range before running a full analysis.
	            </Typography>
	          </Box>
	        </>
	      ) : null}

	      {mode === 'prometheus' && promPreview ? (
	        <Card variant="outlined">
          <CardContent>
            <Stack spacing={2}>
              <Typography variant="h6">Prometheus Preview</Typography>
              <Stack direction="row" spacing={1} flexWrap="wrap">
                <Chip label={`${promPreview.series_count} series`} />
                <Chip label={`${promPreview.sample_count} samples`} />
                <Chip label={`step ${promPreview.step}`} />
                <Chip label={`${promPreview.start} to ${promPreview.end}`} />
              </Stack>
              {promPreview.warnings.map((warning) => <Alert key={warning} severity="warning">{warning}</Alert>)}
              {chartData.length ? <Box sx={{ height: 220 }}><ResponsiveContainer><LineChart data={chartData}><XAxis dataKey="time" /><YAxis /><Tooltip /><Line type="monotone" dataKey="value" stroke="#4f46e5" dot={false} strokeWidth={2} /></LineChart></ResponsiveContainer></Box> : <Typography color="text.secondary">No samples returned for this range.</Typography>}
              <Typography variant="body2" color="text.secondary">Selected series labels: {JSON.stringify(promPreview.series[0]?.labels ?? {})}</Typography>
            </Stack>
          </CardContent>
        </Card>
      ) : null}

	      {mode === 'prometheus' && promResult ? (
	        <Card variant="outlined" sx={panelSx}>
	          <CardContent sx={{ p: 2.5 }}>
	            <Stack spacing={2.2}>
	              <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={1.5}>
	                <Box>
	                  <Typography sx={{ fontSize: 20, fontWeight: 900, color: ui.text }}>What Ops Signals Found</Typography>
	                  <Typography sx={{ color: ui.muted, fontSize: 13, mt: 0.4 }}>Run {promResult.analysis_run_id} · {promResult.metric_name} · {promResult.service}</Typography>
	                </Box>
	                <Stack direction="row" spacing={1} flexWrap="wrap">
	                  <Chip size="small" label={`${promResult.sample_count} samples`} />
	                  <Chip size="small" label={`${promResult.signal_count} signals`} />
	                  <Chip size="small" label={`${promResult.findings_count} findings`} />
                    {promResults.length > 1 ? <Chip size="small" label={`${promResults.length} metrics analyzed`} /> : null}
	                </Stack>
	              </Stack>

                {promResults.length > 1 ? (
                  <Box sx={{ border: `1px solid ${ui.border}`, borderRadius: '8px', p: 1.4, bgcolor: '#fbfdff' }}>
                    <Typography sx={{ fontWeight: 900, color: ui.text, mb: 1 }}>Metric Results</Typography>
                    <Stack direction="row" spacing={1} flexWrap="wrap">
                      {promResults.map((result) => (
                        <Chip
                          key={result.analysis_run_id}
                          clickable
                          color={result.analysis_run_id === promResult.analysis_run_id ? 'primary' : 'default'}
                          label={`${result.metric_name}: ${result.findings_count} findings, ${result.signal_count} signals`}
                          onClick={() => setPromResult(result)}
                          sx={{ fontWeight: 800 }}
                        />
                      ))}
                    </Stack>
                  </Box>
                ) : null}

	              <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: '1.45fr 0.9fr' }, gap: 2 }}>
	                <Box sx={{ border: `1px solid ${ui.border}`, borderRadius: '8px', p: 2, bgcolor: '#fbfdff' }}>
	                  <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
	                    <Typography sx={{ fontWeight: 900, color: ui.text }}>Analyzed Time Series</Typography>
	                    <Typography sx={{ color: ui.muted, fontSize: 12 }}>{formatRangeDate(promResult.actual_start)} - {formatRangeDate(promResult.actual_end)}</Typography>
	                  </Stack>
	                  {resultChartData.length ? (
	                    <Box sx={{ height: 260 }}>
	                      <ResponsiveContainer width="100%" height="100%">
	                        <LineChart data={resultChartData}>
	                          <XAxis dataKey="time" tickLine={false} axisLine={false} />
	                          <YAxis tickLine={false} axisLine={false} width={48} />
	                          <Tooltip />
	                          <Line type="monotone" dataKey="value" stroke="#009688" dot={false} strokeWidth={2.5} />
	                        </LineChart>
	                      </ResponsiveContainer>
	                    </Box>
	                  ) : (
	                    <Stack alignItems="center" justifyContent="center" sx={{ height: 260, color: ui.muted }}>No samples returned with this analysis result.</Stack>
	                  )}
	                </Box>

	                <Box sx={{ border: `1px solid ${ui.border}`, borderRadius: '8px', p: 2, bgcolor: '#fff' }}>
	                  <Typography sx={{ fontWeight: 900, color: ui.text, mb: 1.5 }}>Finding Summary</Typography>
	                  {primaryFinding ? (
	                    <Stack spacing={1.4}>
	                      <Stack direction="row" spacing={1} flexWrap="wrap">
	                        <Chip size="small" label={primaryFinding.health_status} sx={{ bgcolor: '#fff1f2', color: ui.red, fontWeight: 800 }} />
	                        <Chip size="small" label={primaryFinding.category} />
	                        <Chip size="small" label={`priority ${primaryFinding.investigation_priority}`} />
	                      </Stack>
	                      <Typography sx={{ fontSize: 17, fontWeight: 900, color: ui.text }}>{primaryFinding.title}</Typography>
	                      <Typography sx={{ color: '#475569', fontSize: 14, lineHeight: 1.55 }}>{primaryFinding.summary}</Typography>
                        {primaryFinding.id ? (
                          <Stack direction="row" spacing={1}>
                            {createdCases[primaryFinding.id] ? (
                              <Button size="small" variant="contained" href={`/cases/${createdCases[primaryFinding.id]}`} sx={{ bgcolor: '#009688', textTransform: 'none', fontWeight: 850 }}>
                                Open Case #{createdCases[primaryFinding.id]}
                              </Button>
                            ) : (
                              <Button
                                size="small"
                                variant="contained"
                                disabled={createCaseMutation.isPending}
                                onClick={() => createCaseMutation.mutate(primaryFinding.id as number)}
                                sx={{ bgcolor: '#009688', textTransform: 'none', fontWeight: 850 }}
                              >
                                {createCaseMutation.isPending ? 'Creating...' : 'Create Case'}
                              </Button>
                            )}
                          </Stack>
                        ) : null}
	                    </Stack>
	                  ) : (
	                    <Typography color="text.secondary">No findings were emitted for this run.</Typography>
	                  )}
	                  {primarySignal ? (
	                    <Box sx={{ mt: 2, pt: 2, borderTop: `1px solid ${ui.border}` }}>
	                      <Typography sx={{ fontWeight: 850, color: ui.text, mb: 0.7 }}>Primary Signal</Typography>
	                      <Typography sx={{ color: '#475569', fontSize: 14 }}>{primarySignal.summary ?? primarySignal.signal_type}</Typography>
	                      <Typography sx={{ color: ui.muted, fontSize: 12, mt: 0.8 }}>{primarySignal.analyzer_id ?? 'unknown analyzer'} · confidence {typeof primarySignal.confidence === 'number' ? primarySignal.confidence.toFixed(2) : 'n/a'}</Typography>
	                    </Box>
	                  ) : null}
	                </Box>
	              </Box>

	              {dataQualityMessage ? (
	                <Alert severity="warning">
	                  <Typography sx={{ fontWeight: 900 }}>
	                    {dataQualityMessage.kind === 'sample_count'
	                      ? `Data quality failed: only ${dataQualityMessage.validCount} valid samples returned.`
	                      : dataQualityMessage.kind === 'missing' && dataQualityMessage.missingPercentage !== null
	                        ? `Data quality failed: ${dataQualityMessage.missingPercentage.toFixed(2)}% missing values.`
	                        : 'Data quality failed: router rejected the series because values were missing or invalid.'}
	                  </Typography>
	                  <Typography sx={{ mt: 0.5 }}>
	                    {dataQualityMessage.kind === 'sample_count'
	                      ? 'Router skipped all analyzers because the selected window did not return enough valid samples. Try a denser or wider time window, or refresh/restart mock Prometheus data.'
	                      : 'Router skipped all analyzers. Try a shorter time window or refresh/restart mock Prometheus data.'}
	                  </Typography>
	                </Alert>
	              ) : null}

	              <RouterDecisionPanel
	                decisions={(promResult.analyzer_routing ?? []) as CsvAnalyzerRoutingDecision[]}
	                executions={promResult.analyzer_executions ?? []}
	                executedAnalyzers={promResult.executed_analyzers ?? []}
	              />

	              {promResult.signal_count === 0 && !dataQualityMessage && !promResult.analyzer_executions?.length ? (
	                <Alert severity="info">
	                  No signals crossed analyzer thresholds for this Prometheus window. Executed analyzers: {promResult.executed_analyzers.length ? promResult.executed_analyzers.join(', ') : 'none'}.
	                </Alert>
	              ) : null}

	              {promResult.findings.length > 1 || promResult.signals.length > 1 ? (
	                <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: '1fr 1fr' }, gap: 2 }}>
	                  <Box>
	                    <Typography sx={{ fontWeight: 900, color: ui.text, mb: 1 }}>All Findings</Typography>
	                    <Stack spacing={1}>
	                      {promResult.findings.map((finding) => (
	                        <Box key={`${finding.id ?? finding.title}`} sx={{ border: `1px solid ${ui.border}`, borderRadius: '8px', p: 1.4 }}>
                            <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={1.2}>
                              <Box>
	                              <Typography sx={{ fontWeight: 850 }}>{finding.title}</Typography>
	                              <Typography sx={{ color: ui.muted, fontSize: 13 }}>{finding.category} · {finding.health_status}</Typography>
                              </Box>
                              {finding.id ? (
                                createdCases[finding.id] ? (
                                  <Button size="small" variant="outlined" href={`/cases/${createdCases[finding.id]}`} sx={{ textTransform: 'none', fontWeight: 850, alignSelf: { xs: 'flex-start', sm: 'center' } }}>
                                    Open Case
                                  </Button>
                                ) : (
                                  <Button
                                    size="small"
                                    variant="outlined"
                                    disabled={createCaseMutation.isPending}
                                    onClick={() => createCaseMutation.mutate(finding.id as number)}
                                    sx={{ textTransform: 'none', fontWeight: 850, alignSelf: { xs: 'flex-start', sm: 'center' } }}
                                  >
                                    Create Case
                                  </Button>
                                )
                              ) : null}
                            </Stack>
	                        </Box>
	                      ))}
	                    </Stack>
	                  </Box>
	                  <Box>
	                    <Typography sx={{ fontWeight: 900, color: ui.text, mb: 1 }}>Signals</Typography>
	                    <Stack spacing={1}>
	                      {promResult.signals.map((signal) => (
	                        <Box key={signal.id} sx={{ border: `1px solid ${ui.border}`, borderRadius: '8px', p: 1.4 }}>
	                          <Typography sx={{ fontWeight: 850 }}>{signal.summary ?? signal.signal_type}</Typography>
	                          <Typography sx={{ color: ui.muted, fontSize: 13 }}>{signal.analyzer_id ?? 'unknown'} · {signal.severity ?? 'n/a'}</Typography>
	                        </Box>
	                      ))}
	                    </Stack>
	                  </Box>
	                </Box>
	              ) : null}
	            </Stack>
	          </CardContent>
	        </Card>
	      ) : null}

      {mode === 'csv' && previewRows.length > 0 ? (
        <Card variant="outlined">
          <CardContent>
            <Stack spacing={2}>
              <Typography variant="h6">Normalized Preview</Typography>
              <Box sx={{ overflowX: 'auto' }}>
                <Table size="small">
                  <TableHead><TableRow>{Object.keys(previewRows[0] ?? {}).map((key) => <TableCell key={key}>{key}</TableCell>)}</TableRow></TableHead>
                  <TableBody>{previewRows.slice(0, 10).map((row, index) => <TableRow key={index}>{Object.values(row).map((value, valueIndex) => <TableCell key={valueIndex}>{typeof value === 'object' ? JSON.stringify(value) : String(value ?? '')}</TableCell>)}</TableRow>)}</TableBody>
                </Table>
              </Box>
            </Stack>
          </CardContent>
        </Card>
      ) : null}

      {mode === 'csv' ? (
        <>
          <RouterDecisionPanel decisions={routerDecisions} />
          <Card variant="outlined"><CardContent><Stack spacing={2}><Typography variant="h6">Signals</Typography>{resultSignals.length === 0 ? <Typography variant="body2" color="text.secondary">No signals returned yet.</Typography> : resultSignals.map((signal) => <Card key={signal.signal_id} variant="outlined" sx={{ p: 2 }}><Stack spacing={1}><Stack direction="row" spacing={1} flexWrap="wrap"><Chip label={signal.signal_type} size="small" /><Chip label={signal.severity} size="small" /><Chip label={signal.analyzer_id} size="small" /></Stack><Typography variant="subtitle1">{signal.summary}</Typography><Typography variant="body2" color="text.secondary">{signal.metric_name} · {signal.service ?? 'n/a'} · confidence {signal.confidence.toFixed(2)}</Typography></Stack></Card>)}</Stack></CardContent></Card>
          <Card variant="outlined"><CardContent><Stack spacing={2}><Typography variant="h6">Findings</Typography>{resultFindings.length === 0 ? <Typography variant="body2" color="text.secondary">No findings returned yet.</Typography> : resultFindings.map((finding) => <Card key={`${finding.metric_name}-${finding.title}`} variant="outlined" sx={{ p: 2 }}><Stack spacing={1}><Stack direction="row" spacing={1} flexWrap="wrap"><Chip label={finding.health_status} size="small" /><Chip label={finding.category} size="small" /></Stack><Typography variant="subtitle1">{finding.title}</Typography><Typography variant="body2" color="text.secondary">{finding.summary}</Typography><Typography variant="caption" color="text.secondary">Importance {finding.importance_score.toFixed(2)} · Priority {finding.investigation_priority}</Typography></Stack></Card>)}</Stack></CardContent></Card>
        </>
      ) : null}
    </Box>
  );
}
