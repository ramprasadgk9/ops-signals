import { useState } from 'react';
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Chip,
  Grid2 as Grid,
  IconButton,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import AddRoundedIcon from '@mui/icons-material/AddRounded';
import DeleteRoundedIcon from '@mui/icons-material/DeleteRounded';
import ScienceRoundedIcon from '@mui/icons-material/ScienceRounded';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { PageHeader, WorkspacePanel } from '../standalone/components';
import { ui } from '../standalone/theme';
import type { BehaviorConditionInput, BehaviorDefinitionDraft } from '../types';

type InputRow = { alias: string; metricName: string; analyzers: string };
type ConditionRow = BehaviorConditionInput;

const OPERATORS = ['equals', 'greater_than', 'less_than', 'contains'];
const SEVERITIES = ['low', 'medium', 'high', 'critical'];

type ExampleDefinition = {
  key: string;
  label: string;
  id: string;
  title: string;
  description: string;
  category: string;
  severity: string;
  outputTitle: string;
  outputSummary: string;
  inputs: InputRow[];
  conditionsAll: ConditionRow[];
  conditionsAny: ConditionRow[];
  maxTimeGap: string;
  minimumOverlap: string;
};

// Real, already-shipped patterns (config/behavior_definitions.d/core.yml and
// latency_and_errors.yml) reused as fill-in-the-form examples, not invented sample data — so
// what a new user sees here is a known-working two-input pattern with real fact paths, not
// something that can drift out of sync with what the engine actually supports. The id gets an
// "_example" suffix so Save to Pack can't silently collide with the real shipped definition.
const EXAMPLES: ExampleDefinition[] = [
  {
    key: 'cpu_throttling',
    label: 'Load Example: CPU + Throttling',
    id: 'cpu_throttling_example',
    title: 'Possible CPU throttling',
    description: 'Detects abnormal CPU usage occurring together with increased CPU throttling activity.',
    category: 'resource_constraint',
    severity: 'high',
    outputTitle: 'Possible CPU throttling detected',
    outputSummary: 'CPU usage showed abnormal behavior while throttling activity increased during the same analysis period.',
    inputs: [
      { alias: 'cpu', metricName: 'cpu_usage', analyzers: 'anomaly_zscore,pyod_outlier,trend' },
      { alias: 'throttling', metricName: 'cpu_throttled_seconds', analyzers: 'anomaly_zscore,pyod_outlier,trend,baseline_shift,ruptures' },
    ],
    conditionsAll: [
      { fact: 'cpu.anomaly.present', operator: 'equals', value: true },
      { fact: 'throttling.change.upward', operator: 'equals', value: true },
    ],
    conditionsAny: [
      { fact: 'throttling.anomaly.present', operator: 'equals', value: true },
      { fact: 'throttling.change.change_percent', operator: 'greater_than', value: 20 },
    ],
    maxTimeGap: '15m',
    minimumOverlap: '5m',
  },
  {
    key: 'latency_errors',
    label: 'Load Example: Latency + Errors',
    id: 'latency_error_cascade_example',
    title: 'Possible cascading failure',
    description:
      'Detects rising request latency occurring together with a rising error rate in the same analysis window — a common precursor to timeouts and cascading failures.',
    category: 'availability',
    severity: 'high',
    outputTitle: 'Possible cascading failure detected',
    outputSummary:
      'Latency and error rate both showed abnormal behavior in the same window — a pattern often seen when timeouts start cascading into failures downstream.',
    inputs: [
      { alias: 'latency', metricName: 'request_latency_p95', analyzers: 'anomaly_zscore,pyod_outlier,trend' },
      { alias: 'errors', metricName: 'error_rate', analyzers: 'anomaly_zscore,pyod_outlier,trend' },
    ],
    conditionsAll: [
      { fact: 'latency.anomaly.present', operator: 'equals', value: true },
      { fact: 'errors.anomaly.present', operator: 'equals', value: true },
    ],
    conditionsAny: [],
    maxTimeGap: '10m',
    minimumOverlap: '5m',
  },
];

function buildDraft(params: {
  id: string;
  title: string;
  description: string;
  category: string;
  severity: string;
  outputTitle: string;
  outputSummary: string;
  inputs: InputRow[];
  conditionsAll: ConditionRow[];
  conditionsAny: ConditionRow[];
  maxTimeGap: string;
  minimumOverlap: string;
}): BehaviorDefinitionDraft {
  return {
    id: params.id,
    title: params.title,
    description: params.description,
    inputs: params.inputs
      .filter((item) => item.alias && item.metricName)
      .map((item) => ({
        alias: item.alias,
        metric_name: item.metricName,
        analyzers: item.analyzers.split(',').map((a) => a.trim()).filter(Boolean),
      })),
    conditions: {
      all: params.conditionsAll,
      any: params.conditionsAny,
    },
    correlation: {
      same_analysis_context: true,
      max_time_gap: params.maxTimeGap || undefined,
      minimum_overlap: params.minimumOverlap || undefined,
    },
    output: {
      category: params.category || 'behavior',
      severity: params.severity || 'medium',
      title: params.outputTitle || params.title,
      summary: params.outputSummary,
      evidence: [],
    },
  };
}

function ConditionEditor({
  label,
  rows,
  onChange,
}: {
  label: string;
  rows: ConditionRow[];
  onChange: (rows: ConditionRow[]) => void;
}) {
  const update = (index: number, patch: Partial<ConditionRow>) => {
    onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  };
  return (
    <Box>
      <Typography sx={{ fontWeight: 800, mb: 1 }}>{label}</Typography>
      <Stack spacing={1.2}>
        {rows.map((row, index) => (
          <Stack key={index} direction="row" spacing={1} alignItems="center">
            <Tooltip title="Example: cpu.anomaly.present — written as <alias>.<fact path>. The alias is whatever you named the input above; see Fact Reference below for the full list of fact paths." arrow>
              <TextField
                size="small"
                label="Fact (alias.fact.path)"
                placeholder="cpu.anomaly.present"
                value={row.fact}
                onChange={(e) => update(index, { fact: e.target.value })}
                sx={{ flex: 2 }}
              />
            </Tooltip>
            <TextField
              select
              size="small"
              label="Operator"
              value={row.operator}
              onChange={(e) => update(index, { operator: e.target.value })}
              sx={{ minWidth: 140 }}
            >
              {OPERATORS.map((op) => (
                <MenuItem key={op} value={op}>
                  {op}
                </MenuItem>
              ))}
            </TextField>
            <Tooltip title="What the fact should equal / exceed / contain, e.g. true for a present/absent fact, upward for a trend direction, or 20 for a percent change." arrow>
              <TextField
                size="small"
                label="Value"
                placeholder="true / upward / 20"
                value={String(row.value ?? '')}
                onChange={(e) => update(index, { value: e.target.value })}
                sx={{ flex: 1 }}
              />
            </Tooltip>
            <IconButton size="small" onClick={() => onChange(rows.filter((_, i) => i !== index))} aria-label={`Remove ${label} condition ${index + 1}`}>
              <DeleteRoundedIcon fontSize="small" />
            </IconButton>
          </Stack>
        ))}
        <Button
          size="small"
          startIcon={<AddRoundedIcon />}
          onClick={() => onChange([...rows, { fact: '', operator: 'equals', value: true }])}
          sx={{ alignSelf: 'flex-start', textTransform: 'none' }}
        >
          Add {label.toLowerCase()} condition
        </Button>
      </Stack>
    </Box>
  );
}

export function BehaviorLabPage() {
  const [id, setId] = useState('');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState('behavior');
  const [severity, setSeverity] = useState('medium');
  const [outputTitle, setOutputTitle] = useState('');
  const [outputSummary, setOutputSummary] = useState('');
  const [inputs, setInputs] = useState<InputRow[]>([{ alias: '', metricName: '', analyzers: '' }]);
  const [conditionsAll, setConditionsAll] = useState<ConditionRow[]>([]);
  const [conditionsAny, setConditionsAny] = useState<ConditionRow[]>([]);
  const [maxTimeGap, setMaxTimeGap] = useState('15m');
  const [minimumOverlap, setMinimumOverlap] = useState('5m');
  const [selectedSample, setSelectedSample] = useState('');
  const [packFile, setPackFile] = useState('custom_patterns.yml');

  const factsQuery = useQuery({ queryKey: ['behavior-facts'], queryFn: api.behaviorFacts });
  const samplesQuery = useQuery({ queryKey: ['metric-analyzer-samples'], queryFn: api.metricAnalyzerSamples });
  // Every metric name stored so far, offered as you type: the real names your sources send (an
  // OTel name like container.memory.usage, a Prometheus one like process_resident_memory_bytes).
  const metricsQuery = useQuery({ queryKey: ['behavior-available-metrics'], queryFn: api.behaviorAvailableMetrics, retry: false });
  const metricOptions = Array.isArray(metricsQuery.data) ? metricsQuery.data : [];
  const sampleOptions = samplesQuery.data ?? [];

  const draft = buildDraft({
    id,
    title,
    description,
    category,
    severity,
    outputTitle,
    outputSummary,
    inputs,
    conditionsAll,
    conditionsAny,
    maxTimeGap,
    minimumOverlap,
  });

  const validateMutation = useMutation({ mutationFn: () => api.validateBehaviorDefinition(draft) });
  const dryRunMutation = useMutation({
    mutationFn: () => {
      const sample = sampleOptions.find(
        (item) => `${item.service}::${item.metric_name}::${item.analysis_run_id ?? ''}` === selectedSample
      );
      if (!sample?.analysis_run_id) throw new Error('Select a historical sample first');
      return api.dryRunBehaviorDefinition(draft, sample.analysis_run_id, sample.service);
    },
  });
  const saveMutation = useMutation({ mutationFn: () => api.saveBehaviorDefinitionToPack(draft, packFile) });

  const updateInput = (index: number, patch: Partial<InputRow>) => {
    setInputs(inputs.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  };

  const applyExample = (example: ExampleDefinition) => {
    setId(example.id);
    setTitle(example.title);
    setDescription(example.description);
    setCategory(example.category);
    setSeverity(example.severity);
    setOutputTitle(example.outputTitle);
    setOutputSummary(example.outputSummary);
    setInputs(example.inputs);
    setConditionsAll(example.conditionsAll);
    setConditionsAny(example.conditionsAny);
    setMaxTimeGap(example.maxTimeGap);
    setMinimumOverlap(example.minimumOverlap);
    setSelectedSample('');
    validateMutation.reset();
    dryRunMutation.reset();
    saveMutation.reset();
  };

  return (
    <Stack spacing={3}>
      <PageHeader
        title="Behavior Lab"
        subtitle="Author a behavior definition, test it against real historical data, and save it as a pack — without editing YAML by hand or guessing at fact names."
      />

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Typography sx={{ fontWeight: 900, fontSize: 18, mb: 0.5 }}>Not sure where to start?</Typography>
        <Typography sx={{ color: ui.muted, mb: 1.5, fontSize: 13 }}>
          Load a real, already-working pattern below to see how two metrics combine into one behavior — then tweak it into your own.
        </Typography>
        <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap>
          {EXAMPLES.map((example) => (
            <Button key={example.key} variant="outlined" size="small" onClick={() => applyExample(example)} sx={{ textTransform: 'none', fontWeight: 800 }}>
              {example.label}
            </Button>
          ))}
        </Stack>
      </WorkspacePanel>

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Typography sx={{ fontWeight: 900, fontSize: 18, mb: 1.5 }}>1. Define the pattern</Typography>
        <Grid container spacing={1.5}>
          <Grid size={{ xs: 12, md: 4 }}>
            <Tooltip title="Example: cpu_and_errors — a short, unique, lowercase name for this pattern (no spaces). Used internally, not shown to end users." arrow>
              <TextField fullWidth size="small" label="Id" placeholder="cpu_and_errors" value={id} onChange={(e) => setId(e.target.value)} />
            </Tooltip>
          </Grid>
          <Grid size={{ xs: 12, md: 4 }}>
            <Tooltip title="Example: Possible CPU throttling — a short, human-readable name shown in the Rules and Patterns Library lists." arrow>
              <TextField fullWidth size="small" label="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
            </Tooltip>
          </Grid>
          <Grid size={{ xs: 12, md: 4 }}>
            <TextField
              select
              fullWidth
              size="small"
              label="Severity"
              helperText="How serious this is when it fires — shown as a colored badge."
              value={severity}
              onChange={(e) => setSeverity(e.target.value)}
            >
              {SEVERITIES.map((s) => (
                <MenuItem key={s} value={s}>
                  {s}
                </MenuItem>
              ))}
            </TextField>
          </Grid>
          <Grid size={{ xs: 12 }}>
            <Tooltip title="Example: Detects CPU usage rising together with increased throttling activity. — explain what this pattern is looking for and why it matters." arrow>
              <TextField fullWidth size="small" label="Description" value={description} onChange={(e) => setDescription(e.target.value)} />
            </Tooltip>
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <Tooltip title="Example: Possible CPU throttling detected — the headline shown on the finding when this pattern matches. Defaults to Title if left blank." arrow>
              <TextField fullWidth size="small" label="Output title" value={outputTitle} onChange={(e) => setOutputTitle(e.target.value)} placeholder={title || 'Shown on the detected finding'} />
            </Tooltip>
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <Tooltip title="Example: resource_constraint, availability, performance — a grouping tag used for filtering and reporting." arrow>
              <TextField fullWidth size="small" label="Category" value={category} onChange={(e) => setCategory(e.target.value)} />
            </Tooltip>
          </Grid>
          <Grid size={{ xs: 12 }}>
            <Tooltip title="Example: CPU usage and throttling both increased in the same window. — one or two sentences shown to whoever reviews the match." arrow>
              <TextField fullWidth size="small" label="Output summary" value={outputSummary} onChange={(e) => setOutputSummary(e.target.value)} />
            </Tooltip>
          </Grid>
        </Grid>
      </WorkspacePanel>

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Typography sx={{ fontWeight: 900, fontSize: 18, mb: 1.5 }}>2. Inputs (metrics to combine)</Typography>
        <Stack spacing={1.2}>
          {inputs.map((row, index) => (
            <Stack key={index} direction="row" spacing={1} alignItems="center">
              <Tooltip title="Example: cpu — a short nickname for this metric. You'll use it in Conditions below, e.g. cpu.anomaly.present." arrow>
                <TextField size="small" label="Alias" placeholder="cpu" value={row.alias} onChange={(e) => updateInput(index, { alias: e.target.value })} sx={{ flex: 1 }} />
              </Tooltip>
              <Tooltip title="Example: cpu_usage or request_latency_p95 — the real metric name from your data. Start typing to pick from the metric names Ops Signals has stored." arrow>
                <Autocomplete
                  freeSolo
                  options={metricOptions}
                  inputValue={row.metricName}
                  onInputChange={(_event, value) => updateInput(index, { metricName: value })}
                  sx={{ flex: 2 }}
                  renderInput={(params) => <TextField {...params} size="small" label="Metric name" placeholder="cpu_usage" />}
                />
              </Tooltip>
              <Tooltip title="Example: trend,anomaly_zscore — only count evidence from these analyzers for this input. Leave blank to use signals from any analyzer." arrow>
                <TextField size="small" label="Analyzers (comma-separated, optional)" placeholder="trend,anomaly_zscore" value={row.analyzers} onChange={(e) => updateInput(index, { analyzers: e.target.value })} sx={{ flex: 2 }} />
              </Tooltip>
              <IconButton size="small" onClick={() => setInputs(inputs.filter((_, i) => i !== index))} aria-label={`Remove input ${index + 1}`}>
                <DeleteRoundedIcon fontSize="small" />
              </IconButton>
            </Stack>
          ))}
          <Button size="small" startIcon={<AddRoundedIcon />} onClick={() => setInputs([...inputs, { alias: '', metricName: '', analyzers: '' }])} sx={{ alignSelf: 'flex-start', textTransform: 'none' }}>
            Add input
          </Button>
        </Stack>
      </WorkspacePanel>

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Typography sx={{ fontWeight: 900, fontSize: 18, mb: 0.5 }}>3. Conditions</Typography>
        <Typography sx={{ color: ui.muted, mb: 1.5, fontSize: 13 }}>
          Every "all" condition must pass, and at least one "any" condition must pass (if any are declared). See the Fact Reference below for valid fact paths.
        </Typography>
        <Stack spacing={2}>
          <ConditionEditor label="All" rows={conditionsAll} onChange={setConditionsAll} />
          <ConditionEditor label="Any" rows={conditionsAny} onChange={setConditionsAny} />
          <Stack direction="row" spacing={1.5}>
            <Tooltip title="Example: 15m — how far apart two inputs' signals can be and still count as related to the same event." arrow>
              <TextField size="small" label="Max time gap" value={maxTimeGap} onChange={(e) => setMaxTimeGap(e.target.value)} sx={{ width: 160 }} />
            </Tooltip>
            <Tooltip title="Example: 5m — how much the inputs' time windows must overlap to count as happening together, not just nearby." arrow>
              <TextField size="small" label="Minimum overlap" value={minimumOverlap} onChange={(e) => setMinimumOverlap(e.target.value)} sx={{ width: 160 }} />
            </Tooltip>
          </Stack>
        </Stack>
      </WorkspacePanel>

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
          <Typography sx={{ fontWeight: 900, fontSize: 18 }}>4. Validate and test</Typography>
          <Button variant="outlined" onClick={() => validateMutation.mutate()} disabled={validateMutation.isPending} sx={{ textTransform: 'none', fontWeight: 800 }}>
            Validate
          </Button>
        </Stack>
        {validateMutation.data ? (
          <Alert severity={validateMutation.data.valid ? 'success' : 'error'} sx={{ mb: 2 }}>
            {validateMutation.data.valid ? 'Definition is valid.' : validateMutation.data.errors.join(' ')}
            {validateMutation.data.warnings.length ? (
              <Box sx={{ mt: 1 }}>
                {validateMutation.data.warnings.map((w) => (
                  <Typography key={w} sx={{ fontSize: 13 }}>
                    ⚠ {w}
                  </Typography>
                ))}
              </Box>
            ) : null}
          </Alert>
        ) : null}

        <TextField
          select
          fullWidth
          size="small"
          label="Select Existing Sample"
          helperText="Pick a real service + metric + analysis run you already have data for, to test this pattern against actual historical values."
          value={selectedSample}
          onChange={(e) => setSelectedSample(String(e.target.value))}
          sx={{ mb: 1.5 }}
        >
          {sampleOptions.map((sample) => (
            <MenuItem
              key={`${sample.service}-${sample.metric_name}-${sample.analysis_run_id ?? 'none'}`}
              value={`${sample.service}::${sample.metric_name}::${sample.analysis_run_id ?? ''}`}
            >
              {sample.service} / {sample.metric_name} {sample.analysis_run_id ? `(${sample.analysis_run_id})` : ''}
            </MenuItem>
          ))}
        </TextField>
        <Button startIcon={<ScienceRoundedIcon />} variant="contained" onClick={() => dryRunMutation.mutate()} disabled={dryRunMutation.isPending || !selectedSample} sx={{ bgcolor: '#009688', textTransform: 'none', fontWeight: 850 }}>
          Test Pattern
        </Button>

        {dryRunMutation.data ? (
          <Box sx={{ mt: 2 }}>
            <Chip
              label={dryRunMutation.data.matched ? 'MATCHED' : 'NOT_MATCHED'}
              color={dryRunMutation.data.matched ? 'success' : 'default'}
              sx={{ fontWeight: 850, mb: 1.5 }}
            />
            <Typography sx={{ mb: 1 }}>{dryRunMutation.data.description}</Typography>
            <Typography sx={{ fontWeight: 800, mb: 0.5 }}>Confidence: {Math.round(dryRunMutation.data.confidence * 100)}%</Typography>
            {dryRunMutation.data.matched_conditions.length ? (
              <Stack spacing={0.5} sx={{ mt: 1 }}>
                {dryRunMutation.data.matched_conditions.map((c, i) => (
                  <Typography key={i} sx={{ fontSize: 13, color: c.passed ? ui.green : ui.red }}>
                    {c.passed ? '✓' : '✗'} {String(c.fact)} {String(c.operator)} {String(c.value)}
                  </Typography>
                ))}
              </Stack>
            ) : null}
            <Box component="pre" sx={{ mt: 1.5, p: 1.5, bgcolor: '#0f172a', color: '#e2e8f0', borderRadius: 2, fontSize: 12, overflow: 'auto' }}>
              {JSON.stringify(dryRunMutation.data.facts, null, 2)}
            </Box>
          </Box>
        ) : null}
      </WorkspacePanel>

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Typography sx={{ fontWeight: 900, fontSize: 18, mb: 1.5 }}>5. Save as a pack</Typography>
        <Stack direction="row" spacing={1.5} alignItems="center">
          <Tooltip title="Example: custom_patterns.yml — the YAML file this pattern is saved into under config/behavior_definitions.d/. Reuse the same name to group related patterns together." arrow>
            <TextField size="small" label="Pack file" value={packFile} onChange={(e) => setPackFile(e.target.value)} sx={{ width: 260 }} />
          </Tooltip>
          <Button variant="contained" onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending} sx={{ bgcolor: ui.blue, textTransform: 'none', fontWeight: 850 }}>
            Save to Pack
          </Button>
        </Stack>
        {saveMutation.data ? (
          <Alert severity={saveMutation.data.saved ? 'success' : 'error'} sx={{ mt: 1.5 }}>
            {saveMutation.data.saved
              ? `Saved to config/behavior_definitions.d/${saveMutation.data.pack_file}.`
              : saveMutation.data.validation.errors.join(' ')}
          </Alert>
        ) : null}
      </WorkspacePanel>

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Typography sx={{ fontWeight: 900, fontSize: 18, mb: 1.5 }}>Fact Reference</Typography>
        <Typography sx={{ color: ui.muted, mb: 1.5, fontSize: 13 }}>
          Every fact is written as &lt;alias&gt;.&lt;fact path&gt; — e.g. an input aliased "cpu" with the fact "anomaly.present" below is referenced as "cpu.anomaly.present".
        </Typography>
        <Grid container spacing={1}>
          {(factsQuery.data ?? []).map((fact) => (
            <Grid key={fact.key} size={{ xs: 12, md: 6 }}>
              <Box sx={{ p: 1.2, border: `1px solid ${ui.border}`, borderRadius: 2 }}>
                <Typography sx={{ fontWeight: 800, fontFamily: 'monospace', fontSize: 13 }}>{fact.key}</Typography>
                <Typography sx={{ color: ui.muted, fontSize: 12 }}>{fact.description}</Typography>
                <Typography sx={{ fontSize: 12 }}>example: {JSON.stringify(fact.example)}</Typography>
              </Box>
            </Grid>
          ))}
        </Grid>
      </WorkspacePanel>
    </Stack>
  );
}
