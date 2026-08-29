import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Collapse,
  Chip,
  Divider,
  Drawer,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import AddRoundedIcon from '@mui/icons-material/AddRounded';
import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded';
import CancelRoundedIcon from '@mui/icons-material/CancelRounded';
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded';
import FileUploadRoundedIcon from '@mui/icons-material/FileUploadRounded';
import FactCheckRoundedIcon from '@mui/icons-material/FactCheckRounded';
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';
import SaveRoundedIcon from '@mui/icons-material/SaveRounded';
import VerifiedRoundedIcon from '@mui/icons-material/VerifiedRounded';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { deleteJson, getJson, postJson } from '../../api/client';
import { PageHeader, WorkspacePanel } from '../../standalone/components';
import { ui } from '../../standalone/theme';

type RuleOperator = 'gte' | 'gt' | 'lte' | 'lt' | 'equals';

type ScoringRule = {
  metric: string;
  operator: RuleOperator;
  threshold: number | boolean;
  add: number;
};

type AnalyzerConfig = {
  analyzer_id: string;
  display_name: string;
  template_type: string;
  library: string;
  enabled: boolean;
  runtime_mapping: string;
  supported_profiles: string[];
  min_samples: number;
  requires_regular_sampling: boolean;
  requires_numeric: boolean;
  base_score: number;
  scoring_rules: ScoringRule[];
  runtime_params: Record<string, unknown>;
  selected_explanation: string;
  excluded_explanation: string;
  source?: 'builtin' | 'custom';
  routable?: boolean;
  executable?: boolean;
};

type TestRouteResult = {
  recommendation: string;
  final_score: number;
  eligible: boolean;
  runtime_status: string;
  reasons: string[];
};

type LabProfileId = 'zscore_anomaly' | 'pyod_outlier' | 'prophet_forecast' | 'ruptures_change_point' | 'stumpy_motif' | 'trend';

type LabRoutingResult = TestRouteResult & {
  analyzer_id: string;
  lab_profile: LabProfileId;
  lab_profile_label: string;
  detected_profiles: string[];
  matched_rules: Record<string, unknown>[];
};

type RunStatus = 'not_run' | 'passed' | 'failed';

type LibraryCheckResult = {
  package: string;
  import_name: string;
  installed: boolean;
  status: 'unknown' | 'verified' | 'missing';
  version?: string | null;
  error?: string | null;
  suggested_install?: string | null;
};

type AnalyzerReadiness = {
  analyzer_id: string;
  library?: string | null;
  import_name?: string | null;
  library_importable?: boolean | null;
  library_status: 'unknown' | 'verified' | 'missing';
  library_error?: string | null;
  router_definition_exists: boolean;
  router_definition_status: 'missing' | 'draft' | 'saved';
  router_definition_source?: 'builtin' | 'custom' | null;
  config_exists: boolean;
  runtime_mapping: string;
  runtime_mapping_status: 'not_implemented' | 'executable' | 'mapped_to_missing_runtime';
  backend_implementation_exists: boolean;
  executable: boolean;
  execution_test_status: RunStatus;
  benchmark_status: RunStatus;
};

type RuntimeMapping = {
  id: string;
  label: string;
  executable: boolean;
  description: string;
};

type DraftStatus = 'draft' | 'routing_tested' | 'ready_for_backend' | 'executable' | 'benchmark_passed';

type AnalyzerDraft = {
  id: number;
  analyzer_id: string;
  display_name: string;
  status: DraftStatus;
  config: AnalyzerConfig;
  readiness: Record<string, unknown>;
  routing_test: Record<string, unknown>;
  execution_test: Record<string, unknown>;
  benchmark: Record<string, unknown>;
  promoted_at?: string | null;
  updated_at: string;
};

type ExecutionTestResult = {
  analyzer_id: string;
  available: boolean;
  status: RunStatus | 'unavailable';
  reason: string;
  runtime_mapping: string;
  sample_count: number;
  signal_count: number;
  finding_count: number;
};

type RuntimeDesign = {
  type: 'internal_python' | 'external_http' | 'not_implemented';
  health_check_url?: string;
  analyze_url?: string;
};

type YamlPreview = {
  analyzer_id: string;
  yaml_text: string;
};

type WorkflowState = 'done' | 'current' | 'waiting' | 'blocked';

const profileOptions = ['seasonal', 'motif', 'repeating_pattern', 'trend', 'baseline_shift', 'regime_change', 'anomaly', 'outlier', 'spike', 'forecast', 'mixed'];
const metricOptions = ['sample_count', 'regular_sampling', 'seasonality_strength', 'trend_strength', 'shift_index', 'spikiness', 'missing_percentage', 'irregular_sampling_percentage', 'behavior_mix'];
const runtimeTypeOptions: RuntimeDesign['type'][] = ['not_implemented', 'internal_python', 'external_http'];
const labProfileOptions: Array<{ id: LabProfileId; label: string }> = [
  { id: 'zscore_anomaly', label: 'Z-Score anomaly generated data' },
  { id: 'pyod_outlier', label: 'PyOD outlier generated data' },
  { id: 'prophet_forecast', label: 'Prophet forecast generated data' },
  { id: 'ruptures_change_point', label: 'Ruptures change-point generated data' },
  { id: 'stumpy_motif', label: 'STUMPY motif generated data' },
  { id: 'trend', label: 'Trend generated data' },
];

const motifTemplate: AnalyzerConfig = {
  analyzer_id: 'motif_detection',
  display_name: 'Motif Detection',
  template_type: 'Motif / Repeating Pattern',
  library: 'stumpy',
  enabled: true,
  runtime_mapping: 'stumpy',
  supported_profiles: ['seasonal', 'motif', 'repeating_pattern'],
  min_samples: 30,
  requires_regular_sampling: true,
  requires_numeric: true,
  base_score: 0.3,
  scoring_rules: [
    { metric: 'seasonality_strength', operator: 'gte', threshold: 0.42, add: 0.2 },
    { metric: 'seasonality_strength', operator: 'gte', threshold: 0.65, add: 0.22 },
    { metric: 'regular_sampling', operator: 'equals', threshold: true, add: 0.08 },
    { metric: 'sample_count', operator: 'gte', threshold: 60, add: 0.04 },
  ],
  runtime_params: { window_size: 20, motif_count: 1, profile_threshold: 2.0 },
  selected_explanation: 'The series appears to repeat similar shapes or seasonal motifs.',
  excluded_explanation: 'The series is too irregular or too short for reliable motif discovery.',
};

function updateRule(rules: ScoringRule[], index: number, patch: Partial<ScoringRule>) {
  return rules.map((rule, idx) => (idx === index ? { ...rule, ...patch } : rule));
}

export function AddAnalyzerPage() {
  const queryClient = useQueryClient();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [form, setForm] = useState<AnalyzerConfig>(motifTemplate);
  const [testResult, setTestResult] = useState<TestRouteResult | null>(null);
  const [labProfile, setLabProfile] = useState<LabProfileId>('stumpy_motif');
  const [labRoutingResult, setLabRoutingResult] = useState<LabRoutingResult | null>(null);
  const [executionTestStatus, setExecutionTestStatus] = useState<RunStatus>('not_run');
  const [benchmarkStatus] = useState<RunStatus>('not_run');
  const [importName, setImportName] = useState(motifTemplate.library);
  const [libraryCheckResult, setLibraryCheckResult] = useState<LibraryCheckResult | null>(null);
  const [selectedDraft, setSelectedDraft] = useState<AnalyzerDraft | null>(null);
  const [executionTestResult, setExecutionTestResult] = useState<ExecutionTestResult | null>(null);
  const [expandedCompletedSteps, setExpandedCompletedSteps] = useState<Record<string, boolean>>({});

  const analyzers = useQuery({
    queryKey: ['admin-analyzers'],
    queryFn: () => getJson<AnalyzerConfig[]>('/api/admin/analyzers'),
  });
  const runtimeMappings = useQuery({
    queryKey: ['analyzer-runtime-mappings'],
    queryFn: () => getJson<RuntimeMapping[]>('/api/analyzer-labs/runtime-mappings'),
  });
  const drafts = useQuery({
    queryKey: ['analyzer-drafts'],
    queryFn: () => getJson<AnalyzerDraft[]>('/api/analyzer-labs/drafts'),
  });

  const savedAnalyzer = useMemo(
    () => (analyzers.data ?? []).find((item) => item.analyzer_id === form.analyzer_id),
    [analyzers.data, form.analyzer_id],
  );
  const customAnalyzers = useMemo(
    () => (analyzers.data ?? []).filter((item) => item.source === 'custom'),
    [analyzers.data],
  );
  const activeDrafts = useMemo(
    () => (drafts.data ?? []).filter((draft) => !draft.promoted_at),
    [drafts.data],
  );
  const formHasDraftChanges = Boolean(
    form.analyzer_id &&
      (!savedAnalyzer ||
        savedAnalyzer.display_name !== form.display_name ||
        savedAnalyzer.library !== form.library ||
        savedAnalyzer.runtime_mapping !== form.runtime_mapping),
  );
  const readinessPath = useMemo(() => {
    if (!form.analyzer_id.trim()) return null;
    const params = new URLSearchParams();
    if (form.library.trim()) params.set('library', form.library.trim());
    if (importName.trim()) params.set('import_name', importName.trim());
    if (form.runtime_mapping.trim()) params.set('runtime_mapping', form.runtime_mapping.trim());
    return `/api/analyzer-labs/readiness/${encodeURIComponent(form.analyzer_id.trim())}?${params.toString()}`;
  }, [form.analyzer_id, form.library, form.runtime_mapping, importName]);
  const readiness = useQuery({
    queryKey: ['analyzer-readiness', form.analyzer_id, form.library, importName, form.runtime_mapping],
    queryFn: () => getJson<AnalyzerReadiness>(readinessPath ?? ''),
    enabled: Boolean(readinessPath),
  });

  const saveDraftMutation = useMutation({
    mutationFn: (payload: AnalyzerConfig) => postJson<{ config: AnalyzerConfig }, AnalyzerDraft>('/api/analyzer-labs/drafts', { config: payload }),
    onSuccess: (draft) => {
      setSelectedDraft(draft);
      setTestResult(null);
      setLabRoutingResult(null);
      setExecutionTestResult(null);
      setExecutionTestStatus('not_run');
      queryClient.invalidateQueries({ queryKey: ['analyzer-drafts'] });
      queryClient.invalidateQueries({ queryKey: ['analyzer-readiness'] });
    },
  });

  const promoteDraftMutation = useMutation({
    mutationFn: (draftId: number) => postJson<Record<string, never>, AnalyzerDraft>(`/api/analyzer-labs/drafts/${draftId}/promote`, {}),
    onSuccess: (draft) => {
      setSelectedDraft(draft);
      queryClient.invalidateQueries({ queryKey: ['admin-analyzers'] });
      queryClient.invalidateQueries({ queryKey: ['analyzer-drafts'] });
      queryClient.invalidateQueries({ queryKey: ['analyzer-readiness'] });
      setDrawerOpen(false);
    },
  });

  const markRoutingTestMutation = useMutation({
    mutationFn: (draftId: number) => postJson<Record<string, never>, AnalyzerDraft>(`/api/analyzer-labs/drafts/${draftId}/routing-test`, {}),
    onSuccess: (draft) => {
      setSelectedDraft(draft);
      queryClient.invalidateQueries({ queryKey: ['analyzer-drafts'] });
    },
  });

  const testMutation = useMutation({
    mutationFn: (payload: AnalyzerConfig) => postJson<AnalyzerConfig, TestRouteResult>('/api/admin/analyzers/test-route', payload),
    onSuccess: (result) => {
      setTestResult(result);
      if (selectedDraft) {
        markRoutingTestMutation.mutate(selectedDraft.id);
      }
    },
  });

  const labRoutingMutation = useMutation({
    mutationFn: () =>
      postJson<{ config: AnalyzerConfig; lab_profile: LabProfileId }, LabRoutingResult>('/api/analyzer-labs/lab-routing-test', {
        config: form,
        lab_profile: labProfile,
      }),
    onSuccess: setLabRoutingResult,
  });

  const executionTestMutation = useMutation({
    mutationFn: (draftId: number) => postJson<Record<string, never>, ExecutionTestResult>(`/api/analyzer-labs/drafts/${draftId}/execution-test`, {}),
    onSuccess: (result) => {
      setExecutionTestResult(result);
      setExecutionTestStatus(result.status === 'passed' ? 'passed' : result.status === 'failed' ? 'failed' : 'not_run');
      queryClient.invalidateQueries({ queryKey: ['analyzer-drafts'] });
    },
  });

  const deleteDraftMutation = useMutation({
    mutationFn: (draftId: number) => deleteJson<{ deleted: number }>(`/api/analyzer-labs/drafts/${draftId}`),
    onSuccess: (_, draftId) => {
      if (selectedDraft?.id === draftId) {
        setSelectedDraft(null);
        setTestResult(null);
        setLabRoutingResult(null);
        setLibraryCheckResult(null);
        setExecutionTestResult(null);
        setExecutionTestStatus('not_run');
      }
      queryClient.invalidateQueries({ queryKey: ['analyzer-drafts'] });
    },
  });

  const deleteCustomAnalyzerMutation = useMutation({
    mutationFn: (analyzerId: string) => deleteJson<{ deleted: number; analyzer_id: string }>(`/api/admin/analyzers/${encodeURIComponent(analyzerId)}`),
    onSuccess: (_, analyzerId) => {
      if (form.analyzer_id === analyzerId && !currentDraft) {
        setTestResult(null);
        setLabRoutingResult(null);
        setLibraryCheckResult(null);
        setExecutionTestResult(null);
        setExecutionTestStatus('not_run');
      }
      queryClient.invalidateQueries({ queryKey: ['admin-analyzers'] });
      queryClient.invalidateQueries({ queryKey: ['analyzer-readiness'] });
    },
  });

  const verifyLibraryMutation = useMutation({
    mutationFn: () =>
      postJson<{ package: string; import_name?: string }, LibraryCheckResult>('/api/analyzer-labs/libraries/check', {
        package: form.library,
        import_name: importName || form.library,
      }),
    onSuccess: (result) => {
      setLibraryCheckResult(result);
      queryClient.invalidateQueries({ queryKey: ['analyzer-readiness'] });
    },
  });

  const runtimeParamsText = useMemo(() => JSON.stringify(form.runtime_params, null, 2), [form.runtime_params]);
  const currentDraft = useMemo(
    () => selectedDraft ?? (drafts.data ?? []).find((draft) => draft.analyzer_id === form.analyzer_id) ?? null,
    [drafts.data, form.analyzer_id, selectedDraft],
  );
  const routerDefinitionStatus = currentDraft ? 'draft' : formHasDraftChanges ? 'draft' : readiness.data?.router_definition_status ?? 'missing';
  const canPromoteDraft = Boolean(currentDraft && ['routing_tested', 'ready_for_backend', 'executable', 'benchmark_passed'].includes(currentDraft.status));
  const yamlPreview = useQuery({
    queryKey: ['analyzer-draft-yaml-preview', currentDraft?.id],
    queryFn: () => getJson<YamlPreview>(`/api/analyzer-labs/drafts/${currentDraft?.id}/yaml-preview`),
    enabled: Boolean(currentDraft),
  });
  const runtimeDesign = getRuntimeDesign(form.runtime_params);
  const activeReadiness = currentDraft ? readiness.data : undefined;
  const nextStep = getNextStep({ currentDraft, testResult, labRoutingResult, readiness: activeReadiness });
  const workflowSteps = getWorkflowSteps({ currentDraft, testResult, labRoutingResult, readiness: activeReadiness });
  const rulesValidated = Boolean(testResult) || Boolean(currentDraft && currentDraft.status !== 'draft');
  const step3Done = Boolean(labRoutingResult);
  const step3Expanded = !step3Done || expandedCompletedSteps.step3;
  const draftPromoted = Boolean(currentDraft?.promoted_at);
  const promoteIsNext = !draftPromoted && (nextStep.title === 'Next step: save to custom analyzers' || nextStep.title === 'Ready for promotion review');
  const toggleCompletedStep = (stepId: string) => {
    setExpandedCompletedSteps((current) => ({ ...current, [stepId]: !current[stepId] }));
  };

  return (
    <Stack spacing={3}>
      <PageHeader title="Add Analyzer" subtitle="Create, verify, test, and promote analyzer definitions safely." />

      <WorkspacePanel
        sx={{
          p: 2.5,
          borderColor: rulesValidated && !labRoutingResult ? ui.green : ui.border,
          borderWidth: rulesValidated && !labRoutingResult ? 2 : 1,
          bgcolor: rulesValidated && !labRoutingResult ? '#ecfeff' : 'white',
        }}
      >
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} justifyContent="space-between" alignItems={{ xs: 'flex-start', md: 'center' }}>
          <Box>
            <Chip label="Start here" color="primary" size="small" sx={{ fontWeight: 900, mb: 1 }} />
            <Typography sx={{ fontWeight: 900, fontSize: 22 }}>Analyzer Setup Flow</Typography>
            <Typography sx={{ color: ui.muted }}>
              Start with a DB draft, validate rules, test with lab data, verify readiness, then explicitly promote to custom_analyzers.yaml.
            </Typography>
          </Box>
          <Button
            variant="contained"
            startIcon={<AddRoundedIcon />}
            onClick={() => {
              setForm(motifTemplate);
              setImportName(motifTemplate.library);
              setTestResult(null);
              setLabRoutingResult(null);
              setExecutionTestStatus('not_run');
              setLibraryCheckResult(null);
              setDrawerOpen(true);
            }}
            sx={{ textTransform: 'none', fontWeight: 850 }}
          >
            Add Analyzer
          </Button>
        </Stack>

        <Alert severity={nextStep.severity} sx={{ mt: 2 }}>
          <Typography sx={{ fontWeight: 900 }}>{nextStep.title}</Typography>
          <Typography>{nextStep.body}</Typography>
        </Alert>

        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: 'repeat(5, 1fr)' }, gap: 1.5, mt: 2 }}>
          {workflowSteps.map((item) => (
            <WorkflowCard key={item.step} {...item} />
          ))}
        </Box>
      </WorkspacePanel>

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Stack direction={{ xs: 'column', lg: 'row' }} spacing={2} justifyContent="space-between" alignItems={{ xs: 'flex-start', lg: 'center' }}>
          <Box>
            <Chip label="Step 3" size="small" sx={{ fontWeight: 900, mb: 1 }} />
            <Typography sx={{ fontWeight: 900, fontSize: 22 }}>Test With Lab Data</Typography>
            <Typography sx={{ color: ui.muted }}>
              {step3Done
                ? `Completed with ${labRoutingResult?.recommendation ?? 'result'} at score ${labRoutingResult?.final_score.toFixed(2) ?? 'n/a'}.`
                : 'Pick generated lab behavior and check whether this analyzer would be recommended for that time-series profile.'}
            </Typography>
          </Box>
          {step3Done ? (
            <Button variant="outlined" onClick={() => toggleCompletedStep('step3')} sx={{ textTransform: 'none', fontWeight: 850 }}>
              {step3Expanded ? 'Collapse Step 3' : 'Review Step 3'}
            </Button>
          ) : null}
        </Stack>
        {step3Done && !step3Expanded ? (
          <Alert severity="success" sx={{ mt: 2 }}>
            Step 3 is done. Continue below to Step 4: Verify Analyzer Readiness.
          </Alert>
        ) : null}
        <Collapse in={step3Expanded} timeout="auto" unmountOnExit>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.2} sx={{ mt: 1.5 }}>
            <MiniOutcome title="What Step 3 Proves" body="The router recommends this analyzer for a known generated behavior, such as forecast, outlier, motif, trend, or change point." />
            <MiniOutcome title="What Step 3 Does Not Prove" body="It does not prove the analyzer library is installed or that backend execution code exists." />
          </Stack>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ minWidth: { xs: '100%', lg: 560 }, mt: 2 }}>
              <FormControl fullWidth>
                <InputLabel>Lab Data</InputLabel>
                <Select label="Lab Data" value={labProfile} onChange={(event) => setLabProfile(event.target.value as LabProfileId)}>
                  {labProfileOptions.map((option) => (
                    <MenuItem key={option.id} value={option.id}>{option.label}</MenuItem>
                  ))}
                </Select>
              </FormControl>
              <Button
                variant="contained"
                startIcon={<PlayArrowRoundedIcon />}
                onClick={() => labRoutingMutation.mutate()}
                disabled={labRoutingMutation.isPending || !rulesValidated}
                sx={{ textTransform: 'none', fontWeight: 850, minWidth: 190 }}
              >
                Run on Lab Data
              </Button>
          </Stack>
          {labRoutingMutation.error ? <Alert severity="error" sx={{ mt: 2 }}>{String(labRoutingMutation.error)}</Alert> : null}
          {labRoutingResult ? (
            <Box sx={{ mt: 2 }}>
              <RoutingResultAlert result={labRoutingResult} labResult />
            </Box>
          ) : (
            <Alert severity={rulesValidated ? 'info' : 'warning'} sx={{ mt: 2 }}>
              {rulesValidated
                ? 'Ready for Step 3. Select a lab data pattern, then run it to check whether this draft is recommended for that generated behavior.'
                : 'Before Step 3: save the draft, then open the draft and click Validate Rules. After that, Run on Lab Data becomes available.'}
            </Alert>
          )}
        </Collapse>
      </WorkspacePanel>

      <ReadinessPanel
        readiness={activeReadiness}
        isLoading={readiness.isLoading}
        routerDefinitionStatus={routerDefinitionStatus}
        executionTestStatus={executionTestStatus}
        benchmarkStatus={benchmarkStatus}
        draftStatus={currentDraft?.status}
        executionTestResult={executionTestResult}
        onVerifyLibrary={() => verifyLibraryMutation.mutate()}
        onRunExecutionTest={() => currentDraft && executionTestMutation.mutate(currentDraft.id)}
        verifying={verifyLibraryMutation.isPending}
        executionTesting={executionTestMutation.isPending}
        executionTestDisabled={!currentDraft || !activeReadiness?.executable}
      />

      <WorkspacePanel
        sx={{
          p: 2.5,
          borderColor: promoteIsNext ? ui.green : draftPromoted ? '#2e7d32' : ui.border,
          borderWidth: promoteIsNext || draftPromoted ? 2 : 1,
          bgcolor: promoteIsNext || draftPromoted ? '#f0fdf4' : 'white',
        }}
      >
        <Stack direction={{ xs: 'column', lg: 'row' }} spacing={2} justifyContent="space-between" alignItems={{ xs: 'flex-start', lg: 'center' }}>
          <Box>
            <Typography sx={{ fontWeight: 900, fontSize: 20 }}>Current Analyzer</Typography>
            <Typography sx={{ color: ui.muted }}>
              {currentDraft ? currentDraft.analyzer_id : 'No draft selected'}
            </Typography>
          </Box>
          <StatusChip status={draftPromoted ? 'promoted' : currentDraft?.status ?? 'not_run'} />
        </Stack>
        {promoteIsNext ? (
          <Alert severity="success" sx={{ mt: 2 }}>
            <Typography sx={{ fontWeight: 900 }}>Next action: Save to custom_analyzers.yaml</Typography>
            <Typography>Step 4 is complete for this recommendation-only analyzer. This button promotes the draft from Postgres into the custom analyzer YAML.</Typography>
          </Alert>
        ) : null}
        {draftPromoted ? (
          <Box sx={{ mt: 2, border: `1px solid ${ui.green}`, borderRadius: 2, p: 2, bgcolor: '#ffffff' }}>
            <Typography sx={{ fontWeight: 900, fontSize: 18 }}>Analyzer added</Typography>
            <Typography sx={{ mt: 0.6 }}>
              {currentDraft?.analyzer_id} is now available as a custom recommendation-only analyzer.
            </Typography>
            <Typography sx={{ color: ui.muted, mt: 0.6, fontSize: 14 }}>
              It can be recommended by routing. It cannot execute or create findings until backend runtime support is added.
            </Typography>
          </Box>
        ) : null}
        <Divider sx={{ my: 2 }} />
        {!draftPromoted ? (
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} justifyContent="space-between" alignItems={{ xs: 'flex-start', md: 'center' }}>
            <Box>
              <Typography sx={{ fontWeight: 850 }}>Promote selected draft</Typography>
              <Typography sx={{ color: ui.muted, fontSize: 14 }}>
                {currentDraft
                  ? canPromoteDraft
                    ? `${currentDraft.analyzer_id} is selected. This writes to config/custom_analyzers.yaml.`
                    : `${currentDraft.analyzer_id} needs a passing routing test before promotion.`
                  : 'Save or select a draft before promoting.'}
              </Typography>
            </Box>
            <Button
              variant={promoteIsNext ? 'contained' : 'outlined'}
              startIcon={<FileUploadRoundedIcon />}
              disabled={!canPromoteDraft || promoteDraftMutation.isPending}
              onClick={() => currentDraft && promoteDraftMutation.mutate(currentDraft.id)}
              sx={{ textTransform: 'none', fontWeight: 850 }}
            >
              Save to custom_analyzers.yaml
            </Button>
          </Stack>
        ) : (
          <Alert severity="info">To remove this analyzer, use Remove Custom under Promoted Custom Analyzers.</Alert>
        )}
        <Button
          variant="text"
          onClick={() => toggleCompletedStep('advancedLifecycle')}
          sx={{ mt: 2, px: 0, textTransform: 'none', fontWeight: 850 }}
        >
          {expandedCompletedSteps.advancedLifecycle ? 'Hide advanced saved state' : 'Advanced: view saved state'}
        </Button>
        <Collapse in={Boolean(expandedCompletedSteps.advancedLifecycle)} timeout="auto" unmountOnExit>
          <Box sx={{ mt: 1.5, border: `1px solid ${ui.border}`, borderRadius: 2, p: 2, bgcolor: 'white' }}>
            <Typography sx={{ fontWeight: 900, mb: 0.5 }}>Saved State Details</Typography>
            <Typography sx={{ color: ui.muted, fontSize: 14, mb: 1.5 }}>
              These are system states for debugging. They do not decide what you should click next.
            </Typography>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              {['draft', 'routing_tested', 'ready_for_backend', 'executable', 'benchmark_passed'].map((status) => (
                <StatusChip key={status} status={currentDraft?.status === status ? status : `waiting_${status}`} />
              ))}
            </Stack>
            {currentDraft ? (
              <Box sx={{ mt: 2 }}>
                <Typography sx={{ fontWeight: 850, mb: 1 }}>YAML preview</Typography>
                <TextField
                  fullWidth
                  multiline
                  minRows={8}
                  value={yamlPreview.data?.yaml_text ?? (yamlPreview.isLoading ? 'Loading YAML preview...' : '')}
                  InputProps={{ readOnly: true }}
                  helperText="Review this before promotion. The promote button writes this analyzer definition to config/custom_analyzers.yaml."
                />
              </Box>
            ) : null}
          </Box>
        </Collapse>
        {promoteDraftMutation.error ? <Alert severity="error" sx={{ mt: 2 }}>{String(promoteDraftMutation.error)}</Alert> : null}
      </WorkspacePanel>

      <WorkspacePanel sx={{ p: 0, overflow: 'hidden' }}>
        <Box sx={{ p: 2.5, pb: 1 }}>
          <Typography sx={{ fontWeight: 900, fontSize: 20 }}>Active Drafts</Typography>
          <Typography sx={{ color: ui.muted }}>Drafts still being edited, tested, or promoted. Promoted analyzers move to the custom list below.</Typography>
          <Alert severity={currentDraft ? 'success' : 'info'} sx={{ mt: 1.5 }}>
            <Typography sx={{ fontWeight: 900 }}>
              {currentDraft && !draftPromoted ? `Selected draft: ${currentDraft.analyzer_id}` : 'Current next action: create or select an active draft'}
            </Typography>
            <Typography>
              {currentDraft && !draftPromoted
                ? 'Now go to Step 3, choose lab data, and click Run on Lab Data.'
                : 'Click Add Analyzer to create a new draft, or select an unpromoted draft from this table.'}
            </Typography>
          </Alert>
        </Box>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Analyzer ID</TableCell>
              <TableCell>Display Name</TableCell>
              <TableCell>Library</TableCell>
              <TableCell>Runtime Mapping</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Last Updated</TableCell>
              <TableCell align="right">Action</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {activeDrafts.map((draft) => (
              <TableRow
                key={draft.id}
                hover
                selected={currentDraft?.id === draft.id}
                onClick={() => {
                  setSelectedDraft(draft);
                  setForm(draft.config);
                  setImportName(draft.config.library.replace(/-/g, '_'));
                  setLabRoutingResult(null);
                }}
                sx={{
                  cursor: 'pointer',
                  bgcolor: currentDraft?.id === draft.id ? '#ecfeff' : 'inherit',
                  outline: currentDraft?.id === draft.id ? `2px solid ${ui.green}` : 'none',
                  outlineOffset: -2,
                  '&:hover': { bgcolor: currentDraft?.id === draft.id ? '#dcfce7' : '#f8fafc' },
                }}
              >
                <TableCell sx={{ fontWeight: 800 }}>{draft.analyzer_id}</TableCell>
                <TableCell>{draft.display_name}</TableCell>
                <TableCell>{draft.config.library}</TableCell>
                <TableCell>{draft.config.runtime_mapping}</TableCell>
                <TableCell><StatusChip status={draft.status} /></TableCell>
                <TableCell>{new Date(draft.updated_at).toLocaleString()}</TableCell>
                <TableCell align="right">
                  <Button
                    size="small"
                    color="error"
                    startIcon={<DeleteOutlineRoundedIcon />}
                    disabled={deleteDraftMutation.isPending}
                    onClick={(event) => {
                      event.stopPropagation();
                      deleteDraftMutation.mutate(draft.id);
                    }}
                    sx={{ textTransform: 'none', fontWeight: 800 }}
                  >
                    Remove
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {activeDrafts.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} sx={{ color: ui.muted }}>No active drafts. Promoted custom analyzers are listed below.</TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
        {deleteDraftMutation.error ? <Alert severity="error" sx={{ m: 2 }}>{String(deleteDraftMutation.error)}</Alert> : null}
      </WorkspacePanel>

      <WorkspacePanel sx={{ p: 0, overflow: 'hidden' }}>
        <Box sx={{ p: 2.5, pb: 1 }}>
          <Stack direction="row" spacing={1} alignItems="center">
            <ArrowForwardRoundedIcon sx={{ color: ui.muted }} />
            <Typography sx={{ fontWeight: 900, fontSize: 20 }}>Promoted Custom Analyzers</Typography>
          </Stack>
          <Typography sx={{ color: ui.muted }}>
            Only analyzers you promoted to custom_analyzers.yaml are shown here. Built-in analyzers are hidden on this page.
          </Typography>
        </Box>
        {analyzers.error ? <Alert severity="error" sx={{ m: 2 }}>{String(analyzers.error)}</Alert> : null}
        {deleteCustomAnalyzerMutation.error ? <Alert severity="error" sx={{ mx: 2, mb: 2 }}>{String(deleteCustomAnalyzerMutation.error)}</Alert> : null}
        {deleteCustomAnalyzerMutation.data ? (
          <Alert severity="success" sx={{ mx: 2, mb: 2 }}>
            Removed {deleteCustomAnalyzerMutation.data.analyzer_id} from custom_analyzers.yaml.
          </Alert>
        ) : null}
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Analyzer ID</TableCell>
              <TableCell>Display Name</TableCell>
              <TableCell>Library</TableCell>
              <TableCell>Runtime Mapping</TableCell>
              <TableCell>Status</TableCell>
              <TableCell align="right">Action</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {customAnalyzers.map((item) => (
              <TableRow key={`${item.source}-${item.analyzer_id}`} hover>
                <TableCell sx={{ fontWeight: 800 }}>{item.analyzer_id}</TableCell>
                <TableCell>{item.display_name}</TableCell>
                <TableCell>{item.library}</TableCell>
                <TableCell>{item.runtime_mapping}</TableCell>
                <TableCell>
                  <Stack direction="row" spacing={1}>
                    <Chip size="small" label={item.routable ? 'Routable' : 'Not routable'} color={item.routable ? 'success' : 'default'} />
                    <Chip size="small" label={item.executable ? 'Executable' : 'Config only'} color={item.executable ? 'primary' : 'warning'} />
                  </Stack>
                </TableCell>
                <TableCell align="right">
                  <Button
                    size="small"
                    color="error"
                    startIcon={<DeleteOutlineRoundedIcon />}
                    disabled={deleteCustomAnalyzerMutation.isPending}
                    onClick={() => deleteCustomAnalyzerMutation.mutate(item.analyzer_id)}
                    sx={{ textTransform: 'none', fontWeight: 800 }}
                  >
                    Remove Custom
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {customAnalyzers.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} sx={{ color: ui.muted }}>No custom analyzers promoted yet.</TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </WorkspacePanel>

      <Drawer anchor="right" open={drawerOpen} onClose={() => setDrawerOpen(false)} PaperProps={{ sx: { width: 760, maxWidth: '100vw' } }}>
        <Stack spacing={2.4} sx={{ p: 3 }}>
          <Box>
            <Typography sx={{ fontWeight: 900, fontSize: 22 }}>Add Analyzer</Typography>
            <Typography sx={{ color: ui.muted }}>Start with the STUMPY-like motif template, then tune routing and runtime settings.</Typography>
          </Box>
          <Divider />

          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
            <TextField fullWidth label="Analyzer ID" value={form.analyzer_id} onChange={(event) => setForm({ ...form, analyzer_id: event.target.value })} />
            <TextField fullWidth label="Display Name" value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} />
          </Stack>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
            <TextField fullWidth label="Template Type" value={form.template_type} onChange={(event) => setForm({ ...form, template_type: event.target.value })} />
            <TextField
              fullWidth
              label="Library"
              value={form.library}
              onChange={(event) => {
                const libraryValue = event.target.value.trim().toLowerCase();
                setForm({ ...form, library: libraryValue });
                setImportName(libraryValue.replace(/-/g, '_'));
                setLibraryCheckResult(null);
              }}
            />
            <TextField fullWidth label="Python Import Name" value={importName} onChange={(event) => setImportName(event.target.value.trim().toLowerCase())} />
          </Stack>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
            <FormControl fullWidth>
              <InputLabel>Runtime Mapping</InputLabel>
              <Select
                label="Runtime Mapping"
                value={form.runtime_mapping}
                onChange={(event) => setForm({ ...form, runtime_mapping: event.target.value })}
              >
                {(runtimeMappings.data ?? [{ id: 'not_implemented', label: 'Not Implemented', executable: false, description: 'Config-only analyzer.' }]).map((mapping) => (
                  <MenuItem key={mapping.id} value={mapping.id}>
                    {mapping.id} {mapping.executable ? '(executable)' : '(config only)'}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControlLabel control={<Switch checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} />} label="Enabled" />
          </Stack>

          <Typography sx={{ fontWeight: 900 }}>Runtime Design</Typography>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
            <FormControl fullWidth>
              <InputLabel>Runtime Type</InputLabel>
              <Select
                label="Runtime Type"
                value={runtimeDesign.type}
                onChange={(event) =>
                  setForm({
                    ...form,
                    runtime_params: setRuntimeDesign(form.runtime_params, { ...runtimeDesign, type: event.target.value as RuntimeDesign['type'] }),
                  })
                }
              >
                {runtimeTypeOptions.map((runtimeType) => (
                  <MenuItem key={runtimeType} value={runtimeType}>{runtimeType.replace(/_/g, ' ')}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              fullWidth
              label="Health Check URL"
              disabled={runtimeDesign.type !== 'external_http'}
              value={runtimeDesign.health_check_url ?? ''}
              onChange={(event) =>
                setForm({
                  ...form,
                  runtime_params: setRuntimeDesign(form.runtime_params, { ...runtimeDesign, health_check_url: event.target.value }),
                })
              }
            />
            <TextField
              fullWidth
              label="Analyze URL"
              disabled={runtimeDesign.type !== 'external_http'}
              value={runtimeDesign.analyze_url ?? ''}
              onChange={(event) =>
                setForm({
                  ...form,
                  runtime_params: setRuntimeDesign(form.runtime_params, { ...runtimeDesign, analyze_url: event.target.value }),
                })
              }
            />
          </Stack>
          <Alert severity="info">
            Use internal_python when Ops Signals has backend code. Use external_http to design a future service-backed analyzer. Use not_implemented for recommendation-only drafts.
          </Alert>

          <FormControl fullWidth>
            <InputLabel>Supported Profiles</InputLabel>
            <Select
              multiple
              label="Supported Profiles"
              value={form.supported_profiles}
              renderValue={(selected) => (
                <Stack direction="row" gap={0.5} flexWrap="wrap">
                  {selected.map((value) => (
                    <Chip
                      key={value}
                      size="small"
                      label={value}
                      deleteIcon={<CancelRoundedIcon onMouseDown={(event) => event.stopPropagation()} />}
                      onDelete={(event) => {
                        event.stopPropagation();
                        setForm({ ...form, supported_profiles: form.supported_profiles.filter((profile) => profile !== value) });
                      }}
                    />
                  ))}
                </Stack>
              )}
              onChange={(event) => setForm({ ...form, supported_profiles: typeof event.target.value === 'string' ? event.target.value.split(',') : event.target.value })}
            >
              {profileOptions.map((profile) => <MenuItem key={profile} value={profile}>{profile}</MenuItem>)}
            </Select>
          </FormControl>

          <Typography sx={{ fontWeight: 900 }}>Eligibility Rules</Typography>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
            <TextField type="number" label="Minimum Samples" value={form.min_samples} onChange={(event) => setForm({ ...form, min_samples: Number(event.target.value) })} />
            <FormControlLabel control={<Switch checked={form.requires_regular_sampling} onChange={(event) => setForm({ ...form, requires_regular_sampling: event.target.checked })} />} label="Requires Regular Sampling" />
            <FormControlLabel control={<Switch checked={form.requires_numeric} onChange={(event) => setForm({ ...form, requires_numeric: event.target.checked })} />} label="Requires Numeric Values" />
          </Stack>

          <Typography sx={{ fontWeight: 900 }}>Scoring Rules</Typography>
          <Stack spacing={1}>
            {form.scoring_rules.map((rule, index) => (
              <Stack key={index} direction={{ xs: 'column', md: 'row' }} spacing={1}>
                <FormControl fullWidth>
                  <InputLabel>Profile Metric</InputLabel>
                  <Select label="Profile Metric" value={rule.metric} onChange={(event) => setForm({ ...form, scoring_rules: updateRule(form.scoring_rules, index, { metric: event.target.value }) })}>
                    {metricOptions.map((metric) => <MenuItem key={metric} value={metric}>{metric}</MenuItem>)}
                  </Select>
                </FormControl>
                <FormControl sx={{ minWidth: 110 }}>
                  <InputLabel>Operator</InputLabel>
                  <Select label="Operator" value={rule.operator} onChange={(event) => setForm({ ...form, scoring_rules: updateRule(form.scoring_rules, index, { operator: event.target.value as RuleOperator }) })}>
                    {['gte', 'gt', 'lte', 'lt', 'equals'].map((op) => <MenuItem key={op} value={op}>{op}</MenuItem>)}
                  </Select>
                </FormControl>
                <TextField label="Threshold" value={String(rule.threshold)} onChange={(event) => setForm({ ...form, scoring_rules: updateRule(form.scoring_rules, index, { threshold: event.target.value === 'true' ? true : event.target.value === 'false' ? false : Number(event.target.value) }) })} />
                <TextField label="Score Boost" type="number" value={rule.add} onChange={(event) => setForm({ ...form, scoring_rules: updateRule(form.scoring_rules, index, { add: Number(event.target.value) }) })} />
              </Stack>
            ))}
          </Stack>

          <Typography sx={{ fontWeight: 900 }}>Runtime Parameters</Typography>
          <TextField
            multiline
            minRows={4}
            value={runtimeParamsText}
            onChange={(event) => {
              try {
                setForm({ ...form, runtime_params: JSON.parse(event.target.value) as Record<string, unknown> });
              } catch {
                return;
              }
            }}
          />

          <DrawerProgress
            hasDraft={Boolean(currentDraft)}
            hasValidated={Boolean(testResult) || Boolean(currentDraft && currentDraft.status !== 'draft')}
            libraryCheckResult={libraryCheckResult}
            nextMessage={getDrawerNextMessage({
              currentDraft,
              testResult,
              libraryCheckResult,
              verifying: verifyLibraryMutation.isPending,
              saving: saveDraftMutation.isPending,
              validating: testMutation.isPending,
            })}
          />

          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Button variant="contained" startIcon={<SaveRoundedIcon />} onClick={() => saveDraftMutation.mutate(form)} disabled={saveDraftMutation.isPending}>
              {saveDraftMutation.isPending ? 'Saving...' : currentDraft ? 'Save Draft Again' : 'Save Draft'}
            </Button>
            <Button variant="outlined" startIcon={<PlayArrowRoundedIcon />} onClick={() => testMutation.mutate(form)} disabled={testMutation.isPending}>
              {testMutation.isPending ? 'Validating...' : testResult ? 'Validate Again' : 'Validate Rules'}
            </Button>
            <Button
              variant="outlined"
              startIcon={<VerifiedRoundedIcon />}
              onClick={() => {
                setLibraryCheckResult(null);
                verifyLibraryMutation.mutate();
              }}
              disabled={verifyLibraryMutation.isPending || !form.library}
            >
              {verifyLibraryMutation.isPending ? 'Checking...' : libraryCheckResult ? 'Verify Again' : 'Verify Library'}
            </Button>
          </Stack>

          {testMutation.error ? <Alert severity="error">{String(testMutation.error)}</Alert> : null}
          {saveDraftMutation.error ? <Alert severity="error">{String(saveDraftMutation.error)}</Alert> : null}
          {verifyLibraryMutation.error ? <Alert severity="error">{String(verifyLibraryMutation.error)}</Alert> : null}
          {libraryCheckResult ? (
            <Alert severity={libraryCheckResult.installed ? 'success' : 'warning'}>
              {libraryCheckResult.installed
                ? `${libraryCheckResult.import_name} verified${libraryCheckResult.version ? ` (${libraryCheckResult.version})` : ''}.`
                : `${libraryCheckResult.import_name} is not importable in the backend Python environment. ${libraryCheckResult.suggested_install ?? ''}`}
            </Alert>
          ) : null}
          {saveDraftMutation.data ? <Alert severity="success">Draft saved to Postgres. Promote it when you are ready to update custom_analyzers.yaml.</Alert> : null}
          {testResult ? (
            <RoutingResultAlert result={testResult} />
          ) : null}
        </Stack>
      </Drawer>
    </Stack>
  );
}

function getRuntimeDesign(params: Record<string, unknown>): RuntimeDesign {
  const raw = params.external_runtime;
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return { type: 'not_implemented' };
  }
  const candidate = raw as Record<string, unknown>;
  const type = runtimeTypeOptions.includes(candidate.type as RuntimeDesign['type'])
    ? candidate.type as RuntimeDesign['type']
    : 'not_implemented';
  return {
    type,
    health_check_url: typeof candidate.health_check_url === 'string' ? candidate.health_check_url : '',
    analyze_url: typeof candidate.analyze_url === 'string' ? candidate.analyze_url : '',
  };
}

function setRuntimeDesign(params: Record<string, unknown>, design: RuntimeDesign): Record<string, unknown> {
  return {
    ...params,
    external_runtime: {
      type: design.type,
      ...(design.health_check_url ? { health_check_url: design.health_check_url } : {}),
      ...(design.analyze_url ? { analyze_url: design.analyze_url } : {}),
    },
  };
}

function RoutingResultAlert({ result, labResult = false }: { result: TestRouteResult | LabRoutingResult; labResult?: boolean }) {
  const tuneHint =
    result.recommendation === 'RECOMMENDED'
      ? 'Next: save the draft, then verify readiness before promotion.'
      : result.final_score >= 0.45
        ? 'Tune next: add stronger scoring rules or align supported profiles with the target behavior.'
        : 'Tune next: check supported profiles, minimum samples, and scoring thresholds.';
  return (
    <Alert severity={result.recommendation === 'RECOMMENDED' ? 'success' : 'info'}>
      <Stack spacing={0.7}>
        <Typography sx={{ fontWeight: 850 }}>
          Recommendation: {result.recommendation} · Score {result.final_score.toFixed(2)} · Runtime {result.runtime_status}
        </Typography>
        {labResult ? (
          <>
            <Typography>Lab data: {(result as LabRoutingResult).lab_profile_label}</Typography>
            <Typography>Detected profiles: {(result as LabRoutingResult).detected_profiles.join(', ') || 'none'}</Typography>
          </>
        ) : (
          <Typography>This validates the router rules with a synthetic sample profile, not real time-series data.</Typography>
        )}
        <Typography>
          {result.reasons[0] ?? 'Routing test completed against a sample time-series profile.'}
        </Typography>
        {result.runtime_status === 'config_only' ? (
          <Typography>This analyzer can be recommended, but cannot execute until backend runtime mapping is added.</Typography>
        ) : null}
        <Typography>{tuneHint}</Typography>
      </Stack>
    </Alert>
  );
}

function DrawerProgress({
  hasDraft,
  hasValidated,
  libraryCheckResult,
  nextMessage,
}: {
  hasDraft: boolean;
  hasValidated: boolean;
  libraryCheckResult: LibraryCheckResult | null;
  nextMessage: string;
}) {
  return (
    <Box sx={{ border: `1px solid ${ui.border}`, borderRadius: 2, p: 1.5, bgcolor: '#f8fafc' }}>
      <Typography sx={{ fontWeight: 900, mb: 1 }}>This popup progress</Typography>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        <StatusChip status={hasDraft ? 'done_save_draft' : 'waiting_save_draft'} />
        <StatusChip status={hasValidated ? 'done_validate_rules' : 'waiting_validate_rules'} />
        <StatusChip
          status={
            libraryCheckResult
              ? libraryCheckResult.installed
                ? 'done_verify_library'
                : 'missing_verify_library'
              : 'waiting_verify_library'
          }
        />
      </Stack>
      <Alert severity={hasDraft && hasValidated ? 'success' : 'info'} sx={{ mt: 1.5 }}>
        {nextMessage}
      </Alert>
    </Box>
  );
}

function getDrawerNextMessage({
  currentDraft,
  testResult,
  libraryCheckResult,
  verifying,
  saving,
  validating,
}: {
  currentDraft: AnalyzerDraft | null;
  testResult: TestRouteResult | null;
  libraryCheckResult: LibraryCheckResult | null;
  verifying: boolean;
  saving: boolean;
  validating: boolean;
}) {
  if (saving) return 'Saving the draft to Postgres...';
  if (validating) return 'Validating router rules against a synthetic profile...';
  if (verifying) return 'Checking whether the backend Python environment can import the library...';
  if (!currentDraft) return 'Next inside this popup: click Save Draft.';
  if (!testResult && currentDraft.status === 'draft') return 'Saved. Next inside this popup: click Validate Rules.';
  if (!libraryCheckResult) return 'Rules validated. Optional next inside this popup: click Verify Library, then close this popup and run Step 3 on the parent page.';
  if (!libraryCheckResult.installed) return 'Library check completed: missing. You can still keep this as config-only, or install the library before execution support.';
  return 'Draft saved, rules validated, and library verified. Close this popup and continue with Step 3: Test With Lab Data.';
}

function getNextStep({
  currentDraft,
  testResult,
  labRoutingResult,
  readiness,
}: {
  currentDraft: AnalyzerDraft | null;
  testResult: TestRouteResult | null;
  labRoutingResult: LabRoutingResult | null;
  readiness?: AnalyzerReadiness;
}): { title: string; body: string; severity: 'info' | 'success' | 'warning' } {
  if (!currentDraft) {
    return {
      title: 'Next step: save a draft',
      body: 'Click Add Analyzer, fill the definition, then Save Draft. This stores the analyzer in Postgres only and does not change YAML.',
      severity: 'info',
    };
  }
  if (currentDraft.promoted_at) {
    return {
      title: 'Analyzer saved to custom config',
      body: 'This draft has already been promoted to custom_analyzers.yaml. Select another draft or add backend runtime support if you want it to execute.',
      severity: 'success',
    };
  }
  if (!testResult && currentDraft.status === 'draft') {
    return {
      title: 'Next step: validate rules',
      body: 'Open the draft and click Validate Rules. This confirms the router can understand the definition using a synthetic sample profile.',
      severity: 'info',
    };
  }
  if (!labRoutingResult) {
    return {
      title: 'Next step: test with lab data',
      body: 'Choose generated lab behavior, such as Prophet forecast or PyOD outlier, then run it to see if the analyzer is recommended for that profile.',
      severity: 'info',
    };
  }
  if (labRoutingResult.recommendation === 'NOT_RECOMMENDED' || labRoutingResult.recommendation === 'REJECTED') {
    return {
      title: 'Needs tuning before promotion',
      body: 'The lab-data test did not recommend this analyzer. Adjust supported profiles, scoring rules, or minimum samples, then test again.',
      severity: 'warning',
    };
  }
  if (readiness?.library_importable && readiness.runtime_mapping_status === 'not_implemented') {
    return {
      title: 'Next step: save to custom analyzers',
      body: 'This is recommendation-only and the library check passed. Skip execution test for now and click Save to custom_analyzers.yaml when you are ready.',
      severity: 'success',
    };
  }
  if (!readiness?.library_importable) {
    return {
      title: 'Next step: verify readiness',
      body: 'Click Verify Library. This confirms whether the backend Python environment can import the package.',
      severity: 'warning',
    };
  }
  if (!readiness.backend_implementation_exists || !readiness.config_exists) {
    return {
      title: 'Backend implementation still missing',
      body: 'This analyzer can be recommended, but it cannot execute until backend code and default config are added. Keep it recommendation-only or add backend support next.',
      severity: 'warning',
    };
  }
  return {
    title: 'Ready for promotion review',
    body: 'Review the YAML preview, then promote only when you want to write this analyzer definition to custom_analyzers.yaml.',
    severity: 'success',
  };
}

function getWorkflowSteps({
  currentDraft,
  testResult,
  labRoutingResult,
  readiness,
}: {
  currentDraft: AnalyzerDraft | null;
  testResult: TestRouteResult | null;
  labRoutingResult: LabRoutingResult | null;
  readiness?: AnalyzerReadiness;
}): Array<{ step: string; title: string; body: string; state: WorkflowState }> {
  const draftDone = Boolean(currentDraft);
  const rulesDone = Boolean(testResult) || Boolean(currentDraft && currentDraft.status !== 'draft');
  const labDone = Boolean(labRoutingResult);
  const labBlocked = Boolean(labRoutingResult && ['NOT_RECOMMENDED', 'REJECTED'].includes(labRoutingResult.recommendation));
  const recommendationOnlyReady = Boolean(labDone && readiness?.library_importable && readiness.runtime_mapping_status === 'not_implemented');
  const executionReady = Boolean(labDone && readiness?.library_importable && readiness.backend_implementation_exists && readiness.config_exists);
  const readinessDone = recommendationOnlyReady || executionReady;
  const canPromote = Boolean(currentDraft && ['routing_tested', 'ready_for_backend', 'executable', 'benchmark_passed'].includes(currentDraft.status));
  const promoted = Boolean(currentDraft?.promoted_at);

  return [
    {
      step: '1',
      title: 'Save Draft',
      body: 'Store the analyzer definition in Postgres without changing YAML.',
      state: draftDone ? 'done' : 'current',
    },
    {
      step: '2',
      title: 'Validate Rules',
      body: 'Check that router rules are valid with a synthetic profile.',
      state: rulesDone ? 'done' : draftDone ? 'current' : 'waiting',
    },
    {
      step: '3',
      title: 'Test With Lab Data',
      body: 'Use generated lab behavior to verify recommendation fit.',
      state: labBlocked ? 'blocked' : labDone ? 'done' : rulesDone ? 'current' : 'waiting',
    },
    {
      step: '4',
      title: 'Verify Readiness',
      body: 'Check library, config, runtime mapping, and backend code.',
      state: readinessDone ? 'done' : labDone ? 'current' : 'waiting',
    },
    {
      step: '5',
      title: 'Promote Config',
      body: 'Review YAML and explicitly write custom_analyzers.yaml.',
      state: promoted ? 'done' : canPromote && readinessDone && !labBlocked ? 'current' : 'waiting',
    },
  ];
}

function MiniOutcome({ title, body }: { title: string; body: string }) {
  return (
    <Box sx={{ border: `1px solid ${ui.border}`, borderRadius: 2, p: 1.4, bgcolor: '#f8fafc', flex: 1 }}>
      <Typography sx={{ fontWeight: 900, fontSize: 13.5 }}>{title}</Typography>
      <Typography sx={{ color: ui.muted, fontSize: 13, lineHeight: 1.45, mt: 0.4 }}>{body}</Typography>
    </Box>
  );
}

function ReadinessPanel({
  readiness,
  isLoading,
  routerDefinitionStatus,
  executionTestStatus,
  benchmarkStatus,
  draftStatus,
  executionTestResult,
  onVerifyLibrary,
  onRunExecutionTest,
  verifying,
  executionTesting,
  executionTestDisabled,
}: {
  readiness?: AnalyzerReadiness;
  isLoading: boolean;
  routerDefinitionStatus: AnalyzerReadiness['router_definition_status'];
  executionTestStatus: RunStatus;
  benchmarkStatus: RunStatus;
  draftStatus?: DraftStatus;
  executionTestResult: ExecutionTestResult | null;
  onVerifyLibrary: () => void;
  onRunExecutionTest: () => void;
  verifying: boolean;
  executionTesting: boolean;
  executionTestDisabled: boolean;
}) {
  const readinessNext = getReadinessNextAction(readiness, executionTestResult);
  const [showDetails, setShowDetails] = useState(false);
  useEffect(() => {
    if (readinessNext.action === 'promote') {
      setShowDetails(false);
    }
  }, [readinessNext.action]);
  const items = [
    {
      label: 'Draft status',
      status: draftStatus ?? 'not_run',
      detail: draftStatus ? 'Current analyzer draft is tracked in Postgres.' : 'Save a draft before promotion or execution testing.',
    },
    {
      label: 'Library installed',
      status: readiness?.library_status ?? 'unknown',
      detail: readiness?.library_error ?? readiness?.import_name ?? 'Choose a library to verify.',
    },
    {
      label: 'Router definition',
      status: routerDefinitionStatus,
      detail:
        routerDefinitionStatus === 'saved'
          ? `Saved in ${readiness?.router_definition_source ?? 'registry'} definitions.`
          : routerDefinitionStatus === 'draft'
            ? 'Current form has unsaved router definition changes.'
            : 'No saved router definition found yet.',
    },
    {
      label: 'Runtime mapping',
      status: readiness?.runtime_mapping_status ?? 'not_implemented',
      detail: readiness?.runtime_mapping ? `Maps to ${readiness.runtime_mapping}.` : 'Runtime mapping has not been selected.',
    },
    {
      label: 'Backend analyzer code',
      status: readiness?.backend_implementation_exists ? 'found' : 'missing',
      detail: readiness?.backend_implementation_exists ? 'Executable analyzer implementation is available.' : 'Backend analyzer implementation is not wired yet.',
    },
    {
      label: 'Default config',
      status: readiness?.config_exists ? 'found' : 'missing',
      detail: readiness?.config_exists ? 'Default exists in config/analyzers.yaml.' : 'No default entry found in config/analyzers.yaml.',
    },
    {
      label: 'Execution test',
      status: executionTestResult?.status ?? executionTestStatus,
      detail: executionTestResult
        ? `${executionTestResult.reason}${executionTestResult.available ? ` Samples ${executionTestResult.sample_count}, signals ${executionTestResult.signal_count}, findings ${executionTestResult.finding_count}.` : ''}`
        : executionTestStatus === 'not_run'
          ? 'Run Execution Test after the analyzer has executable backend code.'
          : 'Latest execution test updated this status.',
    },
    {
      label: 'Benchmark',
      status: benchmarkStatus,
      detail: 'Benchmark runner is not connected on this page yet.',
    },
  ];

  return (
    <WorkspacePanel sx={{ p: 2.5 }}>
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} justifyContent="space-between" alignItems={{ xs: 'flex-start', md: 'center' }}>
        <Box>
          <Chip label="Step 4" size="small" sx={{ fontWeight: 900, mb: 1 }} />
          <Stack direction="row" spacing={1} alignItems="center">
            <FactCheckRoundedIcon sx={{ color: ui.green }} />
            <Typography sx={{ fontWeight: 900, fontSize: 22 }}>Verify Analyzer Readiness</Typography>
          </Stack>
          <Typography sx={{ color: ui.muted }}>
            Checks whether this draft is only recommendation-ready or also execution-ready in the backend.
          </Typography>
        </Box>
        {readinessNext.action === 'promote' ? (
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems={{ xs: 'flex-start', sm: 'center' }}>
            <Chip color="success" icon={<VerifiedRoundedIcon />} label="Library verified" sx={{ fontWeight: 850 }} />
            <Chip label="Execution test skipped for config-only" sx={{ fontWeight: 850 }} />
          </Stack>
        ) : (
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
            <Button
              variant={readinessNext.action === 'verify_library' ? 'contained' : 'outlined'}
              startIcon={<VerifiedRoundedIcon />}
              onClick={onVerifyLibrary}
              disabled={verifying || isLoading}
              sx={{ textTransform: 'none', fontWeight: 850 }}
            >
              {verifying ? 'Checking...' : 'Verify Library'}
            </Button>
            <Button
              variant={readinessNext.action === 'run_execution_test' ? 'contained' : 'outlined'}
              startIcon={<PlayArrowRoundedIcon />}
              onClick={onRunExecutionTest}
              disabled={executionTesting || executionTestDisabled}
              sx={{ textTransform: 'none', fontWeight: 850 }}
            >
              {executionTesting ? 'Running...' : 'Run Execution Test'}
            </Button>
          </Stack>
        )}
      </Stack>
      <Alert severity={readinessNext.severity} sx={{ mt: 2 }}>
        <Typography sx={{ fontWeight: 900 }}>{readinessNext.title}</Typography>
        <Typography>{readinessNext.body}</Typography>
      </Alert>
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.2} sx={{ mt: 1.5 }}>
        <MiniOutcome title="Recommendation-Ready" body="Router definition exists and lab-data routing works. The analyzer can appear in recommendations." />
        <MiniOutcome title="Execution-Ready" body="Library, default config, runtime mapping, and backend analyzer code are all available. Then it can emit signals." />
      </Stack>
      <Button
        variant="text"
        onClick={() => setShowDetails((value) => !value)}
        sx={{ mt: 1.5, px: 0, textTransform: 'none', fontWeight: 850 }}
      >
        {showDetails ? 'Hide readiness checks' : 'Review readiness checks'}
      </Button>
      <Collapse in={showDetails} timeout="auto" unmountOnExit>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(2, 1fr)', xl: 'repeat(4, 1fr)' }, gap: 1.2, mt: 1 }}>
          {items.map((item) => (
            <Card key={item.label} variant="outlined" sx={{ borderRadius: 2 }}>
              <CardContent sx={{ p: 1.7, '&:last-child': { pb: 1.7 } }}>
                <Stack direction="row" spacing={1} justifyContent="space-between" alignItems="flex-start">
                  <Typography sx={{ fontWeight: 850 }}>{item.label}</Typography>
                  <StatusChip status={item.status} />
                </Stack>
                <Typography sx={{ color: ui.muted, fontSize: 13.5, mt: 1, lineHeight: 1.4 }}>{item.detail}</Typography>
              </CardContent>
            </Card>
          ))}
        </Box>
      </Collapse>
    </WorkspacePanel>
  );
}

function getReadinessNextAction(readiness?: AnalyzerReadiness, executionTestResult?: ExecutionTestResult | null): {
  title: string;
  body: string;
  action: 'verify_library' | 'run_execution_test' | 'promote' | 'none';
  severity: 'info' | 'success' | 'warning';
} {
  if (!readiness) {
    return {
      title: 'Waiting for Step 3',
      body: 'Finish Test With Lab Data first. Then this section will tell you whether to verify the library, run execution test, or promote as config-only.',
      action: 'none',
      severity: 'info',
    };
  }
  if (!readiness.library_importable) {
    return {
      title: 'Click next: Verify Library',
      body: 'This checks whether the backend Python environment can import the package. Do this before deciding whether to promote.',
      action: 'verify_library',
      severity: 'warning',
    };
  }
  if (readiness.runtime_mapping_status === 'not_implemented') {
    return {
      title: 'Step 4 complete for recommendation-only',
      body: 'The library is verified, but runtime mapping is config-only. Do not run execution test. Next click: Save to custom_analyzers.yaml in Step 5.',
      action: 'promote',
      severity: 'success',
    };
  }
  if (readiness.executable && executionTestResult?.status !== 'passed') {
    return {
      title: 'Click next: Run Execution Test',
      body: 'This analyzer has backend execution support. Run the execution test before promotion so you know it can emit signals.',
      action: 'run_execution_test',
      severity: 'info',
    };
  }
  return {
    title: 'Step 4 complete',
    body: 'Readiness is verified. Next click: Save to custom_analyzers.yaml in Step 5.',
    action: 'promote',
    severity: 'success',
  };
}

function WorkflowCard({ step, title, body, state }: { step: string; title: string; body: string; state: WorkflowState }) {
  const palette = {
    done: { border: '#2e7d32', bg: '#f0fdf4', chip: 'success' as const, label: 'Done' },
    current: { border: ui.green, bg: '#ecfeff', chip: 'primary' as const, label: 'Current' },
    waiting: { border: ui.border, bg: 'white', chip: 'default' as const, label: 'Waiting' },
    blocked: { border: '#ef6c00', bg: '#fff7ed', chip: 'warning' as const, label: 'Tune' },
  }[state];
  return (
    <Card variant="outlined" sx={{ borderColor: palette.border, bgcolor: palette.bg, borderWidth: state === 'current' ? 2 : 1 }}>
      <CardContent>
        <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between" sx={{ mb: 0.8 }}>
          <Chip label={step} size="small" color={palette.chip} sx={{ fontWeight: 900 }} />
          <Chip label={palette.label} size="small" color={palette.chip} variant={state === 'waiting' ? 'outlined' : 'filled'} sx={{ fontWeight: 800 }} />
        </Stack>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.8 }}>
          <Typography sx={{ fontWeight: 900 }}>{title}</Typography>
        </Stack>
        <Typography sx={{ color: ui.muted, lineHeight: 1.55 }}>{body}</Typography>
      </CardContent>
    </Card>
  );
}

function StatusChip({ status }: { status: string }) {
  const statusLabels: Record<string, string> = {
    done_save_draft: 'Save Draft done',
    done_validate_rules: 'Validate Rules done',
    done_verify_library: 'Verify Library done',
    missing_verify_library: 'Verify Library missing',
    waiting_save_draft: 'Save Draft waiting',
    waiting_validate_rules: 'Validate Rules waiting',
    waiting_verify_library: 'Verify Library waiting',
    routing_tested: 'rules validated',
    promoted: 'saved to custom YAML',
  };
  const normalizedStatus = status.startsWith('waiting_') ? status.replace('waiting_', '') : status;
  const label = statusLabels[status] ?? statusLabels[normalizedStatus] ?? normalizedStatus.replace(/_/g, ' ');
  const color =
    status.startsWith('waiting_')
      ? 'default'
      : ['verified', 'saved', 'executable', 'found', 'passed', 'done_save_draft', 'done_validate_rules', 'done_verify_library', 'promoted'].includes(status)
      ? 'success'
      : ['draft', 'not_run', 'unknown'].includes(status)
        ? 'default'
        : 'warning';
  return <Chip size="small" label={label} color={color} sx={{ textTransform: 'capitalize', fontWeight: 800 }} />;
}

function InfoCard({ title, body }: { title: string; body: string }) {
  return (
    <Card variant="outlined">
      <CardContent>
        <Typography sx={{ fontWeight: 900, mb: 0.7 }}>{title}</Typography>
        <Typography sx={{ color: ui.muted, lineHeight: 1.55 }}>{body}</Typography>
      </CardContent>
    </Card>
  );
}
