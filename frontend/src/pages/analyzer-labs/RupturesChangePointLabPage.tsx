import { useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded';
import TimelineRoundedIcon from '@mui/icons-material/TimelineRounded';
import { useMutation } from '@tanstack/react-query';
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../../api/queries';
import { PageHeader, WorkspacePanel } from '../../standalone/components';
import { ui } from '../../standalone/theme';
import type { CsvAnalyzerRoutingDecision, CsvValidationResult, ValidationSignal } from '../../types';
import { AnalyzerLabConfigPanel } from './AnalyzerLabConfigPanel';
import { passFailFromFinding } from './labConfig';
import { LabSandboxBanner, RunsUse, useAnalyzerInUse, useInUseComparison } from './labSettings';
import { labChanges } from '../../utils/analyzerSettings';

type Pattern = 'baseline_shift_up' | 'baseline_shift_down' | 'small_shift' | 'noisy_shift' | 'no_shift';

type GeneratedPoint = {
  index: number;
  timestamp: string;
  value: number;
  expected_change: boolean;
};

const PATTERNS: Array<{ value: Pattern; label: string; explanation: string }> = [
  { value: 'baseline_shift_up', label: 'Baseline shift up', explanation: 'The metric moves from one stable level to a higher stable level.' },
  { value: 'baseline_shift_down', label: 'Baseline shift down', explanation: 'The metric moves from one stable level to a lower stable level.' },
  { value: 'small_shift', label: 'Small shift', explanation: 'The metric changes slightly, often below the finding threshold.' },
  { value: 'noisy_shift', label: 'Noisy shift', explanation: 'The baseline changes, but noise makes the exact change point harder to locate.' },
  { value: 'no_shift', label: 'No shift', explanation: 'The metric stays around one stable baseline. Ruptures should avoid creating a finding.' },
];

const BASELINE_CONFIG = {
  threshold_percent: 25,
  min_segment_size: 5,
  change_threshold: 1.5,
  ruptures: {
    algorithm: 'binseg',
    model: 'l2',
    min_size: 5,
    jump: 5,
    n_bkps: 1,
  },
};

function seededRandom(seed: number) {
  let state = seed >>> 0;
  return () => {
    state = (1664525 * state + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

function gaussian(random: () => number) {
  const u1 = Math.max(random(), 1e-12);
  const u2 = Math.max(random(), 1e-12);
  return Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
}

function parseIntervalMs(interval: string) {
  const match = interval.trim().toLowerCase().match(/^(\d+)([smhd])$/);
  if (!match) return 300000;
  const value = Number(match[1]);
  const unit = match[2];
  const multipliers: Record<string, number> = { s: 1000, m: 60000, h: 3600000, d: 86400000 };
  return value * multipliers[unit];
}

function shiftPercentFor(pattern: Pattern, shiftPercent: number) {
  if (pattern === 'no_shift') return 0;
  if (pattern === 'small_shift') return Math.min(Math.abs(shiftPercent), 12);
  if (pattern === 'baseline_shift_down') return -Math.abs(shiftPercent);
  return Math.abs(shiftPercent);
}

function generateSeries(input: {
  pattern: Pattern;
  samples: number;
  interval: string;
  seed: number;
  baseline: number;
  shiftPercent: number;
  noise: number;
  changePoint: number;
}) {
  const random = seededRandom(input.seed);
  const intervalMs = parseIntervalMs(input.interval);
  const start = new Date(Date.UTC(2026, 7, 24, 0, 0, 0));
  const effectiveShift = shiftPercentFor(input.pattern, input.shiftPercent);
  const afterBaseline = input.baseline * (1 + effectiveShift / 100);
  const actualChangePoint = Math.max(10, Math.min(input.samples - 10, input.changePoint));
  const noiseMultiplier = input.pattern === 'noisy_shift' ? 2.2 : 1;

  return Array.from({ length: input.samples }, (_, index): GeneratedPoint => {
    const center = index < actualChangePoint ? input.baseline : afterBaseline;
    return {
      index,
      timestamp: new Date(start.getTime() + index * intervalMs).toISOString(),
      value: Number((center + gaussian(random) * input.noise * noiseMultiplier).toFixed(3)),
      expected_change: index === actualChangePoint,
    };
  });
}

function toCsv(points: GeneratedPoint[]) {
  return [
    'timestamp,metric_name,value,service,expected_change',
    ...points.map((point) => `${point.timestamp},synthetic_ruptures_value,${point.value},ruptures-lab,${point.expected_change}`),
  ].join('\n');
}

function mean(values: number[]) {
  return values.reduce((sum, value) => sum + value, 0) / Math.max(values.length, 1);
}

function generatedSummary(points: GeneratedPoint[], changePoint: number) {
  const before = points.slice(0, changePoint).map((point) => point.value);
  const after = points.slice(changePoint).map((point) => point.value);
  const beforeMean = mean(before);
  const afterMean = mean(after);
  return {
    beforeMean,
    afterMean,
    percentChange: ((afterMean - beforeMean) / Math.max(Math.abs(beforeMean), 1e-9)) * 100,
  };
}

function baselineSignal(result: CsvValidationResult | null): ValidationSignal | undefined {
  return result?.signals.find((signal) => signal.analyzer_id === 'baseline_shift' || signal.evidence?.library === 'ruptures');
}

function routerDecision(result: CsvValidationResult | null) {
  return ((result?.analyzer_routing ?? []) as CsvAnalyzerRoutingDecision[]).find((decision) => decision.analyzer_id === 'ruptures' || decision.analyzer_id === 'baseline_shift');
}

function numberEvidence(signal: ValidationSignal | undefined, key: string) {
  const value = signal?.evidence?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function RupturesChangePointLabPage() {
  const [pattern, setPattern] = useState<Pattern>('baseline_shift_up');
  const [samples, setSamples] = useState(160);
  const [interval, setInterval] = useState('5m');
  const [seed, setSeed] = useState(7);
  const [baseline, setBaseline] = useState(50);
  const [shiftPercent, setShiftPercent] = useState(60);
  const [noise, setNoise] = useState(2);
  const [changePoint, setChangePoint] = useState(80);
  const [thresholdPercent, setThresholdPercent] = useState(BASELINE_CONFIG.threshold_percent);
  const [changeThreshold, setChangeThreshold] = useState(BASELINE_CONFIG.change_threshold);
  const [minSegmentSize, setMinSegmentSize] = useState(BASELINE_CONFIG.min_segment_size);
  const [jump, setJump] = useState(BASELINE_CONFIG.ruptures.jump);
  const [result, setResult] = useState<CsvValidationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { analyzer: inUse } = useAnalyzerInUse('baseline_shift');
  const { comparison, compare } = useInUseComparison();

  const boundedChangePoint = Math.max(10, Math.min(samples - 10, changePoint));
  const points = useMemo(
    () => generateSeries({ pattern, samples, interval, seed, baseline, shiftPercent, noise, changePoint: boundedChangePoint }),
    [baseline, boundedChangePoint, interval, noise, pattern, samples, seed, shiftPercent],
  );
  const chartData = points.map((point) => ({ ...point, time: new Date(point.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }));
  const summary = generatedSummary(points, boundedChangePoint);
  const signal = baselineSignal(result);
  const decision = routerDecision(result);
  const detectedIndex = numberEvidence(signal, 'change_point_index');
  const detectedPercent = numberEvidence(signal, 'percent_change');
  const indexError = detectedIndex === null ? null : Math.abs(detectedIndex - boundedChangePoint);
  const withinTolerance = indexError !== null && indexError <= Math.max(3, jump);
  const currentPattern = PATTERNS.find((item) => item.value === pattern);
  const implementation = {
    algorithm: BASELINE_CONFIG.ruptures.algorithm,
    model: BASELINE_CONFIG.ruptures.model,
    min_size: minSegmentSize,
    jump,
    n_bkps: BASELINE_CONFIG.ruptures.n_bkps,
  };
  const findingRules = {
    min_change_percent: thresholdPercent,
    min_effect_size: changeThreshold,
  };
  const shouldFind = Math.abs(summary.percentChange) >= thresholdPercent;
  const passFailStatus = result ? passFailFromFinding(shouldFind, result.findings.length > 0) : 'unknown';
  const values = { ruptures: implementation, finding_rules: findingRules };
  const hasChanges = labChanges(inUse, values).length > 0;

  const runMutation = useMutation({
    mutationFn: async () => {
      const form = new FormData();
      form.set('file', new File([toCsv(points)], 'ruptures-change-point-lab.csv', { type: 'text/csv' }));
      form.set('provider', 'generic');
      form.set('analyzer_id', 'baseline_shift');
      form.set('service', 'ruptures-lab');
      form.set('metric_name', 'synthetic_ruptures_value');
      form.set('interval', interval);
      form.set('analyzer_overrides', JSON.stringify({
        baseline_shift: {
          finding_rules: {
            min_change_percent: thresholdPercent,
            min_effect_size: changeThreshold,
          },
          ruptures: {
            algorithm: BASELINE_CONFIG.ruptures.algorithm,
            model: BASELINE_CONFIG.ruptures.model,
            min_size: minSegmentSize,
            jump,
            n_bkps: BASELINE_CONFIG.ruptures.n_bkps,
          },
        },
      }));
      const nextResult = await api.runCsvValidation(form);
      if (hasChanges) compare(form);
      return nextResult;
    },
    onSuccess: (nextResult) => {
      setError(null);
      setResult(nextResult);
    },
    onError: (err: unknown) => {
      setResult(null);
      setError(err instanceof Error ? err.message : 'Ruptures lab execution failed');
    },
  });

  return (
    <Stack spacing={3}>
      <PageHeader title="Ruptures Change Point Lab" subtitle="Generate baseline shifts, inspect the change point, run the ruptures-backed analyzer, and compare expected vs detected behavior." />
      <LabSandboxBanner analyzerId="baseline_shift" paths={['finding_rules.min_change_percent', 'finding_rules.min_effect_size', 'ruptures.min_size', 'ruptures.jump']} />

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Typography sx={{ fontWeight: 900, fontSize: 20, mb: 1 }}>What This Lab Shows</Typography>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: 'repeat(3, 1fr)' }, gap: 1.5 }}>
          <LearningNote title="What is Ruptures?" body="Ruptures is a change-point detection library. In Ops Signals it helps find the moment a metric moves from one stable baseline to another." />
          <LearningNote title="What data is generated?" body="The lab creates timestamped metric values with a known before/after baseline. The vertical marker is the generated change point." />
          <LearningNote title="How to read results" body="Compare the generated change point with the detected one. A small distance means the analyzer found the right structural change." />
        </Box>
        <Box sx={{ mt: 2, p: 2, border: `1px solid ${ui.border}`, borderRadius: 2, bgcolor: 'var(--os-surface-alt)' }}>
          <Typography sx={{ fontWeight: 900, mb: 1 }}>How This Lab Helps</Typography>
          <Typography sx={{ color: ui.muted, lineHeight: 1.6 }}>
            Use this lab to learn when a sustained baseline shift should become a finding. It separates generated truth,
            ruptures detection, and Ops Signals thresholds such as minimum change percent and effect size.
          </Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 1.5 }}>
            <Chip size="small" label="1. Generate baseline shift" />
            <Chip size="small" label="2. Tune thresholds" />
            <Chip size="small" label="3. Check change-point error" />
            <Chip size="small" label="4. Validate finding creation" />
          </Stack>
        </Box>
      </WorkspacePanel>

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Stack direction="row" alignItems="center" spacing={1.2} sx={{ mb: 2 }}>
          <TimelineRoundedIcon sx={{ color: 'var(--os-ink-brand)' }} />
          <Typography sx={{ fontWeight: 900, fontSize: 20 }}>Generate Time Series</Typography>
        </Stack>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(4, 1fr)' }, gap: 1.5 }}>
          <TextField select size="small" label="Pattern" value={pattern} onChange={(event) => { setPattern(event.target.value as Pattern); setResult(null); }}>
            {PATTERNS.map((item) => <MenuItem key={item.value} value={item.value}>{item.label}</MenuItem>)}
          </TextField>
          <TextField size="small" label="Samples" type="number" value={samples} onChange={(event) => { setSamples(Math.max(30, Number(event.target.value))); setResult(null); }} />
          <TextField size="small" label="Interval" value={interval} onChange={(event) => { setInterval(event.target.value); setResult(null); }} />
          <TextField size="small" label="Seed" type="number" value={seed} onChange={(event) => { setSeed(Number(event.target.value)); setResult(null); }} />
          <TextField size="small" label="Baseline" type="number" value={baseline} onChange={(event) => { setBaseline(Number(event.target.value)); setResult(null); }} />
          <TextField size="small" label="Shift %" type="number" value={shiftPercent} onChange={(event) => { setShiftPercent(Number(event.target.value)); setResult(null); }} />
          <TextField size="small" label="Noise" type="number" value={noise} onChange={(event) => { setNoise(Math.max(0, Number(event.target.value))); setResult(null); }} />
          <TextField size="small" label="Change point" type="number" value={changePoint} onChange={(event) => { setChangePoint(Number(event.target.value)); setResult(null); }} />
        </Box>
      </WorkspacePanel>

      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: '1.45fr 0.85fr' }, gap: 2 }}>
        <WorkspacePanel sx={{ p: 2.5 }}>
          <Typography sx={{ fontWeight: 900, fontSize: 20, mb: 0.5 }}>Understand Data</Typography>
          <Typography sx={{ color: ui.muted, mb: 2 }}>{currentPattern?.explanation}</Typography>
          <Box sx={{ height: 320 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--os-border)" />
                <XAxis dataKey="time" tickLine={false} axisLine={false} minTickGap={24} />
                <YAxis tickLine={false} axisLine={false} width={46} />
                <Tooltip />
                <Line type="monotone" dataKey="value" stroke="#009688" dot={false} strokeWidth={2.2} />
                <ReferenceLine x={chartData[boundedChangePoint]?.time} stroke={ui.red} strokeDasharray="5 5" label="expected" />
                {detectedIndex !== null && chartData[detectedIndex] ? <ReferenceLine x={chartData[detectedIndex].time} stroke={ui.purple} strokeDasharray="3 3" label="detected" /> : null}
              </LineChart>
            </ResponsiveContainer>
          </Box>
        </WorkspacePanel>

        <WorkspacePanel sx={{ p: 2.5 }}>
          <Typography sx={{ fontWeight: 900, fontSize: 20, mb: 1.5 }}>Generated Truth</Typography>
          <Stack spacing={1.2}>
            <ScoreTile label="Expected Change Point" value={boundedChangePoint} />
            <ScoreTile label="Before Mean" value={summary.beforeMean.toFixed(2)} />
            <ScoreTile label="After Mean" value={summary.afterMean.toFixed(2)} />
            <ScoreTile label="Generated Change" value={`${summary.percentChange.toFixed(1)}%`} />
          </Stack>
          <Alert severity="info" sx={{ mt: 2 }}>
            The generated change point is the known truth. Ruptures should detect a nearby sample when the shift is sustained and large enough.
          </Alert>
        </WorkspacePanel>
      </Box>

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Stack direction={{ xs: 'column', md: 'row' }} alignItems={{ xs: 'flex-start', md: 'center' }} justifyContent="space-between" spacing={2}>
          <Box>
            <Typography sx={{ fontWeight: 900, fontSize: 20 }}>Run Ruptures-Backed Analyzer</Typography>
            <Typography sx={{ color: ui.muted }}>Execution uses baseline_shift with ruptures params from analyzer overrides for this lab run only.</Typography>
          </Box>
          <Button startIcon={runMutation.isPending ? <CircularProgress size={18} color="inherit" /> : <PlayArrowRoundedIcon />} variant="contained" onClick={() => runMutation.mutate()} disabled={runMutation.isPending} sx={{ bgcolor: '#009688', textTransform: 'none', fontWeight: 850 }}>
            Run Analyzer
          </Button>
        </Stack>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(4, 1fr)' }, gap: 1.5, mt: 2 }}>
          <TextField size="small" label="Min change %" type="number" value={thresholdPercent} onChange={(event) => setThresholdPercent(Math.max(0, Number(event.target.value)))} helperText={<RunsUse analyzer={inUse} path="finding_rules.min_change_percent" value={thresholdPercent} onReset={(value) => setThresholdPercent(Number(value))} />} />
          <TextField size="small" label="Effect threshold" type="number" value={changeThreshold} onChange={(event) => setChangeThreshold(Math.max(0.1, Number(event.target.value)))} helperText={<RunsUse analyzer={inUse} path="finding_rules.min_effect_size" value={changeThreshold} onReset={(value) => setChangeThreshold(Number(value))} />} />
          <TextField size="small" label="Min segment size" type="number" value={minSegmentSize} onChange={(event) => setMinSegmentSize(Math.max(2, Number(event.target.value)))} helperText={<RunsUse analyzer={inUse} path="ruptures.min_size" value={minSegmentSize} onReset={(value) => setMinSegmentSize(Number(value))} />} />
          <TextField size="small" label="Jump" type="number" value={jump} onChange={(event) => setJump(Math.max(1, Number(event.target.value)))} helperText={<RunsUse analyzer={inUse} path="ruptures.jump" value={jump} onReset={(value) => setJump(Number(value))} />} />
        </Box>
        <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 2 }}>
          <Chip label={`library ruptures`} />
          <Chip label={`algorithm ${BASELINE_CONFIG.ruptures.algorithm}`} />
          <Chip label={`model ${BASELINE_CONFIG.ruptures.model}`} />
          <Chip label={`n_bkps ${BASELINE_CONFIG.ruptures.n_bkps}`} />
        </Stack>
        {error ? <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert> : null}
      </WorkspacePanel>

      {result ? (
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: '1fr 1fr' }, gap: 2 }}>
          <WorkspacePanel sx={{ p: 2.5 }}>
            <Typography sx={{ fontWeight: 900, fontSize: 20, mb: 1.5 }}>Execution Result</Typography>
            <Stack spacing={1.2}>
              <Chip sx={{ alignSelf: 'flex-start', fontWeight: 850 }} color={result.findings.length ? 'success' : 'default'} label={result.findings.length ? 'FINDING_CREATED' : 'NO_FINDING'} />
              <Typography sx={{ color: ui.text, fontWeight: 850 }}>{result.signals.length} signals, {result.findings.length} findings</Typography>
              <Typography sx={{ color: ui.muted }}>{decision?.routing_reason ?? decision?.explanation ?? 'Router explanation was not returned for this manual analyzer run.'}</Typography>
              {signal ? (
                <Box sx={{ borderTop: `1px solid ${ui.border}`, pt: 1 }}>
                  <Typography sx={{ fontWeight: 850 }}>{signal.summary}</Typography>
                  <Typography sx={{ color: ui.muted, fontSize: 13 }}>{signal.analyzer_id} • {signal.severity} • confidence {(signal.confidence ?? 0).toFixed(2)}</Typography>
                </Box>
              ) : (
                <Alert severity="warning">No baseline-shift signal was emitted. Try a larger shift, lower noise, lower thresholds, or more samples.</Alert>
              )}
            </Stack>
          </WorkspacePanel>

          <WorkspacePanel sx={{ p: 2.5 }}>
            <Typography sx={{ fontWeight: 900, fontSize: 20, mb: 1.5 }}>Expected vs Actual</Typography>
            <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 1.2, mb: 2 }}>
              <ScoreTile label="Expected Index" value={boundedChangePoint} />
              <ScoreTile label="Detected Index" value={detectedIndex === null ? 'n/a' : detectedIndex} />
              <ScoreTile label="Index Error" value={indexError === null ? 'n/a' : indexError} />
              <ScoreTile label="Within Tolerance" value={withinTolerance ? 'yes' : 'no'} />
              <ScoreTile label="Detected Change" value={detectedPercent === null ? 'n/a' : `${detectedPercent.toFixed(1)}%`} />
              <ScoreTile label="Finding" value={result.findings.length ? 'yes' : 'no'} />
            </Box>
            <Alert severity={withinTolerance ? 'success' : 'info'}>
              {withinTolerance
                ? 'The detected change point is close to the generated truth.'
                : 'A failed or distant match usually means the shift is too small, too noisy, too close to the edge, or blocked by thresholds.'}
            </Alert>
          </WorkspacePanel>
        </Box>
      ) : null}

      <AnalyzerLabConfigPanel
        analyzerId="baseline_shift"
        labName="Ruptures Change Point Lab"
        values={values}
        yourFound={result ? result.findings.length > 0 : null}
        comparison={comparison}
        passFailStatus={passFailStatus}
        passFailReason={result ? `Expected finding: ${shouldFind ? 'yes' : 'no'} because generated change is ${summary.percentChange.toFixed(1)}% and min change is ${thresholdPercent}%. Actual finding: ${result.findings.length > 0 ? 'yes' : 'no'}.` : 'Run the analyzer to mark this lab run pass or fail.'}
        productionNote="you care about sustained baseline changes, deployments, configuration changes, traffic shifts, or regime changes rather than isolated single-point spikes."
      />

      <Button startIcon={<RefreshRoundedIcon />} onClick={() => { setSeed(seed + 1); setResult(null); }} sx={{ alignSelf: 'flex-start', textTransform: 'none', fontWeight: 850 }}>
        Generate New Seed
      </Button>
    </Stack>
  );
}

function LearningNote({ title, body }: { title: string; body: string }) {
  return (
    <Card variant="outlined" sx={{ height: '100%' }}>
      <CardContent>
        <Typography sx={{ fontWeight: 900, mb: 0.8 }}>{title}</Typography>
        <Typography sx={{ color: ui.muted, fontSize: 14, lineHeight: 1.55 }}>{body}</Typography>
      </CardContent>
    </Card>
  );
}

function ScoreTile({ label, value }: { label: string; value: number | string }) {
  return (
    <Card variant="outlined">
      <CardContent sx={{ p: 1.4, '&:last-child': { pb: 1.4 } }}>
        <Typography sx={{ color: ui.muted, fontSize: 12, fontWeight: 800 }}>{label}</Typography>
        <Typography sx={{ fontWeight: 900, fontSize: 22 }}>{value}</Typography>
      </CardContent>
    </Card>
  );
}
