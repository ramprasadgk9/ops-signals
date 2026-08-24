import { useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  Drawer,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Paper,
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
import { getJson, postJson } from '../api/client';

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

export function AdminApp() {
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
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default', color: 'text.primary' }}>
      <Box sx={{ borderBottom: 1, borderColor: 'divider', px: 3, py: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 700 }}>Ops Signals Admin</Typography>
          <Typography variant="body2" color="text.secondary">Configure analyzer routing and runtime mappings.</Typography>
        </Box>
        <Button variant="contained" startIcon={<AddRoundedIcon />} onClick={() => { setForm(motifTemplate); setTestResult(null); setDrawerOpen(true); }}>
          Add Analyzer
        </Button>
      </Box>

      <Box sx={{ p: 3 }}>
        {analyzers.error ? <Alert severity="error">{String(analyzers.error)}</Alert> : null}
        <Paper variant="outlined" sx={{ overflow: 'hidden' }}>
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
                  <TableCell>{item.analyzer_id}</TableCell>
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
        </Paper>
      </Box>

      <Drawer anchor="right" open={drawerOpen} onClose={() => setDrawerOpen(false)} PaperProps={{ sx: { width: 720, maxWidth: '100vw' } }}>
        <Stack spacing={2.5} sx={{ p: 3 }}>
          <Box>
            <Typography variant="h6" sx={{ fontWeight: 700 }}>Add Analyzer</Typography>
            <Typography variant="body2" color="text.secondary">Start with the STUMPY-like motif template, then tune routing and runtime settings.</Typography>
          </Box>
          <Divider />

          <Stack direction="row" spacing={2}>
            <TextField fullWidth label="Analyzer ID" value={form.analyzer_id} onChange={(e) => setForm({ ...form, analyzer_id: e.target.value })} />
            <TextField fullWidth label="Display Name" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
          </Stack>
          <Stack direction="row" spacing={2}>
            <TextField fullWidth label="Template Type" value={form.template_type} onChange={(e) => setForm({ ...form, template_type: e.target.value })} />
            <TextField fullWidth label="Library" value={form.library} onChange={(e) => setForm({ ...form, library: e.target.value })} />
          </Stack>
          <Stack direction="row" spacing={2}>
            <TextField fullWidth label="Runtime Mapping" value={form.runtime_mapping} onChange={(e) => setForm({ ...form, runtime_mapping: e.target.value })} />
            <FormControlLabel control={<Switch checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />} label="Enabled" />
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
              onChange={(e) => setForm({ ...form, supported_profiles: typeof e.target.value === 'string' ? e.target.value.split(',') : e.target.value })}
            >
              {profileOptions.map((profile) => <MenuItem key={profile} value={profile}>{profile}</MenuItem>)}
            </Select>
          </FormControl>

          <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>Eligibility Rules</Typography>
          <Stack direction="row" spacing={2}>
            <TextField type="number" label="Minimum Samples" value={form.min_samples} onChange={(e) => setForm({ ...form, min_samples: Number(e.target.value) })} />
            <FormControlLabel control={<Switch checked={form.requires_regular_sampling} onChange={(e) => setForm({ ...form, requires_regular_sampling: e.target.checked })} />} label="Requires Regular Sampling" />
            <FormControlLabel control={<Switch checked={form.requires_numeric} onChange={(e) => setForm({ ...form, requires_numeric: e.target.checked })} />} label="Requires Numeric Values" />
          </Stack>

          <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>Scoring Rules</Typography>
          <Stack spacing={1}>
            {form.scoring_rules.map((rule, index) => (
              <Stack key={index} direction="row" spacing={1}>
                <FormControl fullWidth>
                  <InputLabel>Profile Metric</InputLabel>
                  <Select label="Profile Metric" value={rule.metric} onChange={(e) => setForm({ ...form, scoring_rules: updateRule(form.scoring_rules, index, { metric: e.target.value }) })}>
                    {metricOptions.map((metric) => <MenuItem key={metric} value={metric}>{metric}</MenuItem>)}
                  </Select>
                </FormControl>
                <FormControl sx={{ minWidth: 100 }}>
                  <InputLabel>Operator</InputLabel>
                  <Select label="Operator" value={rule.operator} onChange={(e) => setForm({ ...form, scoring_rules: updateRule(form.scoring_rules, index, { operator: e.target.value as RuleOperator }) })}>
                    {['gte', 'gt', 'lte', 'lt', 'equals'].map((op) => <MenuItem key={op} value={op}>{op}</MenuItem>)}
                  </Select>
                </FormControl>
                <TextField label="Threshold" value={String(rule.threshold)} onChange={(e) => setForm({ ...form, scoring_rules: updateRule(form.scoring_rules, index, { threshold: e.target.value === 'true' ? true : e.target.value === 'false' ? false : Number(e.target.value) }) })} />
                <TextField label="Score Boost" type="number" value={rule.add} onChange={(e) => setForm({ ...form, scoring_rules: updateRule(form.scoring_rules, index, { add: Number(e.target.value) }) })} />
              </Stack>
            ))}
          </Stack>

          <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>Runtime Parameters</Typography>
          <TextField
            multiline
            minRows={4}
            value={runtimeParamsText}
            onChange={(e) => {
              try {
                setForm({ ...form, runtime_params: JSON.parse(e.target.value) as Record<string, unknown> });
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
    </Box>
  );
}
