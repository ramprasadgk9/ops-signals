import { useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
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
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';
import SaveRoundedIcon from '@mui/icons-material/SaveRounded';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getJson, postJson } from '../../api/client';
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

const profileOptions = ['seasonal', 'motif', 'repeating_pattern', 'trend', 'baseline_shift', 'regime_change', 'anomaly', 'outlier', 'spike', 'forecast', 'mixed'];
const metricOptions = ['sample_count', 'regular_sampling', 'seasonality_strength', 'trend_strength', 'shift_index', 'spikiness', 'missing_percentage', 'irregular_sampling_percentage', 'behavior_mix'];

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

  const analyzers = useQuery({
    queryKey: ['admin-analyzers'],
    queryFn: () => getJson<AnalyzerConfig[]>('/api/admin/analyzers'),
  });

  const saveMutation = useMutation({
    mutationFn: (payload: AnalyzerConfig) => postJson<AnalyzerConfig, AnalyzerConfig>('/api/admin/analyzers', payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-analyzers'] });
      setDrawerOpen(false);
    },
  });

  const testMutation = useMutation({
    mutationFn: (payload: AnalyzerConfig) => postJson<AnalyzerConfig, TestRouteResult>('/api/admin/analyzers/test-route', payload),
    onSuccess: setTestResult,
  });

  const runtimeParamsText = useMemo(() => JSON.stringify(form.runtime_params, null, 2), [form.runtime_params]);

  return (
    <Stack spacing={3}>
      <PageHeader title="Add Analyzer" subtitle="Create router definitions, test routing behavior, and save custom analyzer configuration." />

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} justifyContent="space-between" alignItems={{ xs: 'flex-start', md: 'center' }}>
          <Box>
            <Typography sx={{ fontWeight: 900, fontSize: 22 }}>Analyzer Definitions</Typography>
            <Typography sx={{ color: ui.muted }}>
              This page saves routing definitions to custom analyzer config. Executable analyzers still need backend implementation.
            </Typography>
          </Box>
          <Button
            variant="contained"
            startIcon={<AddRoundedIcon />}
            onClick={() => {
              setForm(motifTemplate);
              setTestResult(null);
              setDrawerOpen(true);
            }}
            sx={{ textTransform: 'none', fontWeight: 850 }}
          >
            Add Analyzer
          </Button>
        </Stack>

        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: 'repeat(3, 1fr)' }, gap: 1.5, mt: 2 }}>
          <InfoCard title="1. Routing Definition" body="Defines when an analyzer should be recommended based on detected time-series profiles and scoring rules." />
          <InfoCard title="2. Runtime Mapping" body="Connects a router definition to existing executable analyzer code, such as stumpy, prophet, or pyod_outlier." />
          <InfoCard title="3. Backend Implementation" body="If runtime mapping is not implemented, the analyzer can be recommended but cannot emit signals yet." />
        </Box>
      </WorkspacePanel>

      <WorkspacePanel sx={{ p: 0, overflow: 'hidden' }}>
        {analyzers.error ? <Alert severity="error" sx={{ m: 2 }}>{String(analyzers.error)}</Alert> : null}
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Analyzer ID</TableCell>
              <TableCell>Display Name</TableCell>
              <TableCell>Library</TableCell>
              <TableCell>Runtime Mapping</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Source</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {(analyzers.data ?? []).map((item) => (
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
                <TableCell>{item.source}</TableCell>
              </TableRow>
            ))}
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
            <TextField fullWidth label="Library" value={form.library} onChange={(event) => setForm({ ...form, library: event.target.value })} />
          </Stack>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
            <TextField fullWidth label="Runtime Mapping" value={form.runtime_mapping} onChange={(event) => setForm({ ...form, runtime_mapping: event.target.value })} />
            <FormControlLabel control={<Switch checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} />} label="Enabled" />
          </Stack>

          <FormControl fullWidth>
            <InputLabel>Supported Profiles</InputLabel>
            <Select
              multiple
              label="Supported Profiles"
              value={form.supported_profiles}
              renderValue={(selected) => (
                <Stack direction="row" gap={0.5} flexWrap="wrap">{selected.map((value) => <Chip key={value} size="small" label={value} />)}</Stack>
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

          <Stack direction="row" spacing={1}>
            <Button variant="outlined" startIcon={<PlayArrowRoundedIcon />} onClick={() => testMutation.mutate(form)} disabled={testMutation.isPending}>Test Routing</Button>
            <Button variant="contained" startIcon={<SaveRoundedIcon />} onClick={() => saveMutation.mutate(form)} disabled={saveMutation.isPending}>Save Analyzer</Button>
          </Stack>

          {testMutation.error ? <Alert severity="error">{String(testMutation.error)}</Alert> : null}
          {saveMutation.error ? <Alert severity="error">{String(saveMutation.error)}</Alert> : null}
          {testResult ? (
            <Alert severity={testResult.recommendation === 'RECOMMENDED' ? 'success' : 'info'}>
              Final score {testResult.final_score.toFixed(2)} - Recommendation: {testResult.recommendation} - Runtime: {testResult.runtime_status}
            </Alert>
          ) : null}
        </Stack>
      </Drawer>
    </Stack>
  );
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
