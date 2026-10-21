import { useEffect, useState } from 'react';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
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
import CloseRoundedIcon from '@mui/icons-material/CloseRounded';
import EditNoteRoundedIcon from '@mui/icons-material/EditNoteRounded';
import ExpandMoreRoundedIcon from '@mui/icons-material/ExpandMoreRounded';
import ListAltRoundedIcon from '@mui/icons-material/ListAltRounded';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { WorkspacePanel } from '../standalone/components';
import { ui } from '../standalone/theme';
import type { BehaviorConditionInput, BehaviorDefinitionDraft, CatalogPattern } from '../types';
import { suggestMetrics } from '../utils/metricSuggest';
import { analyzersFor, parsePlain, PLAIN_KINDS, toCondition, type PlainKind } from '../utils/plainConditions';
import { HistoryPreview } from './HistoryPreview';

type InputRow = {
  alias: string;
  metricName: string;
  analyzers: string;
  /** From a catalog template: the signal in plain words, and words to find the user's metric by. */
  label?: string;
  keywords?: string[];
  /** Filled in because it was the only stored metric that fits; said so under the input. */
  autoPicked?: boolean;
};
/** `manual`: written as a fact by hand, even when it could be said in plain words. */
type ConditionRow = BehaviorConditionInput & { manual?: boolean };

const OPERATORS = ['equals', 'greater_than', 'less_than', 'contains'];
const SEVERITIES = ['low', 'medium', 'high', 'critical'];

/** What the builder starts from: a blank form, a shipped rule, a suggestion or an example. */
export type BuilderSeed = {
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

export const BLANK_SEED: BuilderSeed = {
  id: '',
  title: '',
  description: '',
  category: 'behavior',
  severity: 'medium',
  outputTitle: '',
  outputSummary: '',
  inputs: [{ alias: '', metricName: '', analyzers: '' }],
  conditionsAll: [],
  conditionsAny: [],
  maxTimeGap: '15m',
  minimumOverlap: '5m',
};

const text = (value: unknown, fallback = ''): string => (typeof value === 'string' ? value : fallback);

function conditionRows(rows: unknown): ConditionRow[] {
  return Array.isArray(rows)
    ? rows.map((row) => ({ fact: text(row?.fact), operator: text(row?.operator, 'equals'), value: row?.value ?? true }))
    : [];
}

/**
 * A seed from a definition as the API returns it: a shipped rule (GET /api/behavior-definitions) or
 * a suggestion's draft (draft_definition_json). The id gets `idSuffix`, so saving the copy can't
 * overwrite the original.
 */
export function seedFromDefinition(definition: Record<string, unknown>, idSuffix = ''): BuilderSeed {
  const output = (definition.output ?? {}) as Record<string, unknown>;
  const correlation = (definition.correlation ?? {}) as Record<string, unknown>;
  const conditions = (definition.conditions ?? {}) as Record<string, unknown>;
  const inputs = Array.isArray(definition.inputs) ? (definition.inputs as Array<Record<string, unknown>>) : [];
  return {
    id: `${text(definition.id)}${idSuffix}`,
    title: text(definition.title),
    description: text(definition.description),
    category: text(output.category, 'behavior'),
    severity: text(output.severity, 'medium'),
    outputTitle: text(output.title),
    outputSummary: text(output.summary).trim(),
    inputs: inputs.length
      ? inputs.map((item) => ({
          alias: text(item.alias),
          metricName: text(item.metric_name),
          analyzers: Array.isArray(item.analyzers) ? item.analyzers.join(',') : '',
        }))
      : BLANK_SEED.inputs,
    conditionsAll: conditionRows(conditions.all),
    conditionsAny: conditionRows(conditions.any),
    maxTimeGap: text(correlation.max_time_gap, BLANK_SEED.maxTimeGap),
    minimumOverlap: text(correlation.minimum_overlap, BLANK_SEED.minimumOverlap),
  };
}

/** A seed from a catalog template: its draft, each input labelled with its signal and keywords. */
export function seedFromCatalog(pattern: CatalogPattern): BuilderSeed {
  const seed = seedFromDefinition(pattern.draft ?? {});
  const signals = new Map(pattern.signals.map((signal) => [signal.alias, signal]));
  return {
    ...seed,
    inputs: seed.inputs.map((row) => {
      const signal = signals.get(row.alias);
      return signal ? { ...row, label: signal.label, keywords: signal.keywords } : row;
    }),
  };
}

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
      all: params.conditionsAll.map(({ manual: _manual, ...row }) => row),
      any: params.conditionsAny.map(({ manual: _manual, ...row }) => row),
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

type InputChoice = { alias: string; name: string };

/** A condition by hand: the fact the engine reads (Advanced: all facts lists them), an operator, a value. */
function ManualCondition({ label, index, row, update }: { label: string; index: number; row: ConditionRow; update: (patch: Partial<ConditionRow>) => void }) {
  return (
    <>
      <Tooltip title="Example: cpu.anomaly.present — written as <alias>.<fact path>. The alias is whatever you named the input above; Advanced: all facts at the end lists every fact path." arrow>
        <TextField
          size="small"
          label="Fact (alias.fact.path)"
          placeholder="cpu.anomaly.present"
          value={row.fact}
          onChange={(e) => update({ fact: e.target.value })}
          sx={{ flex: 2 }}
        />
      </Tooltip>
      <TextField select size="small" label="Operator" id={`${label}-operator-${index}`} value={row.operator} onChange={(e) => update({ operator: e.target.value })} sx={{ minWidth: 140 }}>
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
          onChange={(e) => update({ value: e.target.value })}
          sx={{ flex: 1 }}
        />
      </Tooltip>
    </>
  );
}

/**
 * Conditions in plain words: [metric] [is rising / is falling / ...]. Anything else is written as a
 * fact by hand, and any row can switch to that.
 */
function ConditionEditor({
  label,
  rows,
  inputs,
  onChange,
  onKindPicked,
}: {
  label: string;
  rows: ConditionRow[];
  inputs: InputChoice[];
  onChange: (rows: ConditionRow[]) => void;
  /** So the input's analyzer list can keep one that produces this fact. */
  onKindPicked: (alias: string, kind: PlainKind) => void;
}) {
  const update = (index: number, patch: Partial<ConditionRow>) => {
    onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  };
  const choose = (index: number, alias: string, kind: PlainKind, percent?: number) => {
    update(index, toCondition({ alias, kind, percent }));
    onKindPicked(alias, kind);
  };
  const add = () => {
    const used = new Set(rows.map((row) => parsePlain(row)?.alias));
    const alias = (inputs.find((input) => !used.has(input.alias)) ?? inputs[0])?.alias;
    if (!alias) {
      onChange([...rows, { fact: '', operator: 'equals', value: true, manual: true }]);
      return;
    }
    onChange([...rows, toCondition({ alias, kind: 'rising' })]);
    onKindPicked(alias, 'rising');
  };
  return (
    <Box>
      <Typography sx={{ fontWeight: 800, mb: 1 }}>{label}</Typography>
      <Stack spacing={1.2}>
        {rows.map((row, index) => {
          const plain = row.manual ? null : parsePlain(row);
          const choices = plain && !inputs.some((input) => input.alias === plain.alias) ? [...inputs, { alias: plain.alias, name: '' }] : inputs;
          return (
            <Stack key={index} direction="row" spacing={1} alignItems="center">
              {plain ? (
                <>
                  <TextField
                    select
                    size="small"
                    label="Metric"
                    id={`${label}-metric-${index}`}
                    value={plain.alias}
                    onChange={(e) => choose(index, e.target.value, plain.kind, plain.percent)}
                    sx={{ flex: 2 }}
                  >
                    {choices.map((input) => (
                      <MenuItem key={input.alias} value={input.alias}>
                        {input.alias}
                        {input.name ? <Box component="span" sx={{ ml: 1, color: ui.muted, fontFamily: 'monospace', fontSize: 12 }}>{input.name}</Box> : null}
                      </MenuItem>
                    ))}
                  </TextField>
                  <TextField
                    select
                    size="small"
                    label="What happens"
                    id={`${label}-kind-${index}`}
                    value={plain.kind}
                    onChange={(e) => choose(index, plain.alias, e.target.value as PlainKind, plain.percent)}
                    sx={{ flex: 2 }}
                  >
                    {PLAIN_KINDS.map((item) => <MenuItem key={item.kind} value={item.kind}>{item.label}</MenuItem>)}
                  </TextField>
                  {plain.percent !== undefined ? (
                    <TextField
                      size="small"
                      type="number"
                      label="Percent"
                      value={plain.percent}
                      onChange={(e) => choose(index, plain.alias, plain.kind, Math.abs(Number(e.target.value)))}
                      slotProps={{ htmlInput: { min: 0 } }}
                      sx={{ width: 110 }}
                    />
                  ) : null}
                </>
              ) : (
                <ManualCondition label={label} index={index} row={row} update={(patch) => update(index, patch)} />
              )}
              {plain ? (
                <Tooltip title="Write this condition as a fact by hand, for anything the plain choices can't say." arrow>
                  <IconButton size="small" onClick={() => update(index, { manual: true })} aria-label={`Write ${label} condition ${index + 1} by hand`}>
                    <EditNoteRoundedIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              ) : parsePlain(row) ? (
                <Tooltip title="Show this condition as plain choices again." arrow>
                  <IconButton size="small" onClick={() => update(index, { manual: false })} aria-label={`Show ${label} condition ${index + 1} in plain words`}>
                    <ListAltRoundedIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              ) : null}
              <IconButton size="small" onClick={() => onChange(rows.filter((_, i) => i !== index))} aria-label={`Remove ${label} condition ${index + 1}`}>
                <DeleteRoundedIcon fontSize="small" />
              </IconButton>
            </Stack>
          );
        })}
        <Button
          size="small"
          startIcon={<AddRoundedIcon />}
          onClick={add}
          sx={{ alignSelf: 'flex-start', textTransform: 'none' }}
        >
          Add {label.toLowerCase()} condition
        </Button>
      </Stack>
    </Box>
  );
}

type Props = {
  /** Where the form starts; the caller remounts the builder (a new `key`) to start over. */
  seed?: BuilderSeed;
  /** Shown above the title, e.g. "Editing a copy of a shipped rule". */
  sourceLabel?: string;
  onClose?: () => void;
  /** On a blank pattern: closes the builder and shows the known patterns to start from instead. */
  onBrowseKnown?: () => void;
};

/**
 * Author a behavior definition, test it against real historical data, and save it to a pack. Opens
 * as a side panel on Behavior Intelligence from New pattern, Edit copy and Turn into pattern.
 */
/** Under a template's input: whether it points at a stored metric, and the best fits when not. */
function MetricMatch({ row, options, onPick }: { row: InputRow; options: string[]; onPick: (metricName: string) => void }) {
  if (options.includes(row.metricName)) {
    return row.autoPicked ? (
      <Typography sx={{ mt: 0.75, fontSize: 13 }}>
        Picked <Box component="span" sx={{ fontFamily: 'monospace' }}>{row.metricName}</Box>, the only stored metric that looks like this one. Not right? Type another.
      </Typography>
    ) : (
      <Typography sx={{ mt: 0.75, fontSize: 13, color: ui.green }}>Matched to a metric Ops Signals has stored.</Typography>
    );
  }
  const suggestions = suggestMetrics(row.keywords ?? [], options);
  return (
    <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap" sx={{ mt: 0.75 }}>
      <Typography sx={{ fontSize: 13, color: ui.orange }}>
        {suggestions.length ? 'Pick your metric:' : 'No stored metric looks like this one. Type to search all of them.'}
      </Typography>
      {suggestions.map((metric) => (
        <Chip key={metric} size="small" variant="outlined" clickable label={metric} onClick={() => onPick(metric)} sx={{ fontFamily: 'monospace' }} />
      ))}
    </Stack>
  );
}

export function BehaviorBuilder({ seed = BLANK_SEED, sourceLabel, onClose, onBrowseKnown }: Props) {
  const [id, setId] = useState(seed.id);
  const [title, setTitle] = useState(seed.title);
  const [description, setDescription] = useState(seed.description);
  const [category, setCategory] = useState(seed.category);
  const [severity, setSeverity] = useState(seed.severity);
  const [outputTitle, setOutputTitle] = useState(seed.outputTitle);
  const [outputSummary, setOutputSummary] = useState(seed.outputSummary);
  const [inputs, setInputs] = useState<InputRow[]>(seed.inputs);
  const [conditionsAll, setConditionsAll] = useState<ConditionRow[]>(seed.conditionsAll);
  const [conditionsAny, setConditionsAny] = useState<ConditionRow[]>(seed.conditionsAny);
  const [maxTimeGap, setMaxTimeGap] = useState(seed.maxTimeGap);
  const [minimumOverlap, setMinimumOverlap] = useState(seed.minimumOverlap);
  const [packFile, setPackFile] = useState('custom_patterns.yml');

  const factsQuery = useQuery({ queryKey: ['behavior-facts'], queryFn: api.behaviorFacts });
  // Every metric name stored so far, offered as you type: the real names your sources send (an
  // OTel name like container.memory.usage, a Prometheus one like process_resident_memory_bytes).
  const metricsQuery = useQuery({ queryKey: ['behavior-available-metrics'], queryFn: api.behaviorAvailableMetrics, retry: false });
  const metricOptions = Array.isArray(metricsQuery.data) ? metricsQuery.data : [];
  // A template's signals start on a generic name (consumer_lag); until each points at a metric
  // Ops Signals has stored, a test could only say "no signals". Without the list, nothing is held up.
  const unmapped = metricOptions.length ? inputs.filter((row) => row.keywords && !metricOptions.includes(row.metricName)) : [];

  // A template signal only one stored metric fits needs no choosing: fill it in, once, and say so.
  const [autoPicked, setAutoPicked] = useState(false);
  useEffect(() => {
    if (autoPicked || !metricOptions.length) return;
    setAutoPicked(true);
    setInputs((rows) => rows.map((row) => {
      if (!row.keywords || metricOptions.includes(row.metricName)) return row;
      const fits = suggestMetrics(row.keywords, metricOptions);
      return fits.length === 1 ? { ...row, metricName: fits[0], autoPicked: true } : row;
    }));
  }, [autoPicked, metricOptions]);

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
  const saveMutation = useMutation({ mutationFn: () => api.saveBehaviorDefinitionToPack(draft, packFile) });

  const updateInput = (index: number, patch: Partial<InputRow>) => {
    setInputs(inputs.map((row, i) => {
      if (i !== index) return row;
      // A metric the user chose is no longer the one picked for them.
      const chosen = patch.metricName !== undefined && patch.metricName !== row.metricName;
      return { ...row, ...patch, ...(chosen ? { autoPicked: false } : {}) };
    }));
  };
  // A condition can only be true when the input's analyzers produce its fact: keep one that does.
  // An empty list already means any analyzer.
  const keepAnalyzersFor = (alias: string, kind: PlainKind) => {
    const needed = analyzersFor(kind);
    setInputs((rows) => rows.map((row) => {
      const listed = row.analyzers.split(',').map((item) => item.trim()).filter(Boolean);
      if (row.alias !== alias || !listed.length || listed.some((item) => needed.includes(item))) return row;
      return { ...row, analyzers: [...listed, ...needed].join(',') };
    }));
  };
  const inputChoices: InputChoice[] = inputs.filter((row) => row.alias).map((row) => ({ alias: row.alias, name: row.metricName }));

  return (
    <Stack spacing={3}>
      <Stack direction="row" alignItems="flex-start" spacing={2}>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          {sourceLabel ? <Typography variant="caption" sx={{ color: ui.muted, fontWeight: 700 }}>{sourceLabel}</Typography> : null}
          <Typography component="h2" sx={{ fontWeight: 900, fontSize: 24 }}>{seed.title || 'New pattern'}</Typography>
          <Typography sx={{ color: ui.muted, fontSize: 14 }}>
            Combine metrics into one pattern, test it against real historical data, and save it to a pack — without editing YAML by hand or guessing at fact names.
          </Typography>
        </Box>
        {onClose ? (
          <IconButton onClick={onClose} aria-label="Close builder">
            <CloseRoundedIcon />
          </IconButton>
        ) : null}
      </Stack>

      {onBrowseKnown ? (
        <Alert
          severity="info"
          action={<Button color="inherit" size="small" onClick={onBrowseKnown} sx={{ textTransform: 'none', fontWeight: 800 }}>See known patterns</Button>}
        >
          Not sure where to start? Pick a known pattern — its metrics and conditions are already filled in.
        </Alert>
      ) : null}

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Typography sx={{ fontWeight: 900, fontSize: 18, mb: 1.5 }}>1. Define the pattern</Typography>
        <Grid container spacing={1.5}>
          <Grid size={{ xs: 12, md: 4 }}>
            <Tooltip title="Example: cpu_and_errors — a short, unique, lowercase name for this pattern (no spaces). Used internally, not shown to end users." arrow>
              <TextField fullWidth size="small" label="Id" placeholder="cpu_and_errors" value={id} onChange={(e) => setId(e.target.value)} />
            </Tooltip>
          </Grid>
          <Grid size={{ xs: 12, md: 4 }}>
            <Tooltip title="Example: Possible CPU throttling — a short, human-readable name shown in the Patterns list." arrow>
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
            <Box key={index}>
            {row.label ? <Typography sx={{ fontWeight: 800, fontSize: 13, mb: 0.75 }}>{row.label}</Typography> : null}
            <Stack direction="row" spacing={1} alignItems="center">
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
            {row.keywords && metricOptions.length ? <MetricMatch row={row} options={metricOptions} onPick={(metricName) => updateInput(index, { metricName })} /> : null}
            </Box>
          ))}
          <Button size="small" startIcon={<AddRoundedIcon />} onClick={() => setInputs([...inputs, { alias: '', metricName: '', analyzers: '' }])} sx={{ alignSelf: 'flex-start', textTransform: 'none' }}>
            Add input
          </Button>
        </Stack>
      </WorkspacePanel>

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Typography sx={{ fontWeight: 900, fontSize: 18, mb: 0.5 }}>3. Conditions</Typography>
        <Typography sx={{ color: ui.muted, mb: 1.5, fontSize: 13 }}>
          Every "all" condition must pass, and at least one "any" condition must pass (if any are declared). For anything the choices can't say, write the condition by hand.
        </Typography>
        <Stack spacing={2}>
          <ConditionEditor label="All" rows={conditionsAll} inputs={inputChoices} onChange={setConditionsAll} onKindPicked={keepAnalyzersFor} />
          <ConditionEditor label="Any" rows={conditionsAny} inputs={inputChoices} onChange={setConditionsAny} onKindPicked={keepAnalyzersFor} />
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
          <Typography sx={{ fontWeight: 900, fontSize: 18 }}>4. Check and try it</Typography>
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

        {unmapped.length ? (
          <Typography role="status" sx={{ fontSize: 13, color: ui.orange }}>
            Pick your metric for {unmapped.map((row) => row.label ?? row.alias).join(', ')} first (step 2).
          </Typography>
        ) : null}

        <HistoryPreview
          draft={draft}
          blockedReason={unmapped.length ? `Pick your metric for ${unmapped.map((row) => row.label ?? row.alias).join(', ')} first (step 2).` : null}
        />
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

      <Accordion disableGutters sx={{ bgcolor: 'transparent', border: `1px solid ${ui.border}`, borderRadius: 2, '&::before': { display: 'none' } }}>
        <AccordionSummary expandIcon={<ExpandMoreRoundedIcon />}>
          <Box>
            <Typography sx={{ fontWeight: 900, fontSize: 16 }}>Advanced: all facts</Typography>
            <Typography sx={{ color: ui.muted, fontSize: 13 }}>Only needed to write a condition by hand.</Typography>
          </Box>
        </AccordionSummary>
        <AccordionDetails>
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
        </AccordionDetails>
      </Accordion>
    </Stack>
  );
}
