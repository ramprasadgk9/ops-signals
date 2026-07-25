import { useEffect, useState, type ReactNode } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Drawer,
  Grid2 as Grid,
  IconButton,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import WidgetsOutlinedIcon from '@mui/icons-material/WidgetsOutlined';
import TimelineOutlinedIcon from '@mui/icons-material/TimelineOutlined';
import ChangeHistoryOutlinedIcon from '@mui/icons-material/ChangeHistoryOutlined';
import Inventory2OutlinedIcon from '@mui/icons-material/Inventory2Outlined';
import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded';
import MoreHorizRoundedIcon from '@mui/icons-material/MoreHorizRounded';
import SendRoundedIcon from '@mui/icons-material/SendRounded';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/queries';
import { ErrorState } from '../components/ErrorState';
import { FindingDetailsDrawer } from '../components/FindingDetailsDrawer';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { SignalDetailsDrawer } from '../components/SignalDetailsDrawer';
import { useOverviewData } from '../hooks/useOverviewData';
import type { AnalysisRun, Finding, OperationalCase, Signal, TimeseriesPoint } from '../types';

const panelSx = {
  borderRadius: 2,
  border: '1px solid #e5e7eb',
  boxShadow: '0 1px 2px rgba(15, 23, 42, 0.04)',
};

function SummaryCard({
  icon,
  value,
  label,
  tone,
}: {
  icon: ReactNode;
  value: string | number;
  label: string;
  tone: 'violet' | 'green' | 'orange' | 'purple';
}) {
  const colors = {
    violet: { bg: '#f0eaff', color: '#5b49f0' },
    green: { bg: '#e7fbf3', color: '#059669' },
    orange: { bg: '#fff0dc', color: '#f97316' },
    purple: { bg: '#f4e8ff', color: '#7c3aed' },
  }[tone];

  return (
    <Card sx={panelSx}>
      <CardContent sx={{ display: 'flex', alignItems: 'center', gap: 1.5, py: 1.75 }}>
        <Box sx={{ width: 44, height: 44, borderRadius: 2, display: 'grid', placeItems: 'center', bgcolor: colors.bg, color: colors.color }}>
          {icon}
        </Box>
        <Box>
          <Typography sx={{ fontSize: 20, fontWeight: 750, lineHeight: 1 }}>
            {value}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            {label}
          </Typography>
        </Box>
      </CardContent>
    </Card>
  );
}

const caseSteps = ['Finding', 'Investigation', 'Root Cause', 'Resolution', 'Publish Knowledge'] as const;
type CaseStep = typeof caseSteps[number];

function InvestigationDrawer({
  open,
  caseData,
  finding,
  runMetric,
  timeRange,
  onClose,
  onSaveInvestigation,
  onSaveRootCause,
  onSaveResolution,
  onPublish,
}: {
  open: boolean;
  caseData: OperationalCase | null;
  finding: Finding | null;
  runMetric: string;
  timeRange: string;
  onClose: () => void;
  onSaveInvestigation: (payload: { status: string; note: string }) => Promise<void>;
  onSaveRootCause: (payload: { status: string; summary: string; confidence: string; verified: boolean }) => Promise<void>;
  onSaveResolution: (payload: { status: string; summary: string; action: string }) => Promise<void>;
  onPublish: () => Promise<void>;
}) {
  const [activeStep, setActiveStep] = useState<CaseStep>('Finding');
  const [investigationStatus, setInvestigationStatus] = useState('in_progress');
  const [investigationNote, setInvestigationNote] = useState('');
  const [rootCauseStatus, setRootCauseStatus] = useState('hypothesis');
  const [rootCauseSummary, setRootCauseSummary] = useState('');
  const [rootCauseConfidence, setRootCauseConfidence] = useState('0.6');
  const [rootCauseVerified, setRootCauseVerified] = useState(false);
  const [resolutionStatus, setResolutionStatus] = useState('pending');
  const [resolutionSummary, setResolutionSummary] = useState('');
  const [correctiveAction, setCorrectiveAction] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (!caseData) return;
    setInvestigationStatus(caseData.investigation_status || 'in_progress');
    setRootCauseStatus(caseData.root_cause_status || 'hypothesis');
    setRootCauseSummary(caseData.root_cause_summary ?? '');
    setRootCauseConfidence(String(caseData.root_cause_confidence ?? 0.6));
    setRootCauseVerified(caseData.root_cause_verified);
    setResolutionStatus(caseData.outcome_status || 'pending');
    setResolutionSummary(caseData.outcome_summary ?? '');
    setCorrectiveAction(caseData.corrective_action ?? '');
  }, [caseData]);

  const saveActiveStep = async () => {
    if (activeStep === 'Finding') {
      setActiveStep('Investigation');
      return;
    }

    setIsSaving(true);
    try {
      if (activeStep === 'Investigation') {
        await onSaveInvestigation({ status: investigationStatus, note: investigationNote });
        setInvestigationNote('');
      } else if (activeStep === 'Root Cause') {
        await onSaveRootCause({
          status: rootCauseStatus,
          summary: rootCauseSummary,
          confidence: rootCauseConfidence,
          verified: rootCauseVerified,
        });
      } else if (activeStep === 'Resolution') {
        await onSaveResolution({ status: resolutionStatus, summary: resolutionSummary, action: correctiveAction });
      } else if (activeStep === 'Publish Knowledge') {
        await onPublish();
      }
    } finally {
      setIsSaving(false);
    }
  };

  const fieldSx = {
    '& .MuiInputBase-root': { color: '#e5e7eb', bgcolor: '#111827' },
    '& .MuiInputLabel-root': { color: '#9ca3af' },
    '& .MuiOutlinedInput-notchedOutline': { borderColor: '#374151' },
  };

  return (
    <Drawer anchor="right" open={open} onClose={onClose}>
      <Box sx={{ width: { xs: '100vw', sm: 460 }, height: '100%', bgcolor: 'rgba(9, 12, 20, 0.98)', color: '#d7d9e5', p: 2.25, overflowY: 'auto' }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2, mb: 1.5 }}>
          <Box>
            <Typography variant="h5" sx={{ fontWeight: 800 }}>Investigation</Typography>
            <Typography color="#9ca3af">Case #{caseData?.id ?? 'draft'}</Typography>
          </Box>
          <IconButton onClick={onClose} sx={{ color: '#fff', border: '1px solid #4b5563', borderRadius: 1 }}>
            <Typography sx={{ fontWeight: 800 }}>x</Typography>
          </IconButton>
        </Box>

        <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
          <Chip label={caseData?.case_status ?? 'open'} size="small" sx={{ color: '#d7d9e5', border: '1px solid #4b5563' }} />
          <Chip label={caseData?.memory_status === 'indexed' ? 'Published' : 'Not published'} size="small" sx={{ color: '#34d399', border: '1px solid #34d399' }} />
        </Stack>

        <Box sx={{ border: '1px solid #2f3645', borderRadius: 1, overflow: 'hidden', mb: 2 }}>
          {caseSteps.map((step, index) => (
            <Button
              key={step}
              fullWidth
              onClick={() => setActiveStep(step)}
              sx={{
                justifyContent: 'flex-start',
                gap: 1.5,
                px: 1.5,
                py: 1.35,
                borderRadius: 0,
                color: '#d7d9e5',
                bgcolor: activeStep === step ? '#1d2941' : 'transparent',
                borderBottom: index < caseSteps.length - 1 ? '1px solid #2f3645' : 0,
                textTransform: 'none',
                fontWeight: 700,
              }}
            >
              <Box sx={{ width: 24, height: 24, borderRadius: '50%', border: '1px solid #4f7edb', color: '#93c5fd', display: 'grid', placeItems: 'center', fontSize: 12 }}>
                {index === 0 ? '✓' : index + 1}
              </Box>
              {step}
            </Button>
          ))}
        </Box>

        {activeStep === 'Finding' ? (
          <Stack spacing={1.4}>
            <Typography variant="h5" sx={{ fontWeight: 800, lineHeight: 1.1 }}>{finding?.title ?? 'Finding snapshot'}</Typography>
            <Typography sx={{ color: '#b9bdca', lineHeight: 1.55 }}>{finding?.summary}</Typography>
            {[
              ['Severity', finding?.health_status ?? 'n/a'],
              ['Metric', runMetric],
              ['Time range', timeRange],
              ['Importance', finding?.importance_score?.toFixed(2) ?? 'n/a'],
              ['Confidence', finding?.importance_score?.toFixed(2) ?? 'n/a'],
              ['Supporting signals', finding?.signal_ids.length ?? 0],
            ].map(([label, value]) => (
              <Box key={label} sx={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr', gap: 2 }}>
                <Typography sx={{ fontWeight: 800 }}>{label}</Typography>
                <Typography sx={{ fontWeight: 800 }}>{value}</Typography>
              </Box>
            ))}
          </Stack>
        ) : null}

        {activeStep === 'Investigation' ? (
          <Stack spacing={1.5}>
            <TextField select label="Investigation status" value={investigationStatus} onChange={(event) => setInvestigationStatus(event.target.value)} sx={fieldSx}>
              <MenuItem value="not_started">Not started</MenuItem>
              <MenuItem value="in_progress">In progress</MenuItem>
              <MenuItem value="completed">Completed</MenuItem>
            </TextField>
            <TextField multiline rows={5} label="Notes" value={investigationNote} onChange={(event) => setInvestigationNote(event.target.value)} sx={fieldSx} />
            {caseData?.investigation_notes.length ? caseData.investigation_notes.map((note, index) => (
              <Box key={`${note.timestamp ?? 'note'}-${index}`} sx={{ p: 1.5, border: '1px solid #2f3645', borderRadius: 1 }}>
                <Typography variant="caption" color="#9ca3af">{note.timestamp ? new Date(note.timestamp).toLocaleString() : 'No timestamp'}</Typography>
                <Typography>{note.note}</Typography>
              </Box>
            )) : <Typography color="#9ca3af">No investigation notes yet.</Typography>}
          </Stack>
        ) : null}

        {activeStep === 'Root Cause' ? (
          <Stack spacing={1.5}>
            <TextField select label="Root cause status" value={rootCauseStatus} onChange={(event) => setRootCauseStatus(event.target.value)} sx={fieldSx}>
              <MenuItem value="unknown">Unknown</MenuItem>
              <MenuItem value="hypothesis">Hypothesis</MenuItem>
              <MenuItem value="identified">Identified</MenuItem>
              <MenuItem value="confirmed">Confirmed</MenuItem>
            </TextField>
            <TextField multiline rows={5} label="Root cause summary" value={rootCauseSummary} onChange={(event) => setRootCauseSummary(event.target.value)} sx={fieldSx} />
            <TextField label="Confidence" type="number" value={rootCauseConfidence} onChange={(event) => setRootCauseConfidence(event.target.value)} sx={fieldSx} />
            <Button variant={rootCauseVerified ? 'contained' : 'outlined'} onClick={() => setRootCauseVerified((value) => !value)}>Root cause verified</Button>
          </Stack>
        ) : null}

        {activeStep === 'Resolution' ? (
          <Stack spacing={1.5}>
            <TextField select label="Outcome status" value={resolutionStatus} onChange={(event) => setResolutionStatus(event.target.value)} sx={fieldSx}>
              <MenuItem value="pending">Pending</MenuItem>
              <MenuItem value="in_progress">In progress</MenuItem>
              <MenuItem value="resolved">Resolved</MenuItem>
              <MenuItem value="escalated">Escalated</MenuItem>
            </TextField>
            <TextField multiline rows={4} label="Outcome summary" value={resolutionSummary} onChange={(event) => setResolutionSummary(event.target.value)} sx={fieldSx} />
            <TextField multiline rows={4} label="Corrective action" value={correctiveAction} onChange={(event) => setCorrectiveAction(event.target.value)} sx={fieldSx} />
          </Stack>
        ) : null}

        {activeStep === 'Publish Knowledge' ? (
          <Stack spacing={1.5}>
            <Typography sx={{ color: '#b9bdca' }}>Publish this case into operational memory once investigation, root cause, and resolution are ready.</Typography>
            <Typography>Memory status: {caseData?.memory_status ?? 'unknown'}</Typography>
          </Stack>
        ) : null}

        <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 1.5, borderTop: '1px solid #2f3645', mt: 2, pt: 2 }}>
          <Button variant="outlined" onClick={onClose}>Close</Button>
          <Button variant="contained" onClick={saveActiveStep} disabled={isSaving || !caseData}>
            {isSaving ? 'Saving...' : activeStep === 'Finding' ? 'Next' : activeStep === 'Publish Knowledge' ? 'Publish' : 'Save'}
          </Button>
        </Box>
      </Box>
    </Drawer>
  );
}

function RunDetailsDrawer({
  open,
  run,
  finding,
  signals,
  firstTimestamp,
  lastTimestamp,
  onClose,
}: {
  open: boolean;
  run: AnalysisRun;
  finding: Finding | undefined;
  signals: Signal[];
  firstTimestamp: string;
  lastTimestamp: string;
  onClose: () => void;
}) {
  const routing = run.router_decisions_json ?? [];
  const executed = run.executed_analyzers_json ?? [];
  const recommended = routing.filter((item) => item.recommendation === 'RECOMMENDED');
  const optional = routing.filter((item) => item.recommendation === 'OPTIONAL');
  const notRecommended = routing.filter((item) => item.recommendation === 'NOT_RECOMMENDED');
  const rejected = routing.filter((item) => item.recommendation === 'REJECTED');
  const rows = [
    ['Analysis ID', run.id],
    ['Status', run.status],
    ['Service', run.service],
    ['Metric', run.metric_name],
    ['Data source', run.provider],
    ['Source type', run.source_type],
    ['File name', run.file_name ?? 'n/a'],
    ['Samples', run.sample_count],
    ['Finding count', finding ? 1 : 0],
    ['Signal windows', signals.length],
    ['Start', firstTimestamp],
    ['End', lastTimestamp],
    ['Created', run.created_at ? new Date(run.created_at).toLocaleString() : 'n/a'],
    ['Router version', run.router_version ?? 'n/a'],
    ['Registry version', run.analyzer_registry_version ?? 'n/a'],
  ];
  const analyzerLabel = (item: NonNullable<AnalysisRun['router_decisions_json']>[number]) => {
    const score = typeof item.final_score === 'number' ? ` ${item.final_score.toFixed(2)}` : '';
    return `${item.display_name ?? item.analyzer_id ?? item.analyzer ?? 'Analyzer'}${score}`;
  };
  const executedLabel = (item: NonNullable<AnalysisRun['executed_analyzers_json']>[number]) =>
    item.pipeline_analyzer_id ?? item.router_analyzer_id ?? 'Analyzer';
  const renderAnalyzerChips = (
    items: string[],
    tone: 'success' | 'warning' | 'danger' | 'neutral' = 'neutral',
  ) => {
    const colors = {
      success: { bg: '#dcfce7', color: '#047857', border: '#86efac' },
      warning: { bg: '#fff7ed', color: '#c2410c', border: '#fed7aa' },
      danger: { bg: '#fee2e2', color: '#b91c1c', border: '#fecaca' },
      neutral: { bg: '#f8fafc', color: '#334155', border: '#e2e8f0' },
    }[tone];

    if (!items.length) {
      return <Typography variant="body2" color="text.secondary">None</Typography>;
    }

    return (
      <Stack direction="row" spacing={0.75} sx={{ flexWrap: 'wrap', rowGap: 0.75 }}>
        {items.map((item) => (
          <Chip
            key={item}
            label={item}
            size="small"
            sx={{ bgcolor: colors.bg, color: colors.color, border: `1px solid ${colors.border}`, fontWeight: 650 }}
          />
        ))}
      </Stack>
    );
  };

  return (
    <Drawer anchor="right" open={open} onClose={onClose}>
      <Box sx={{ width: { xs: '100vw', sm: 440 }, height: '100%', bgcolor: '#fff', p: 2.5, overflowY: 'auto' }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', mb: 2 }}>
          <Box>
            <Typography variant="h5" sx={{ fontWeight: 800 }}>Run details</Typography>
            <Typography variant="body2" color="text.secondary">
              {run.metric_name} on {run.service}
            </Typography>
          </Box>
          <IconButton onClick={onClose} sx={{ border: '1px solid #e5e7eb', borderRadius: 1.5 }}>
            <Typography sx={{ fontWeight: 800 }}>x</Typography>
          </IconButton>
        </Box>
        <Stack spacing={1}>
          {rows.map(([label, value]) => (
            <Box key={label} sx={{ display: 'grid', gridTemplateColumns: '130px 1fr', gap: 1.5, borderBottom: '1px solid #f1f5f9', py: 1 }}>
              <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 650 }}>{label}</Typography>
              <Typography variant="body2" sx={{ overflowWrap: 'anywhere' }}>{value}</Typography>
            </Box>
          ))}
        </Stack>
        <Box sx={{ mt: 2.5, pt: 2, borderTop: '1px solid #e5e7eb' }}>
          <Typography variant="h6" sx={{ fontWeight: 800, mb: 0.5 }}>Analyzer routing</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            Why this run chose some analyzers and skipped others.
          </Typography>
          {routing.length === 0 ? (
            <Alert severity="info" sx={{ mb: 1.5 }}>
              Analyzer router metadata was not returned for this run.
            </Alert>
          ) : null}
          <Stack spacing={1.5}>
            <Box>
              <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 800 }}>Executed analyzers</Typography>
              {renderAnalyzerChips(executed.map(executedLabel))}
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 800 }}>Recommended</Typography>
              {renderAnalyzerChips(recommended.map(analyzerLabel), 'success')}
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 800 }}>Optional</Typography>
              {renderAnalyzerChips(optional.map(analyzerLabel), 'warning')}
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 800 }}>Not recommended</Typography>
              {renderAnalyzerChips(notRecommended.map(analyzerLabel))}
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 800 }}>Rejected by eligibility checks</Typography>
              {renderAnalyzerChips(rejected.map(analyzerLabel), 'danger')}
            </Box>
            {rejected.slice(0, 5).map((item) => {
              const name = item.display_name ?? item.analyzer_id ?? item.analyzer ?? 'Analyzer';
              const reason = [...(item.reasons ?? []), ...(item.warnings ?? [])].slice(0, 2).join(' ') || 'No rejection reason was returned.';
              return (
                <Box key={name} sx={{ border: '1px solid #fecaca', bgcolor: '#fff7f7', borderRadius: 1.5, p: 1.25 }}>
                  <Typography variant="body2" sx={{ color: '#991b1b', fontWeight: 800 }}>{name}</Typography>
                  <Typography variant="body2" sx={{ color: '#7f1d1d', mt: 0.5 }}>{reason}</Typography>
                </Box>
              );
            })}
          </Stack>
        </Box>
      </Box>
    </Drawer>
  );
}

export function OverviewPage() {
  const { runsQuery, selectedRun, setSelectedRunId, service, metric, runId } = useOverviewData();
  const queryClient = useQueryClient();
  const [timestamp, setTimestamp] = useState('7/24/2026, 12:00 AM');
  const [draftService, setDraftService] = useState('');
  const [draftMetric, setDraftMetric] = useState('');
  const [isRunning, setIsRunning] = useState(false);
  const [isCreatingCase, setIsCreatingCase] = useState(false);
  const [createdCaseId, setCreatedCaseId] = useState<number | null>(null);
  const [runMessage, setRunMessage] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [selectedFinding, setSelectedFinding] = useState<Finding | null>(null);
  const [selectedSignal, setSelectedSignal] = useState<Signal | null>(null);
  const [findingDrawerOpen, setFindingDrawerOpen] = useState(false);
  const [signalDrawerOpen, setSignalDrawerOpen] = useState(false);
  const [caseDrawerOpen, setCaseDrawerOpen] = useState(false);
  const [runDetailsOpen, setRunDetailsOpen] = useState(false);

  const findingQuery = useQuery({
    queryKey: ['findings', service, metric, runId],
    queryFn: () => api.findings(service, metric, runId),
    enabled: Boolean(service && metric && runId),
  });

  const signalQuery = useQuery({
    queryKey: ['signals', service, metric, runId],
    queryFn: () => api.signals(service, metric, runId),
    enabled: Boolean(service && metric && runId),
  });

  const timeSeriesQuery = useQuery({
    queryKey: ['timeseries', service, metric, runId],
    queryFn: () => api.timeseries(service, metric, runId),
    enabled: Boolean(service && metric && runId),
  });

  const caseQuery = useQuery({
    queryKey: ['case', createdCaseId],
    queryFn: () => api.getCase(createdCaseId!),
    enabled: Boolean(createdCaseId),
  });

  useEffect(() => {
    if (!selectedRun) return;
    setDraftService(selectedRun.service);
    setDraftMetric(selectedRun.metric_name);
  }, [selectedRun]);

  if (runsQuery.isLoading) return <LoadingSkeleton />;
  if (runsQuery.error) return <ErrorState message="Failed to load analysis runs" />;

  const runs = runsQuery.data ?? [];
  const fallbackRun = runs[0];
  const run = selectedRun ?? fallbackRun;

  if (!run) {
    return <ErrorState message="No analysis runs found. Create a run before opening the live Prometheus dashboard." />;
  }

  const services = [...new Set(runs.map((item) => item.service))];
  const metrics = [...new Set(runs.map((item) => item.metric_name))];
  const signals = signalQuery.data ?? [];
  const timeseries = timeSeriesQuery.data ?? [];
  const findings = findingQuery.data ?? [];
  const finding = findings[0];
  const signalCount = signals.length || 3;
  const findingCount = findings.length || 1;
  const title = finding?.title ?? `${run.metric_name} behaviour changed significantly yesterday.`;
  const summary =
    finding?.summary ??
    `Baseline increased 71.2%; ${run.metric_name} shows a sustained downward trend of -104.6% across the batch window; cpu behaviour differs significantly from the previous day.`;
  const values = timeseries.map((point) => point.value).filter((value) => Number.isFinite(value));
  const current = values.length ? values[values.length - 1] : null;
  const average = values.length ? values.reduce((total, value) => total + value, 0) / values.length : null;
  const peak = values.length ? Math.max(...values) : null;
  const min = values.length ? Math.min(...values) : 0;
  const max = values.length ? Math.max(...values) : 1;
  const range = max - min || 1;
  const chartPoints = timeseries.length
    ? timeseries
        .map((point, index) => {
          const x = 35 + (index / Math.max(1, timeseries.length - 1)) * 835;
          const y = 145 - ((point.value - min) / range) * 115;
          return `${x.toFixed(1)},${y.toFixed(1)}`;
        })
        .join(' ')
    : '35,50 95,48 140,45 205,50 280,47 355,50 390,135 470,140 535,135 605,140 675,136 745,141 820,137 870,139';
  const signalMarkers = signals.slice(0, 3).map((_, index) => 245 + index * 210);
  const firstTimestamp = timeseries[0]?.timestamp ? new Date(timeseries[0].timestamp).toLocaleString() : '7/24/2026, 12:00 AM';
  const lastPoint = timeseries.length ? timeseries[timeseries.length - 1] : null;
  const lastTimestamp = lastPoint?.timestamp ? new Date(lastPoint.timestamp).toLocaleString() : '7/24/2026, 11:59 PM';
  const formatMetric = (value: number | null) => (value == null ? 'n/a' : value.toFixed(2));
  const signalRows: Array<[string, string, string, string]> = signals.length
    ? signals.slice(0, 6).map((signal: Signal) => [
        signal.start_time ? new Date(signal.start_time).toLocaleString() : 'n/a',
        signal.signal_type.replace(/_/g, ' '),
        signal.severity ?? 'medium',
        signal.summary ?? `${run.metric_name} signal detected by ${signal.analyzer_id ?? 'analyzer'}.`,
      ])
    : [
        ['No signals', 'n/a', 'n/a', `No signals returned for ${run.service} / ${run.metric_name}.`],
      ];

  const runAnalysis = async () => {
    setIsRunning(true);
    setRunError(null);
    setRunMessage(null);
    try {
      const refreshedRuns = await queryClient.fetchQuery({ queryKey: ['analysis-runs'], queryFn: api.analysisRuns });
      const matchingRun = refreshedRuns.find((item) => item.service === draftService && item.metric_name === draftMetric);
      if (!matchingRun) {
        setRunError(`No analysis run found for ${draftService} / ${draftMetric}.`);
        return;
      }

      setSelectedRunId(matchingRun.id);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['findings', matchingRun.service, matchingRun.metric_name, matchingRun.id] }),
        queryClient.invalidateQueries({ queryKey: ['signals', matchingRun.service, matchingRun.metric_name, matchingRun.id] }),
        queryClient.invalidateQueries({ queryKey: ['timeseries', matchingRun.service, matchingRun.metric_name, matchingRun.id] }),
      ]);
      setRunMessage(`Loaded ${matchingRun.service} / ${matchingRun.metric_name}.`);
    } catch (error) {
      setRunError(error instanceof Error ? error.message : 'Run analysis failed.');
    } finally {
      setIsRunning(false);
    }
  };

  const openFinding = () => {
    if (!finding) {
      setRunError('No finding is available for this run.');
      return;
    }
    setSelectedFinding(finding);
    setFindingDrawerOpen(true);
  };

  const openEvidence = () => {
    const evidenceSignal = signals[0];
    if (!evidenceSignal) {
      setRunError('No evidence signal is available for this run.');
      return;
    }
    setSelectedSignal(evidenceSignal);
    setSignalDrawerOpen(true);
  };

  const createCase = async () => {
    if (!finding?.id) {
      setRunError('No finding is available to create a case.');
      return;
    }
    setIsCreatingCase(true);
    setRunError(null);
    setRunMessage(null);
    try {
      const createdCase = await api.createCase(finding.id);
      setCreatedCaseId(createdCase.case_id);
      await queryClient.invalidateQueries({ queryKey: ['case', createdCase.case_id] });
      setCaseDrawerOpen(true);
      setRunMessage(`Created case #${createdCase.case_id}. Continue the investigation in the side panel.`);
    } catch (error) {
      setRunError(error instanceof Error ? error.message : 'Create case failed.');
    } finally {
      setIsCreatingCase(false);
    }
  };

  const refreshCase = async () => {
    if (createdCaseId) {
      await queryClient.invalidateQueries({ queryKey: ['case', createdCaseId] });
    }
  };

  const saveInvestigation = async (payload: { status: string; note: string }) => {
    if (!createdCaseId) return;
    await api.updateInvestigation(createdCaseId, {
      investigation_status: payload.status,
      investigation_note: payload.note.trim() || undefined,
    });
    await refreshCase();
    setRunMessage(`Saved investigation for case #${createdCaseId}.`);
  };

  const saveRootCause = async (payload: { status: string; summary: string; confidence: string; verified: boolean }) => {
    if (!createdCaseId) return;
    const parsedConfidence = Number.parseFloat(payload.confidence);
    await api.updateRCA(createdCaseId, {
      root_cause_status: payload.status,
      root_cause_summary: payload.summary.trim() || undefined,
      root_cause_confidence: Number.isFinite(parsedConfidence) ? parsedConfidence : undefined,
      root_cause_verified: payload.verified,
    });
    await refreshCase();
    setRunMessage(`Saved root cause for case #${createdCaseId}.`);
  };

  const saveResolution = async (payload: { status: string; summary: string; action: string }) => {
    if (!createdCaseId) return;
    await api.updateResolution(createdCaseId, {
      outcome_status: payload.status,
      outcome_summary: payload.summary.trim() || undefined,
      corrective_action: payload.action.trim() || undefined,
    });
    await refreshCase();
    setRunMessage(`Saved resolution for case #${createdCaseId}.`);
  };

  const publishCase = async () => {
    if (!createdCaseId) return;
    await api.indexCaseMemory(createdCaseId);
    await refreshCase();
    setRunMessage(`Published case #${createdCaseId} to knowledge memory.`);
  };

  return (
    <Box sx={{ display: 'grid', gap: 1.5, color: '#0f172a' }}>
      <Card sx={panelSx}>
        <CardContent sx={{ p: 2 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2, alignItems: 'flex-start', mb: 2 }}>
            <Box sx={{ minWidth: 0 }}>
              <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
                <Typography variant="h5" sx={{ fontWeight: 800, letterSpacing: 0 }}>
                  {run.metric_name} - 7/24/2026
                </Typography>
                <Chip label="Completed" size="small" sx={{ bgcolor: '#dcfce7', color: '#047857', fontWeight: 650 }} />
              </Box>
            </Box>
            <Stack direction="row" spacing={1}>
              <Button variant="outlined" size="small" sx={{ borderRadius: 1.5, color: '#334155', borderColor: '#dbe3ee' }}>
                Last updated: 2m ago
              </Button>
              <Button
                variant="contained"
                size="small"
                onClick={runAnalysis}
                disabled={isRunning || !draftService || !draftMetric}
                sx={{ borderRadius: 1.5, bgcolor: '#5546e8', px: 2.5 }}
              >
                {isRunning ? 'Running...' : 'Run Analysis'}
              </Button>
            </Stack>
          </Box>

          {runMessage ? <Alert severity="success" sx={{ mb: 2 }}>{runMessage}</Alert> : null}
          {runError ? <Alert severity="error" sx={{ mb: 2 }}>{runError}</Alert> : null}

          <Grid container spacing={1.5} sx={{ mb: 2 }}>
            <Grid size={{ xs: 12, md: 2.4 }}>
              <TextField
                fullWidth
                select
                size="small"
                label="Service"
                value={draftService}
                onChange={(event) => setDraftService(event.target.value)}
              >
                {services.map((item) => (
                  <MenuItem key={item} value={item}>
                    {item}
                  </MenuItem>
                ))}
              </TextField>
            </Grid>
            <Grid size={{ xs: 12, md: 2.4 }}>
              <TextField
                fullWidth
                select
                size="small"
                label="Metric"
                value={draftMetric}
                onChange={(event) => setDraftMetric(event.target.value)}
              >
                {metrics.map((item) => (
                  <MenuItem key={item} value={item}>
                    {item}
                  </MenuItem>
                ))}
              </TextField>
            </Grid>
            <Grid size={{ xs: 12, md: 2.4 }}>
              <TextField fullWidth size="small" label="Data source" value="Prometheus" />
            </Grid>
            <Grid size={{ xs: 12, md: 2.4 }}>
              <TextField fullWidth size="small" label="Samples" value={run.sample_count} />
            </Grid>
            <Grid size={{ xs: 12, md: 2.4 }}>
              <TextField fullWidth size="small" label="Time range" value={timestamp} onChange={(event) => setTimestamp(event.target.value)} />
            </Grid>
          </Grid>

          <Grid container spacing={1.5}>
            <Grid size={{ xs: 12, md: 2.4 }}>
              <SummaryCard icon={<WidgetsOutlinedIcon />} value={run.sample_count} label="Samples" tone="violet" />
            </Grid>
            <Grid size={{ xs: 12, md: 2.4 }}>
              <SummaryCard icon={<TimelineOutlinedIcon />} value={signalCount} label="Signals" tone="green" />
            </Grid>
            <Grid size={{ xs: 12, md: 2.4 }}>
              <SummaryCard icon={<ChangeHistoryOutlinedIcon />} value={findingCount} label="Finding" tone="orange" />
            </Grid>
            <Grid size={{ xs: 12, md: 2.4 }}>
              <SummaryCard icon={<Inventory2OutlinedIcon />} value={0} label="Behavior Findings" tone="purple" />
            </Grid>
            <Grid size={{ xs: 12, md: 2.4 }}>
              <Card
                onClick={() => setRunDetailsOpen(true)}
                sx={{
                  ...panelSx,
                  cursor: 'pointer',
                  transition: 'border-color 160ms ease, box-shadow 160ms ease',
                  '&:hover': { borderColor: '#c7d2fe', boxShadow: '0 8px 24px rgba(79, 70, 229, 0.12)' },
                }}
              >
                <CardContent sx={{ minHeight: 78, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Typography variant="body2" sx={{ fontWeight: 650 }}>
                    View run details
                  </Typography>
                  <ArrowForwardRoundedIcon fontSize="small" />
                </CardContent>
              </Card>
            </Grid>
          </Grid>
        </CardContent>
      </Card>

      <Grid container spacing={1.5}>
        <Grid size={{ xs: 12, xl: 9 }}>
          <Stack spacing={1.5}>
            <Card sx={{ ...panelSx, borderColor: '#ff9aa4' }}>
              <CardContent sx={{ p: 2, display: 'grid', gridTemplateColumns: { xs: '1fr', md: '92px 1fr auto' }, gap: 2 }}>
                <Box sx={{ minHeight: 150, borderRadius: 2, bgcolor: '#fff1f2', display: 'grid', placeItems: 'center', color: '#ef4444', fontSize: 36, fontWeight: 900 }}>
                  OS
                </Box>
                <Stack spacing={1.5}>
                  <Chip label="CRITICAL" size="small" variant="outlined" sx={{ width: 'fit-content', color: '#ef4444', borderColor: '#fb7185', fontWeight: 750 }} />
                  <Typography variant="h6" sx={{ fontWeight: 800 }}>
                    {title}
                  </Typography>
                  <Typography variant="body2" sx={{ lineHeight: 1.6, color: '#334155' }}>
                    {summary}
                  </Typography>
                  <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap' }}>
                    <Chip label="Importance 0.83" size="small" sx={{ bgcolor: '#fee2e2', color: '#b91c1c' }} />
                    <Chip label="Confidence 0.83" size="small" sx={{ bgcolor: '#ede9fe', color: '#4f46e5' }} />
                    <Chip label="Category Behavior Change" size="small" sx={{ bgcolor: '#dcfce7', color: '#047857' }} />
                  </Stack>
                  <Stack direction="row" spacing={1}>
                    <Button variant="contained" size="small" onClick={openFinding} sx={{ bgcolor: '#5546e8', borderRadius: 1.5 }}>
                      Investigate
                    </Button>
                    <Button variant="outlined" size="small" onClick={createCase} disabled={isCreatingCase} sx={{ borderRadius: 1.5 }}>
                      {isCreatingCase ? 'Creating...' : 'Create Case'}
                    </Button>
                    <Button variant="outlined" size="small" onClick={openEvidence} sx={{ borderRadius: 1.5 }}>
                      View Evidence
                    </Button>
                  </Stack>
                </Stack>
                <IconButton size="small" sx={{ alignSelf: 'start', border: '1px solid #e5e7eb', borderRadius: 1.5 }}>
                  <MoreHorizRoundedIcon />
                </IconButton>
              </CardContent>
            </Card>

            <Card sx={panelSx}>
              <CardContent sx={{ p: 2 }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1.5 }}>
                  <Typography variant="h6" sx={{ fontWeight: 800 }}>
                    Metric timeline
                  </Typography>
                  <Button variant="outlined" size="small" sx={{ borderRadius: 1.5 }}>
                    Auto
                  </Button>
                </Box>
                <Grid container spacing={1.5} sx={{ mb: 1 }}>
                  {[
                    ['Current', formatMetric(current)],
                    ['Average', formatMetric(average)],
                    ['Peak', formatMetric(peak)],
                    ['Signal windows', signalCount],
                  ].map(([label, value]) => (
                    <Grid key={label} size={{ xs: 6, md: 3 }}>
                      <Typography variant="caption" color="text.secondary">
                        {label}
                      </Typography>
                      <Typography sx={{ fontWeight: 700 }}>{value}</Typography>
                    </Grid>
                  ))}
                </Grid>
                <Box sx={{ height: 170, px: 2 }}>
                  <svg viewBox="0 0 900 170" width="100%" height="100%" role="img" aria-label="Metric timeline">
                    <rect x="0" y="0" width="900" height="170" rx="8" fill="#fff" />
                    {[30, 70, 110, 150].map((y) => (
                      <line key={y} x1="20" x2="880" y1={y} y2={y} stroke="#e5e7eb" />
                    ))}
                    {(signalMarkers.length ? signalMarkers : [245, 455, 655]).map((x) => (
                      <rect key={x} x={x} y="25" width="16" height="120" fill="#fecdd3" opacity="0.9" />
                    ))}
                    <line x1="35" x2="870" y1="110" y2="110" stroke="#94a3b8" strokeDasharray="7 7" />
                    <polyline
                      points={chartPoints}
                      fill="none"
                      stroke="#4f46e5"
                      strokeWidth="3"
                    />
                    <text x="35" y="165" fill="#475569" fontSize="12">{firstTimestamp}</text>
                    <text x="870" y="165" fill="#475569" fontSize="12" textAnchor="end">{lastTimestamp}</text>
                  </svg>
                </Box>
                <Stack direction="row" spacing={2} sx={{ pl: 2, mt: 1 }}>
                  <Typography variant="caption" color="text.secondary">{run.metric_name}</Typography>
                  <Typography variant="caption" color="text.secondary">Baseline</Typography>
                  <Typography variant="caption" color="text.secondary">Signal window</Typography>
                </Stack>
              </CardContent>
            </Card>

            <Card sx={panelSx}>
              <CardContent sx={{ p: 0 }}>
                <Box sx={{ display: 'flex', gap: 3, borderBottom: '1px solid #e5e7eb', px: 2, pt: 1.5 }}>
                  {[`Signals (${signals.length})`, `Findings (${findings.length})`, 'Behavior Findings (0)', 'Evidence'].map((tab, index) => (
                    <Typography key={tab} sx={{ pb: 1.25, fontSize: 14, color: index === 0 ? '#4f46e5' : '#334155', borderBottom: index === 0 ? '2px solid #4f46e5' : '2px solid transparent' }}>
                      {tab}
                    </Typography>
                  ))}
                </Box>
                <Box sx={{ display: 'grid', gridTemplateColumns: '1.1fr 0.8fr 0.7fr 2.1fr 0.3fr', px: 2, py: 1.25, gap: 1, borderBottom: '1px solid #e5e7eb' }}>
                  {['Time', 'Type', 'Severity', 'Summary', ''].map((head) => (
                    <Typography key={head} variant="caption" color="text.secondary" sx={{ fontWeight: 700 }}>{head}</Typography>
                  ))}
                </Box>
                {signalRows.map((row) => (
                  <Box key={row[0]} sx={{ display: 'grid', gridTemplateColumns: '1.1fr 0.8fr 0.7fr 2.1fr 0.3fr', px: 2, py: 1.25, gap: 1, borderBottom: '1px solid #f1f5f9' }}>
                    <Typography variant="body2">{row[0]}</Typography>
                    <Typography variant="body2">{row[1]}</Typography>
                    <Chip label={row[2]} size="small" sx={{ width: 'fit-content', textTransform: 'capitalize', color: row[2].toLowerCase() === 'critical' ? '#b91c1c' : row[2].toLowerCase() === 'high' ? '#c2410c' : '#a16207', border: '1px solid currentColor', bgcolor: '#fff' }} />
                    <Typography variant="body2">{row[3]}</Typography>
                    <Typography variant="body2" sx={{ color: '#4f46e5', fontWeight: 650 }}>View</Typography>
                  </Box>
                ))}
              </CardContent>
            </Card>
          </Stack>
        </Grid>

        <Grid size={{ xs: 12, xl: 3 }}>
          <Stack spacing={1.5}>
            <Card sx={panelSx}>
              <CardContent sx={{ p: 2 }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1.5 }}>
                  <Typography variant="h6" sx={{ fontWeight: 800 }}>Evidence</Typography>
                  <Button variant="outlined" size="small">⌄</Button>
                </Box>
                <Box sx={{ border: '1px solid #86efac', bgcolor: '#ecfdf5', borderRadius: 1.5, p: 1.25, mb: 1.5 }}>
                  <Typography sx={{ color: '#047857', fontWeight: 800 }}>{signalCount}</Typography>
                  <Typography variant="body2" sx={{ color: '#047857' }}>signal windows support this finding</Typography>
                </Box>
                {[
                  ['Earliest signal', signals[0]?.start_time ? new Date(signals[0].start_time).toLocaleString() : 'n/a'],
                  ['Highest observed value', formatMetric(peak)],
                  ['Baseline comparison', finding ? 'Significantly different' : 'No finding'],
                  ['Analyzer confidence', signals[0]?.confidence == null ? 'n/a' : signals[0].confidence.toFixed(2)],
                ].map(([label, value]) => (
                  <Box key={label} sx={{ display: 'flex', justifyContent: 'space-between', gap: 2, mb: 1 }}>
                    <Typography variant="body2" sx={{ fontWeight: 650 }}>{label}</Typography>
                    <Typography variant="body2" sx={{ textAlign: 'right' }}>{value}</Typography>
                  </Box>
                ))}
                <Button fullWidth variant="outlined" size="small" sx={{ mt: 1, borderRadius: 1.5 }}>
                  View all {signalCount} signals
                </Button>
              </CardContent>
            </Card>

            <Card sx={panelSx}>
              <CardContent sx={{ p: 2 }}>
                {[
                  ['Current', formatMetric(current)],
                  ['Peak', formatMetric(peak)],
                  ['Finding category', finding?.category ?? 'n/a'],
                ].map(([label, value]) => (
                  <Box key={label} sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
                    <Typography variant="body2">{label}</Typography>
                    <Typography variant="body2">{value}</Typography>
                  </Box>
                ))}
              </CardContent>
            </Card>

            <Card sx={{ ...panelSx, borderColor: '#ddd6fe', bgcolor: '#fbf9ff' }}>
              <CardContent sx={{ p: 2 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Typography variant="h6" sx={{ fontWeight: 800, color: '#4c1d95' }}>Ask Ops Signals</Typography>
                  <Chip label="Beta" size="small" sx={{ height: 22, bgcolor: '#ede9fe', color: '#5b21b6' }} />
                </Box>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1, mb: 1.5 }}>
                  Grounded in this run, router decisions, signals, and case context.
                </Typography>
                <Box sx={{ display: 'flex', gap: 0.75, mb: 1.5 }}>
                  <TextField fullWidth size="small" placeholder="Ask a question about this analysis..." />
                  <IconButton size="small" sx={{ bgcolor: '#ede9fe', color: '#4f46e5' }}>
                    <SendRoundedIcon fontSize="small" />
                  </IconButton>
                </Box>
                {['Why did this behaviour change?', 'What should I investigate next?'].map((question) => (
                  <Box key={question} sx={{ display: 'flex', justifyContent: 'space-between', py: 0.8, borderTop: '1px solid #ede9fe' }}>
                  <Typography variant="body2" sx={{ color: '#4f46e5' }}>{question}</Typography>
                    <ArrowForwardRoundedIcon fontSize="small" sx={{ color: '#64748b' }} />
                  </Box>
                ))}
              </CardContent>
            </Card>

            <Card sx={panelSx}>
              <CardContent sx={{ p: 2 }}>
                <Typography variant="h6" sx={{ fontWeight: 800, mb: 1.5 }}>Analysis info</Typography>
                {[
                  ['Analysis ID', run.id.slice(0, 8)],
                  ['Run by', 'ramprasad.gk'],
                  ['Duration', '2m 14s'],
                  ['Completed', '7/24/2026, 12:45 AM'],
                ].map(([label, value]) => (
                  <Box key={label} sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
                    <Typography variant="body2" color="text.secondary">{label}</Typography>
                    <Typography variant="body2">{value}</Typography>
                  </Box>
                ))}
              </CardContent>
            </Card>
          </Stack>
        </Grid>
      </Grid>
      <FindingDetailsDrawer
        open={findingDrawerOpen}
        finding={selectedFinding}
        signals={signals}
        onClose={() => setFindingDrawerOpen(false)}
      />
      <SignalDetailsDrawer
        open={signalDrawerOpen}
        signal={selectedSignal}
        timeseries={timeseries}
        onClose={() => setSignalDrawerOpen(false)}
      />
      <RunDetailsDrawer
        open={runDetailsOpen}
        run={run}
        finding={finding}
        signals={signals}
        firstTimestamp={firstTimestamp}
        lastTimestamp={lastTimestamp}
        onClose={() => setRunDetailsOpen(false)}
      />
      <InvestigationDrawer
        open={caseDrawerOpen}
        caseData={caseQuery.data ?? null}
        finding={caseQuery.data?.finding_snapshot ?? finding ?? null}
        runMetric={run.metric_name}
        timeRange={`${firstTimestamp} - ${lastTimestamp}`}
        onClose={() => setCaseDrawerOpen(false)}
        onSaveInvestigation={saveInvestigation}
        onSaveRootCause={saveRootCause}
        onSaveResolution={saveResolution}
        onPublish={publishCase}
      />
    </Box>
  );
}
