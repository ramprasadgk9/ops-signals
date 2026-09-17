import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  CircularProgress,
  FormControl,
  FormControlLabel,
  Grid2 as Grid,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Step,
  StepLabel,
  Stepper,
  Tab,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import AssistantRoundedIcon from '@mui/icons-material/AssistantRounded';
import PlayCircleRoundedIcon from '@mui/icons-material/PlayCircleRounded';
import BuildRoundedIcon from '@mui/icons-material/BuildRounded';
import TaskAltRoundedIcon from '@mui/icons-material/TaskAltRounded';
import FactCheckRoundedIcon from '@mui/icons-material/FactCheckRounded';
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded';
import RadioButtonUncheckedRoundedIcon from '@mui/icons-material/RadioButtonUncheckedRounded';
import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded';
import { useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/queries';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { ErrorState } from '../components/ErrorState';
import type { Signal } from '../types';
import { groupSignalsByAnalyzer, signalGroupChipLabel, signalGroupTooltip } from '../utils/signalGroups';

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props;
  return (
    <div role="tabpanel" hidden={value !== index} id={`case-tabpanel-${index}`} aria-labelledby={`case-tab-${index}`} {...other}>
      {value === index ? <Box sx={{ pt: 3 }}>{children}</Box> : null}
    </div>
  );
}

function stepForCase(caseStatus: string, investigationStatus: string, rootCauseStatus: string, outcomeStatus: string): number {
  if (outcomeStatus === 'resolved') return 4;
  if (rootCauseStatus === 'confirmed' || rootCauseStatus === 'identified') return 3;
  if (investigationStatus === 'completed' || investigationStatus === 'in_progress') return 2;
  if (caseStatus === 'open' || caseStatus === 'in_progress') return 1;
  return 0;
}

function stepVisualState(stepIndex: number, activeStep: number) {
  if (stepIndex < activeStep) return 'completed';
  if (stepIndex === activeStep) return 'active';
  return 'upcoming';
}

function statusLabel(value: string): string {
  return value
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function workflowState(label: string, done: boolean, active: boolean) {
  return { label, done, active };
}

export function CaseDetailsPage() {
  const { caseId } = useParams<{ caseId: string }>();
  const [tabValue, setTabValue] = useState(0);
  const queryClient = useQueryClient();
  const [initialized, setInitialized] = useState(false);

  const [investigationStatus, setInvestigationStatus] = useState('');
  const [investigationNote, setInvestigationNote] = useState('');
  const [rcaStatus, setRcaStatus] = useState('');
  const [rcaSummary, setRcaSummary] = useState('');
  const [rcaConfidence, setRcaConfidence] = useState<number | string>('');
  const [rcaVerified, setRcaVerified] = useState(false);
  const [outcomeStatus, setOutcomeStatus] = useState('');
  const [outcomeSummary, setOutcomeSummary] = useState('');
  const [correctiveAction, setCorrectiveAction] = useState('');
  const [learningOutcomeStatus, setLearningOutcomeStatus] = useState('');

  const caseQuery = useQuery({
    queryKey: ['case', caseId],
    queryFn: () => api.getCase(parseInt(caseId || '0')),
    enabled: Boolean(caseId),
  });

  const caseSignalsQuery = useQuery({
    queryKey: [
      'case-signals',
      caseQuery.data?.analysis_run_id,
      caseQuery.data?.finding_snapshot.service ?? '',
      caseQuery.data?.finding_snapshot.metric_name ?? '',
    ],
    queryFn: () =>
      api.signals(
        caseQuery.data!.finding_snapshot.service ?? '',
        caseQuery.data!.finding_snapshot.metric_name,
        caseQuery.data!.analysis_run_id
      ),
    enabled: Boolean(
      caseQuery.data?.analysis_run_id &&
        caseQuery.data?.finding_snapshot.metric_name &&
        caseQuery.data?.finding_snapshot.service
    ),
  });

  useEffect(() => {
    if (!caseQuery.data || initialized) return;
    setInvestigationStatus(caseQuery.data.investigation_status);
    setRcaStatus(caseQuery.data.root_cause_status);
    setRcaSummary(caseQuery.data.root_cause_summary || '');
    setRcaConfidence(caseQuery.data.root_cause_confidence || '');
    setRcaVerified(caseQuery.data.root_cause_verified);
    setOutcomeStatus(caseQuery.data.outcome_status);
    setOutcomeSummary(caseQuery.data.outcome_summary || '');
    setCorrectiveAction(caseQuery.data.corrective_action || '');
    setInitialized(true);
  }, [caseQuery.data, initialized]);

  const updateInvestigationMutation = useMutation({
    mutationFn: () =>
      api.updateInvestigation(parseInt(caseId || '0'), {
        investigation_status: investigationStatus,
        investigation_note: investigationNote || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case', caseId] });
      setInvestigationNote('');
    },
  });

  const updateRCAMutation = useMutation({
    mutationFn: () =>
      api.updateRCA(parseInt(caseId || '0'), {
        root_cause_status: rcaStatus,
        root_cause_summary: rcaSummary || undefined,
        root_cause_confidence: rcaConfidence ? parseFloat(rcaConfidence.toString()) : undefined,
        root_cause_verified: rcaVerified,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case', caseId] });
    },
  });

  const resolutionRequiresLearningOutcome = outcomeStatus === 'resolved';
  const canSaveResolution = !resolutionRequiresLearningOutcome || Boolean(learningOutcomeStatus);

  const updateResolutionMutation = useMutation({
    mutationFn: () =>
      api.updateResolution(parseInt(caseId || '0'), {
        outcome_status: outcomeStatus,
        outcome_summary: outcomeSummary || undefined,
        corrective_action: correctiveAction || undefined,
        learning_outcome_status: learningOutcomeStatus || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case', caseId] });
    },
  });

  const indexMemoryMutation = useMutation({
    mutationFn: () => api.indexCaseMemory(parseInt(caseId || '0')),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case', caseId] });
    },
  });

  const askAssistant = () => {
    window.location.href = '/assistant';
  };

  const caseData = caseQuery.data;
  const finding = caseData?.finding_snapshot;

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

  const currentStep = useMemo(() => {
    if (!caseData) return 0;
    return stepForCase(caseData.case_status, caseData.investigation_status, caseData.root_cause_status, caseData.outcome_status);
  }, [caseData]);

  const matchedSignals = useMemo(() => {
    const signals = caseSignalsQuery.data ?? [];
    const signalIds = finding?.signal_ids ?? [];
    return signalIds
      .map((signalId) => signals.find((signal) => signal.id === signalId))
      .filter((signal): signal is Signal => Boolean(signal))
      .filter((signal) => signal.severity ? signal.severity.toLowerCase() !== 'low' : signal.importance_score >= 0.55);
  }, [caseSignalsQuery.data, finding?.signal_ids]);

  const signalGroups = useMemo(() => groupSignalsByAnalyzer(matchedSignals), [matchedSignals]);

  const steps = [
    { label: 'Review Finding', icon: <FactCheckRoundedIcon /> },
    { label: 'Investigate', icon: <PlayCircleRoundedIcon /> },
    { label: 'Root Cause', icon: <BuildRoundedIcon /> },
    { label: 'Resolution', icon: <TaskAltRoundedIcon /> },
    { label: 'Publish Knowledge', icon: <AssistantRoundedIcon /> },
  ];

  if (caseQuery.isLoading) return <LoadingSkeleton />;
  if (caseQuery.error) return <ErrorState message="Failed to load case details" />;
  if (!caseData || !finding) return <ErrorState message="Case not found" />;

  const signalIds = finding.signal_ids ?? [];
  const categoryLabel = typeof finding.category === 'string' && finding.category.length > 0 ? finding.category.split('_').join(' ') : 'n/a';
  const memoryLabel = typeof caseData.memory_status === 'string' && caseData.memory_status.length > 0
    ? caseData.memory_status.split('_').join(' ')
    : 'unknown';

  const summaryCards = [
    { label: 'Severity', value: statusLabel(finding.health_status), color: getHealthColor(finding.health_status) },
    { label: 'Importance', value: `${(finding.importance_score * 100).toFixed(0)}%` },
    { label: 'Category', value: categoryLabel },
    { label: 'Service', value: finding.service ?? 'n/a' },
  ];
  const workflowItems = [
    workflowState('Finding reviewed', true, tabValue === 0),
    workflowState('Evidence checked', matchedSignals.length > 0 || signalIds.length > 0, tabValue === 1),
    workflowState('Investigation notes', caseData.investigation_notes.length > 0 || caseData.investigation_status === 'completed', tabValue === 2),
    workflowState('Root cause saved', Boolean(caseData.root_cause_summary) || ['identified', 'confirmed'].includes(caseData.root_cause_status), tabValue === 3),
    workflowState('Resolution recorded', Boolean(caseData.outcome_summary || caseData.corrective_action) || caseData.outcome_status === 'resolved', tabValue === 4),
    workflowState('Knowledge published', caseData.memory_status === 'indexed', tabValue === 5),
  ];
  const nextIncompleteIndex = workflowItems.findIndex((item) => !item.done);
  const nextWorkflowIndex = nextIncompleteIndex === -1 ? 5 : nextIncompleteIndex;
  const nextActionText = nextWorkflowIndex === 0
    ? 'Review the finding summary and evidence.'
    : nextWorkflowIndex === 1
      ? 'Open Evidence and inspect the supporting signals.'
      : nextWorkflowIndex === 2
        ? 'Add an investigation note with what you checked.'
        : nextWorkflowIndex === 3
          ? 'Document the root cause, confidence, and whether it is verified.'
            : nextWorkflowIndex === 4
              ? 'Record the outcome and corrective action.'
              : nextWorkflowIndex === 5
                ? 'Publish this case to operational memory for future matching.'
                : 'Review similar cases for recurring patterns.';

  return (
    <Box sx={{ pb: 4 }}>
      <Stack spacing={2.5}>
        <Box>
          <Button variant="text" onClick={() => window.location.href = '/'} sx={{ px: 0 }}>
            ← Back to Overview
          </Button>

          <Stack
            direction={{ xs: 'column', md: 'row' }}
            justifyContent="space-between"
            alignItems={{ xs: 'flex-start', md: 'center' }}
            spacing={2}
            sx={{ mt: 1 }}
          >
            <Box>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1, flexWrap: 'wrap' }}>
                <Typography variant="h4">Investigation #{caseData.id}</Typography>
                <Chip label={statusLabel(caseData.case_status)} color={caseData.case_status === 'resolved' ? 'success' : 'default'} size="small" />
                <Chip label={`Case ${memoryLabel}`} size="small" variant="outlined" />
              </Stack>
              <Typography variant="h6" color="text.secondary" sx={{ fontWeight: 400 }}>
                {finding.title}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                {finding.summary}
              </Typography>
            </Box>

            <Stack direction="row" spacing={1} alignItems="center">
              <Button variant="outlined" startIcon={<AssistantRoundedIcon />} onClick={askAssistant}>
                Ask Assistant
              </Button>
              {(caseData.memory_status === 'not_indexed' || caseData.memory_status === 'stale' || caseData.memory_status === 'failed') && (
                <Button
                  variant="contained"
                  onClick={() => indexMemoryMutation.mutate()}
                  disabled={indexMemoryMutation.isPending}
                >
                  {indexMemoryMutation.isPending ? 'Indexing…' : 'Add to Memory'}
                </Button>
              )}
            </Stack>
          </Stack>
        </Box>

        <Card variant="outlined">
          <CardContent sx={{ py: 2.5 }}>
            <Stepper activeStep={currentStep} alternativeLabel>
              {steps.map((step, index) => {
                const visualState = stepVisualState(index, currentStep);
                return (
                <Step key={step.label}>
                  <StepLabel
                    icon={step.icon}
                    sx={{
                      '& .MuiStepLabel-label': {
                        color:
                          visualState === 'active'
                            ? 'success.main'
                            : visualState === 'completed'
                              ? 'text.secondary'
                              : 'text.disabled',
                        fontWeight: visualState === 'active' ? 700 : 600,
                      },
                      '& .MuiStepIcon-root': {
                        color:
                          visualState === 'active'
                            ? 'success.main'
                            : visualState === 'completed'
                              ? 'success.light'
                              : 'action.disabled',
                      },
                    }}
                  >
                    {step.label}
                  </StepLabel>
                </Step>
                );
              })}
            </Stepper>
          </CardContent>
        </Card>

        <Grid container spacing={2}>
          <Grid size={{ xs: 12, md: 7 }}>
            <Card
              variant="outlined"
              sx={{
                borderColor: currentStep >= 2 ? 'success.light' : 'divider',
                boxShadow: currentStep >= 2 ? '0 0 0 1px rgba(46, 125, 50, 0.12)' : 'none',
              }}
            >
              <CardContent>
                <Stack spacing={2}>
                  <Typography variant="overline" color="text.secondary">
                    Operational Summary
                  </Typography>
                  <Typography variant="body1">
                    {finding.summary}
                  </Typography>
                  <Grid container spacing={2}>
                    {summaryCards.map((item) => (
                      <Grid key={item.label} size={{ xs: 6, sm: 3 }}>
                        <Box sx={{ p: 1.5, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                          <Typography variant="caption" color="text.secondary">
                            {item.label}
                          </Typography>
                          <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 0.5 }}>
                            <Typography variant="body2" sx={{ fontWeight: 700 }}>
                              {item.value}
                            </Typography>
                            {'color' in item && item.color ? <Chip size="small" color={item.color} label={statusLabel(finding.health_status)} /> : null}
                          </Stack>
                        </Box>
                      </Grid>
                    ))}
                  </Grid>

                  <Box sx={{ pt: 1 }}>
                    <Typography variant="caption" color="text.secondary">
                      Signals used
                    </Typography>
                    <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: 'wrap' }}>
                      {signalGroups.length > 0 ? (
                        signalGroups.map((group) => (
                          <Tooltip key={group.key} title={<span style={{ whiteSpace: 'pre-line' }}>{signalGroupTooltip(group)}</span>} arrow>
                            <Chip label={signalGroupChipLabel(group)} size="small" variant="outlined" />
                          </Tooltip>
                        ))
                      ) : (
                        <Chip label="No problem-signals matched" size="small" variant="outlined" />
                      )}
                    </Stack>
                  </Box>
                </Stack>
              </CardContent>
            </Card>
          </Grid>

          <Grid size={{ xs: 12, md: 5 }}>
            <Card
              variant="outlined"
              sx={{
                height: '100%',
                borderColor: currentStep === 1 ? 'success.light' : 'divider',
                boxShadow: currentStep === 1 ? '0 0 0 1px rgba(46, 125, 50, 0.12)' : 'none',
              }}
            >
              <CardContent>
                <Stack spacing={2}>
                  <Typography variant="overline" color="text.secondary">
                    Next Action
                  </Typography>
                  <Typography variant="body1" sx={{ fontWeight: 600 }}>
                    {currentStep === 0
                      ? 'Review the finding and decide whether this is actionable.'
                      : currentStep === 1
                        ? 'Capture investigation notes and inspect the evidence.'
                        : currentStep === 2
                          ? 'Document the root cause and confidence.'
                          : currentStep === 3
                            ? 'Record the resolution and corrective action.'
                            : 'Confirm the outcome and publish knowledge.'}
                  </Typography>
                  <Button variant="contained" onClick={() => setTabValue(Math.min(currentStep + 1, 4))}>
                    Continue Investigation
                  </Button>
                </Stack>
              </CardContent>
            </Card>
          </Grid>
        </Grid>

        <Card variant="outlined">
          <CardContent sx={{ py: 2 }}>
            <Stack spacing={2}>
              <Stack direction={{ xs: 'column', lg: 'row' }} justifyContent="space-between" spacing={2}>
                <Box>
                  <Typography variant="overline" color="text.secondary">Workflow Status</Typography>
                  <Typography variant="body1" sx={{ fontWeight: 700 }}>{nextActionText}</Typography>
                </Box>
                <Button
                  variant="contained"
                  endIcon={<ArrowForwardRoundedIcon />}
                  onClick={() => setTabValue(nextWorkflowIndex)}
                  sx={{ alignSelf: { xs: 'stretch', lg: 'center' } }}
                >
                  {nextWorkflowIndex >= workflowItems.length ? 'Review Similar Cases' : `Go to ${workflowItems[nextWorkflowIndex].label}`}
                </Button>
              </Stack>
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                {workflowItems.map((item, index) => (
                  <Chip
                    key={item.label}
                    icon={item.done ? <CheckCircleRoundedIcon /> : <RadioButtonUncheckedRoundedIcon />}
                    label={`${index + 1}. ${item.label}`}
                    color={item.done ? 'success' : item.active ? 'primary' : 'default'}
                    variant={item.done || item.active ? 'filled' : 'outlined'}
                    onClick={() => setTabValue(index)}
                    sx={{ fontWeight: 700 }}
                  />
                ))}
              </Stack>
              <Tabs value={tabValue} onChange={(_, newValue) => setTabValue(newValue)} variant="scrollable" scrollButtons="auto">
                <Tab label="Overview" id="case-tab-0" aria-controls="case-tabpanel-0" />
                <Tab label="Evidence" id="case-tab-1" aria-controls="case-tabpanel-1" />
                <Tab label="Investigation" id="case-tab-2" aria-controls="case-tabpanel-2" />
                <Tab label="Root Cause" id="case-tab-3" aria-controls="case-tabpanel-3" />
                <Tab label="Resolution" id="case-tab-4" aria-controls="case-tabpanel-4" />
                <Tab label="Publish Knowledge" id="case-tab-5" aria-controls="case-tabpanel-5" />
                <Tab label="Similar Cases" id="case-tab-6" aria-controls="case-tabpanel-6" />
              </Tabs>
            </Stack>
          </CardContent>
        </Card>

        <TabPanel value={tabValue} index={0}>
          <Grid container spacing={2}>
            <Grid size={{ xs: 12, md: 7 }}>
              <Card variant="outlined">
                <CardContent>
                  <Typography variant="h6" sx={{ mb: 2 }}>
                    Why this case exists
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                    The system detected a change in {finding.metric_name} that is worth reviewing before it is dismissed as normal variation.
                  </Typography>
                  <Stack spacing={1.5}>
                    <Box>
                      <Typography variant="caption" color="text.secondary">
                        Case title
                      </Typography>
                      <Typography variant="body2">{caseData.case_title}</Typography>
                    </Box>
                    <Box>
                      <Typography variant="caption" color="text.secondary">
                        Created
                      </Typography>
                      <Typography variant="body2">{new Date(caseData.created_at).toLocaleString()}</Typography>
                    </Box>
                    {caseData.resolved_at ? (
                      <Box>
                        <Typography variant="caption" color="text.secondary">
                          Resolved
                        </Typography>
                        <Typography variant="body2">{new Date(caseData.resolved_at).toLocaleString()}</Typography>
                      </Box>
                    ) : null}
                  </Stack>
                </CardContent>
              </Card>
            </Grid>

            <Grid size={{ xs: 12, md: 5 }}>
              <Card variant="outlined">
                <CardContent>
                  <Typography variant="h6" sx={{ mb: 2 }}>
                    Suggested focus
                  </Typography>
                  <Stack spacing={1}>
                    <Typography variant="body2">• Review the signal evidence window</Typography>
                    <Typography variant="body2">• Check whether the change is expected</Typography>
                    <Typography variant="body2">• Capture the first hypothesis in Investigation</Typography>
                    <Typography variant="body2">• Move to root cause once the pattern is clear</Typography>
                  </Stack>
                </CardContent>
              </Card>
            </Grid>
          </Grid>
        </TabPanel>

        <TabPanel value={tabValue} index={1}>
          <Grid container spacing={2}>
            <Grid size={{ xs: 12, md: 5 }}>
              <Card variant="outlined">
                <CardContent>
                  <Typography variant="h6" sx={{ mb: 2 }}>
                    Signals used
                  </Typography>
                  <Typography variant="body2" sx={{ mb: 1 }}>
                    {matchedSignals.length} supporting signal{matchedSignals.length !== 1 ? 's' : ''} detected.
                  </Typography>
                  <Stack spacing={1}>
                    {signalGroups.length > 0 ? (
                      signalGroups.map((group) => (
                        <Tooltip key={group.key} title={<span style={{ whiteSpace: 'pre-line' }}>{signalGroupTooltip(group)}</span>} arrow>
                          <Chip label={signalGroupChipLabel(group)} variant="outlined" sx={{ justifyContent: 'flex-start' }} />
                        </Tooltip>
                      ))
                    ) : (
                      <Typography variant="body2" color="text.secondary">
                        No problem-signals matched.
                      </Typography>
                    )}
                  </Stack>
                </CardContent>
              </Card>
            </Grid>
            <Grid size={{ xs: 12, md: 7 }}>
              <Card variant="outlined">
                <CardContent>
                  <Typography variant="h6" sx={{ mb: 2 }}>
                    Comparison details
                  </Typography>
                  <Box sx={{ bgcolor: 'grey.50', p: 2, borderRadius: 2, overflowX: 'auto' }}>
                    <Typography variant="caption" component="pre" sx={{ m: 0, whiteSpace: 'pre-wrap' }}>
                      {JSON.stringify(finding.comparison_json, null, 2)}
                    </Typography>
                  </Box>
                </CardContent>
              </Card>
            </Grid>
          </Grid>
        </TabPanel>

        <TabPanel value={tabValue} index={2}>
          <Grid container spacing={2}>
            <Grid size={{ xs: 12, md: 7 }}>
              <Card
                variant="outlined"
                sx={{
                  borderColor: investigationStatus === 'in_progress' ? 'success.light' : 'divider',
                  boxShadow: investigationStatus === 'in_progress' ? '0 0 0 1px rgba(46, 125, 50, 0.12)' : 'none',
                }}
              >
                <CardContent>
                  <Typography variant="h6" sx={{ mb: 2 }}>
                    Update Investigation
                  </Typography>
                  <Stack spacing={2}>
                    <FormControl fullWidth>
                      <InputLabel>Status</InputLabel>
                      <Select value={investigationStatus} onChange={(e) => setInvestigationStatus(e.target.value)} label="Status">
                        <MenuItem value="not_started">Not Started</MenuItem>
                        <MenuItem value="in_progress">In Progress</MenuItem>
                        <MenuItem value="completed">Completed</MenuItem>
                      </Select>
                    </FormControl>

                    <TextField
                      label="Investigation note"
                      multiline
                      rows={4}
                      value={investigationNote}
                      onChange={(e) => setInvestigationNote(e.target.value)}
                      placeholder="Capture what you checked, what you ruled out, and what to do next."
                    />

                    <Button variant="contained" onClick={() => updateInvestigationMutation.mutate()} disabled={updateInvestigationMutation.isPending}>
                      {updateInvestigationMutation.isPending ? <CircularProgress size={20} sx={{ mr: 1 }} /> : null}
                      Save Investigation
                    </Button>
                  </Stack>
                </CardContent>
              </Card>
            </Grid>

            <Grid size={{ xs: 12, md: 5 }}>
              <Card variant="outlined">
                <CardContent>
                  <Typography variant="h6" sx={{ mb: 2 }}>
                    Investigation notes
                  </Typography>
                  {caseData.investigation_notes.length === 0 ? (
                    <Typography variant="body2" color="text.secondary">
                      No notes yet.
                    </Typography>
                  ) : (
                    <Stack spacing={1}>
                      {caseData.investigation_notes.map((note, index) => (
                        <Box key={index} sx={{ p: 1.5, bgcolor: 'grey.50', borderRadius: 2 }}>
                          <Typography variant="caption" color="text.secondary">
                            {note.timestamp ? new Date(note.timestamp).toLocaleString() : 'No timestamp'}
                          </Typography>
                          <Typography variant="body2">{note.note}</Typography>
                        </Box>
                      ))}
                    </Stack>
                  )}
                </CardContent>
              </Card>
            </Grid>
          </Grid>
        </TabPanel>

        <TabPanel value={tabValue} index={3}>
          <Grid container spacing={2}>
            <Grid size={{ xs: 12, lg: 8 }}>
              <Card
                variant="outlined"
                sx={{
                  borderColor: rcaStatus === 'investigating' || rcaStatus === 'identified' ? 'success.light' : 'divider',
                  boxShadow: rcaStatus === 'investigating' || rcaStatus === 'identified' ? '0 0 0 1px rgba(46, 125, 50, 0.12)' : 'none',
                }}
              >
                <CardContent>
                  <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={1.5} sx={{ mb: 2 }}>
                    <Box>
                      <Typography variant="h6">Root Cause</Typography>
                      <Typography variant="body2" color="text.secondary">
                        Step 4 of 5. Save this before moving to Resolution.
                      </Typography>
                    </Box>
                    <Chip
                      label={workflowItems[3].done ? 'Completed' : tabValue === 3 ? 'Current step' : 'Not completed'}
                      color={workflowItems[3].done ? 'success' : 'primary'}
                      variant={workflowItems[3].done ? 'filled' : 'outlined'}
                    />
                  </Stack>
                  <Stack spacing={2}>
                    <FormControl fullWidth>
                      <InputLabel>Status</InputLabel>
                      <Select value={rcaStatus} onChange={(e) => setRcaStatus(e.target.value)} label="Status">
                        <MenuItem value="unknown">Unknown</MenuItem>
                        <MenuItem value="investigating">Investigating</MenuItem>
                        <MenuItem value="identified">Identified</MenuItem>
                        <MenuItem value="confirmed">Confirmed</MenuItem>
                      </Select>
                    </FormControl>

                    <TextField
                      label="Root cause summary"
                      multiline
                      rows={4}
                      value={rcaSummary}
                      onChange={(e) => setRcaSummary(e.target.value)}
                      placeholder="Example: traffic spike caused CPU saturation after the checkout deployment increased request volume."
                      helperText="Write the operational reason, not just the metric symptom."
                    />

                    <TextField
                      label="Confidence (0-1)"
                      type="number"
                      inputProps={{ step: 0.01, min: 0, max: 1 }}
                      value={rcaConfidence}
                      onChange={(e) => setRcaConfidence(e.target.value)}
                      helperText="Use 0.5 for a hypothesis, 0.8+ when evidence strongly supports it."
                    />

                    <FormControlLabel
                      control={<Checkbox checked={rcaVerified} onChange={(e) => setRcaVerified(e.target.checked)} />}
                      label="Verified by investigation evidence"
                    />

                    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
                      <Button variant="contained" onClick={() => updateRCAMutation.mutate()} disabled={updateRCAMutation.isPending}>
                        {updateRCAMutation.isPending ? <CircularProgress size={20} sx={{ mr: 1 }} /> : null}
                        Save Root Cause
                      </Button>
                      <Button variant="outlined" onClick={() => setTabValue(4)} endIcon={<ArrowForwardRoundedIcon />}>
                        Next: Resolution
                      </Button>
                    </Stack>
                  </Stack>
                </CardContent>
              </Card>
            </Grid>
            <Grid size={{ xs: 12, lg: 4 }}>
              <Card variant="outlined" sx={{ height: '100%' }}>
                <CardContent>
                  <Typography variant="h6" sx={{ mb: 2 }}>What To Do Here</Typography>
                  <Stack spacing={1.5}>
                    <WorkflowHint done={rcaStatus !== 'unknown'} text="Choose whether the RCA is investigating, identified, or confirmed." />
                    <WorkflowHint done={Boolean(rcaSummary.trim())} text="Summarize the cause in one clear sentence." />
                    <WorkflowHint done={Boolean(rcaConfidence)} text="Set confidence so future readers know how certain this is." />
                    <WorkflowHint done={rcaVerified} text="Mark verified only after evidence supports the cause." />
                  </Stack>
                  <Alert severity="info" sx={{ mt: 2 }}>
                    After saving, record the fix or outcome in Resolution.
                  </Alert>
                </CardContent>
              </Card>
            </Grid>
          </Grid>
        </TabPanel>

        <TabPanel value={tabValue} index={4}>
          <Card
            variant="outlined"
            sx={{
              borderColor: outcomeStatus === 'in_progress' || outcomeStatus === 'resolved' ? 'success.light' : 'divider',
              boxShadow: outcomeStatus === 'in_progress' || outcomeStatus === 'resolved' ? '0 0 0 1px rgba(46, 125, 50, 0.12)' : 'none',
            }}
          >
            <CardContent>
              <Typography variant="h6" sx={{ mb: 2 }}>
                Resolution
              </Typography>
              <Stack spacing={2}>
                <FormControl fullWidth>
                  <InputLabel>Outcome Status</InputLabel>
                  <Select value={outcomeStatus} onChange={(e) => setOutcomeStatus(e.target.value)} label="Outcome Status">
                    <MenuItem value="pending">Pending</MenuItem>
                    <MenuItem value="in_progress">In Progress</MenuItem>
                    <MenuItem value="resolved">Resolved</MenuItem>
                    <MenuItem value="escalated">Escalated</MenuItem>
                  </Select>
                </FormControl>

                <TextField
                  label="Outcome summary"
                  multiline
                  rows={4}
                  value={outcomeSummary}
                  onChange={(e) => setOutcomeSummary(e.target.value)}
                />

                <TextField
                  label="Corrective action"
                  multiline
                  rows={4}
                  value={correctiveAction}
                  onChange={(e) => setCorrectiveAction(e.target.value)}
                />

                {resolutionRequiresLearningOutcome ? (
                  <FormControl fullWidth required error={!learningOutcomeStatus}>
                    <InputLabel>Learning Outcome</InputLabel>
                    <Select
                      value={learningOutcomeStatus}
                      onChange={(e) => setLearningOutcomeStatus(e.target.value)}
                      label="Learning Outcome"
                    >
                      <MenuItem value="confirmed">Confirmed — this was a real issue</MenuItem>
                      <MenuItem value="partially_confirmed">Partially confirmed — real, but not fully understood</MenuItem>
                      <MenuItem value="rejected">Rejected — false positive, not a real issue</MenuItem>
                      <MenuItem value="inconclusive">Inconclusive — could not determine</MenuItem>
                    </Select>
                    <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5 }}>
                      Required when marking a case Resolved — records whether this was a real issue so similar
                      future alerts can learn from it.
                    </Typography>
                  </FormControl>
                ) : null}

                {updateResolutionMutation.isError ? (
                  <Alert severity="error">
                    {updateResolutionMutation.error instanceof Error
                      ? updateResolutionMutation.error.message
                      : 'Failed to save resolution.'}
                  </Alert>
                ) : null}

                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
                  <Button
                    variant="contained"
                    onClick={() => updateResolutionMutation.mutate()}
                    disabled={updateResolutionMutation.isPending || !canSaveResolution}
                  >
                    {updateResolutionMutation.isPending ? <CircularProgress size={20} sx={{ mr: 1 }} /> : null}
                    Save Resolution
                  </Button>
                  <Button variant="outlined" onClick={() => setTabValue(5)} endIcon={<ArrowForwardRoundedIcon />}>
                    Next: Publish Knowledge
                  </Button>
                </Stack>
              </Stack>
            </CardContent>
          </Card>
        </TabPanel>

        <TabPanel value={tabValue} index={5}>
          <Grid container spacing={2}>
            <Grid size={{ xs: 12, lg: 8 }}>
              <Card variant="outlined">
                <CardContent>
                  <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={1.5} sx={{ mb: 2 }}>
                    <Box>
                      <Typography variant="h6">Publish Knowledge</Typography>
                      <Typography variant="body2" color="text.secondary">
                        Final step. Index this case into Operational Memory so future similar cases can retrieve it.
                      </Typography>
                    </Box>
                    <Chip
                      label={statusLabel(caseData.memory_status)}
                      color={caseData.memory_status === 'indexed' ? 'success' : caseData.memory_status === 'failed' ? 'error' : 'default'}
                    />
                  </Stack>

                  <Stack spacing={2}>
                    <Alert severity={caseData.memory_status === 'indexed' ? 'success' : 'info'}>
                      {caseData.memory_status === 'indexed'
                        ? 'This case is already published to Operational Memory.'
                        : caseData.memory_status === 'stale'
                          ? 'This case was changed after indexing. Publish again to refresh memory.'
                          : 'Resolution does not automatically publish to vector memory. Use this action when the case is ready to become reusable knowledge.'}
                    </Alert>
                    <Grid container spacing={2}>
                      <Grid size={{ xs: 12, md: 4 }}>
                        <Box sx={{ p: 1.5, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                          <Typography variant="caption" color="text.secondary">Root Cause</Typography>
                          <Typography variant="body2" sx={{ fontWeight: 700 }}>{caseData.root_cause_summary ? 'Captured' : 'Missing'}</Typography>
                        </Box>
                      </Grid>
                      <Grid size={{ xs: 12, md: 4 }}>
                        <Box sx={{ p: 1.5, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                          <Typography variant="caption" color="text.secondary">Resolution</Typography>
                          <Typography variant="body2" sx={{ fontWeight: 700 }}>{caseData.outcome_summary || caseData.corrective_action ? 'Captured' : 'Missing'}</Typography>
                        </Box>
                      </Grid>
                      <Grid size={{ xs: 12, md: 4 }}>
                        <Box sx={{ p: 1.5, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                          <Typography variant="caption" color="text.secondary">Memory</Typography>
                          <Typography variant="body2" sx={{ fontWeight: 700 }}>{statusLabel(caseData.memory_status)}</Typography>
                        </Box>
                      </Grid>
                    </Grid>
                    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
                      <Button
                        variant="contained"
                        onClick={() => indexMemoryMutation.mutate()}
                        disabled={indexMemoryMutation.isPending || caseData.memory_status === 'indexed'}
                      >
                        {indexMemoryMutation.isPending ? <CircularProgress size={20} sx={{ mr: 1 }} /> : null}
                        {caseData.memory_status === 'indexed' ? 'Published' : caseData.memory_status === 'stale' ? 'Refresh Knowledge' : 'Publish Knowledge'}
                      </Button>
                      <Button variant="outlined" onClick={() => setTabValue(6)} endIcon={<ArrowForwardRoundedIcon />}>
                        Next: Similar Cases
                      </Button>
                    </Stack>
                  </Stack>
                </CardContent>
              </Card>
            </Grid>
            <Grid size={{ xs: 12, lg: 4 }}>
              <Card variant="outlined" sx={{ height: '100%' }}>
                <CardContent>
                  <Typography variant="h6" sx={{ mb: 2 }}>Publish Checklist</Typography>
                  <Stack spacing={1.5}>
                    <WorkflowHint done={Boolean(caseData.root_cause_summary)} text="Root cause has been captured." />
                    <WorkflowHint done={Boolean(caseData.outcome_summary || caseData.corrective_action)} text="Resolution or corrective action has been recorded." />
                    <WorkflowHint done={caseData.memory_status === 'indexed'} text="Case is indexed in Operational Memory." />
                  </Stack>
                </CardContent>
              </Card>
            </Grid>
          </Grid>
        </TabPanel>

        <TabPanel value={tabValue} index={6}>
          <SimilarCasesList caseId={parseInt(caseId || '0')} />
        </TabPanel>

        {caseData.memory_status === 'failed' ? <Alert severity="warning">Memory indexing failed for this case. You can retry from the header.</Alert> : null}
      </Stack>
    </Box>
  );
}

function SimilarCasesList({ caseId }: { caseId: number }) {
  const { data: similarCases, isLoading, error } = useQuery({
    queryKey: ['similarCases', caseId],
    queryFn: () => api.getSimilarCases(caseId, 5, 0.7),
  });

  if (isLoading) return <CircularProgress />;
  if (error) return <Alert severity="error">Failed to load similar cases</Alert>;

  if (!similarCases?.matches || similarCases.matches.length === 0) {
    return <Alert severity="info">No similar cases found</Alert>;
  }

  return (
    <Stack spacing={2}>
      {similarCases.matches.map((match: any) => (
        <Card key={match.case_id} variant="outlined">
          <CardContent>
            <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={2}>
              <Box>
                <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                  {match.title}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {match.service} · {match.metric_name} · {statusLabel(match.case_status)}
                </Typography>
                {match.root_cause_summary ? (
                  <Typography variant="body2" sx={{ mt: 1 }}>
                    RCA: {match.root_cause_summary}
                  </Typography>
                ) : null}
              </Box>
              <Stack alignItems="flex-end" spacing={1}>
                <Typography variant="h5" sx={{ fontWeight: 700, color: 'primary.main' }}>
                  {(match.similarity_score * 100).toFixed(0)}%
                </Typography>
                <Button size="small" variant="text" onClick={() => (window.location.href = `/cases/${match.case_id}`)}>
                  Open Case
                </Button>
              </Stack>
            </Stack>
          </CardContent>
        </Card>
      ))}
    </Stack>
  );
}

function WorkflowHint({ done, text }: { done: boolean; text: string }) {
  return (
    <Stack direction="row" spacing={1.2} alignItems="flex-start">
      {done ? (
        <CheckCircleRoundedIcon color="success" fontSize="small" sx={{ mt: 0.2 }} />
      ) : (
        <RadioButtonUncheckedRoundedIcon color="disabled" fontSize="small" sx={{ mt: 0.2 }} />
      )}
      <Typography variant="body2" color={done ? 'text.primary' : 'text.secondary'}>
        {text}
      </Typography>
    </Stack>
  );
}
