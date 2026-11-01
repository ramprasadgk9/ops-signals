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
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../../api/queries';
import { PageHeader, WorkspacePanel } from '../../standalone/components';
import { ui } from '../../standalone/theme';
import type { CsvAnalyzerRoutingDecision, CsvValidationResult, ValidationSignal } from '../../types';
import { AnalyzerLabConfigPanel } from './AnalyzerLabConfigPanel';
import { passFailFromFinding } from './labConfig';
import { LabSandboxBanner, RunsUse, useAnalyzerInUse, useInUseComparison } from './labSettings';
import { labChanges } from '../../utils/analyzerSettings';

type Pattern = 'steady_up' | 'steady_down' | 'weak_trend' | 'noisy_trend' | 'flat';

type GeneratedPoint = {
  index: number;
  timestamp: string;
  value: number;
};

const PATTERNS: Array<{ value: Pattern; label: string; explanation: string }> = [
  { value: 'steady_up', label: 'Steady up', explanation: 'The metric gradually rises across the whole window.' },
  { value: 'steady_down', label: 'Steady down', explanation: 'The metric gradually falls across the whole window.' },
  { value: 'weak_trend', label: 'Weak trend', explanation: 'The metric moves only slightly, often below the finding threshold.' },
  { value: 'noisy_trend', label: 'Noisy trend', explanation: 'The metric has a direction, but variance makes the fit less clean.' },
  { value: 'flat', label: 'Flat', explanation: 'The metric stays near one level. Trend should avoid creating a finding.' },
];

const TREND_CONFIG = {
  implementation: {
    library: 'statsmodels',
    model: 'OLS',
  },
  finding_rules: {
    min_slope_percent: 10,
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

function trendPercentFor(pattern: Pattern, trendPercent: number) {
  if (pattern === 'flat') return 0;
  if (pattern === 'weak_trend') return Math.min(Math.abs(trendPercent), 6);
  if (pattern === 'steady_down') return -Math.abs(trendPercent);
  return Math.abs(trendPercent);
}

function generateSeries(input: {
  pattern: Pattern;
  samples: number;
  interval: string;
  seed: number;
  baseline: number;
  trendPercent: number;
  noise: number;
}) {
  const random = seededRandom(input.seed);
  const intervalMs = parseIntervalMs(input.interval);
  const start = new Date(Date.UTC(2026, 7, 24, 0, 0, 0));
  const effectiveTrend = trendPercentFor(input.pattern, input.trendPercent);
  const endDelta = input.baseline * (effectiveTrend / 100);
  const noisy = input.pattern === 'noisy_trend';

  return Array.from({ length: input.samples }, (_, index): GeneratedPoint => {
    const progress = input.samples <= 1 ? 0 : index / (input.samples - 1);
    const value = input.baseline + endDelta * progress + gaussian(random) * input.noise * (noisy ? 3 : 1);
    return {
      index,
      timestamp: new Date(start.getTime() + index * intervalMs).toISOString(),
      value: Number(value.toFixed(3)),
    };
  });
}

function toCsv(points: GeneratedPoint[]) {
  return [
    'timestamp,metric_name,value,service',
    ...points.map((point) => `${point.timestamp},synthetic_trend_value,${point.value},trend-lab`),
  ].join('\n');
}

function generatedSlopePercent(points: GeneratedPoint[]) {
  const first = points[0]?.value ?? 0;
  const last = points[points.length - 1]?.value ?? first;
  return ((last - first) / Math.max(Math.abs(first), 1e-9)) * 100;
}

function trendSignal(result: CsvValidationResult | null): ValidationSignal | undefined {
  return result?.signals.find((signal) => signal.analyzer_id === 'trend');
}

function routerDecision(result: CsvValidationResult | null) {
  return ((result?.analyzer_routing ?? []) as CsvAnalyzerRoutingDecision[]).find((decision) => decision.analyzer_id === 'trend_regression' || decision.analyzer_id === 'trend');
}

function numberEvidence(signal: ValidationSignal | undefined, key: string) {
  const value = signal?.evidence?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function TrendLabPage() {
  const [pattern, setPattern] = useState<Pattern>('steady_up');
  const [samples, setSamples] = useState(120);
  const [interval, setInterval] = useState('5m');
  const [seed, setSeed] = useState(31);
  const [baseline, setBaseline] = useState(100);
  const [trendPercent, setTrendPercent] = useState(30);
  const [noise, setNoise] = useState(1.2);
  const [minSlopePercent, setMinSlopePercent] = useState(TREND_CONFIG.finding_rules.min_slope_percent);
  const [result, setResult] = useState<CsvValidationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { analyzer: inUse } = useAnalyzerInUse('trend');
  const { comparison, compare } = useInUseComparison();

  const points = useMemo(
    () => generateSeries({ pattern, samples, interval, seed, baseline, trendPercent, noise }),
    [baseline, interval, noise, pattern, samples, seed, trendPercent],
  );
  const chartData = points.map((point) => ({ ...point, time: new Date(point.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }));
  const expectedSlope = generatedSlopePercent(points);
  const signal = trendSignal(result);
  const decision = routerDecision(result);
  const detectedSlope = numberEvidence(signal, 'slope_percent');
  const rSquared = numberEvidence(signal, 'r_squared');
  const pValue = numberEvidence(signal, 'p_value');
  const confidence = signal?.confidence ?? null;
  const ruleMatched = signal?.evidence?.finding_rule_matched === true;
  const currentPattern = PATTERNS.find((item) => item.value === pattern);
  const implementation = TREND_CONFIG.implementation;
  const findingRules = { min_slope_percent: minSlopePercent };
  const shouldFind = Math.abs(expectedSlope) >= minSlopePercent;
  const passFailStatus = result ? passFailFromFinding(shouldFind, result.findings.length > 0) : 'unknown';
  const values = { implementation, finding_rules: findingRules };
  const hasChanges = labChanges(inUse, values).length > 0;

  const runMutation = useMutation({
    mutationFn: async () => {
      const form = new FormData();
      form.set('file', new File([toCsv(points)], 'trend-lab.csv', { type: 'text/csv' }));
      form.set('provider', 'generic');
      form.set('analyzer_id', 'trend');
      form.set('service', 'trend-lab');
      form.set('metric_name', 'synthetic_trend_value');
      form.set('interval', interval);
      form.set('analyzer_overrides', JSON.stringify({
        trend: {
          implementation: TREND_CONFIG.implementation,
          finding_rules: {
            min_slope_percent: minSlopePercent,
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
      setError(err instanceof Error ? err.message : 'Trend lab execution failed');
    },
  });

  return (
    <Stack spacing={3}>
      <PageHeader title="Trend Lab" subtitle="Generate directional time-series data, run Trend Regression, and decide when slope becomes a finding." />
      <LabSandboxBanner analyzerId="trend" paths={['finding_rules.min_slope_percent']} />

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Typography sx={{ fontWeight: 900, fontSize: 20, mb: 1 }}>What This Lab Shows</Typography>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: 'repeat(3, 1fr)' }, gap: 1.5 }}>
          <LearningNote title="What is Trend Regression?" body="Trend Regression fits a straight line through the metric values and asks whether the overall direction is meaningful." />
          <LearningNote title="What data is generated?" body="The lab creates a baseline metric and applies a gradual increase, decrease, weak trend, noisy trend, or flat behavior." />
          <LearningNote title="How to read results" body="Compare generated slope with detected slope. A finding is created when absolute slope percent crosses the configured rule." />
        </Box>
        <Box sx={{ mt: 2, p: 2, border: `1px solid ${ui.border}`, borderRadius: 2, bgcolor: 'var(--os-surface-alt)' }}>
          <Typography sx={{ fontWeight: 900, mb: 1 }}>How This Lab Helps</Typography>
          <Typography sx={{ color: ui.muted, lineHeight: 1.6 }}>
            Use this lab to validate slow-moving changes such as steady CPU growth, latency drift, memory pressure, or traffic decline.
            It separates generated trend truth, Trend Regression detection, and whether Ops Signals should create a trend finding.
          </Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 1.5 }}>
            <Chip size="small" label="1. Generate slope" />
            <Chip size="small" label="2. Add noise" />
            <Chip size="small" label="3. Tune min slope" />
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
          <TextField size="small" label="Samples" type="number" value={samples} onChange={(event) => { setSamples(Math.max(10, Number(event.target.value))); setResult(null); }} />
          <TextField size="small" label="Interval" value={interval} onChange={(event) => { setInterval(event.target.value); setResult(null); }} />
          <TextField size="small" label="Seed" type="number" value={seed} onChange={(event) => { setSeed(Number(event.target.value)); setResult(null); }} />
          <TextField size="small" label="Baseline" type="number" value={baseline} onChange={(event) => { setBaseline(Number(event.target.value)); setResult(null); }} />
          <TextField size="small" label="Trend %" type="number" value={trendPercent} onChange={(event) => { setTrendPercent(Math.max(0, Number(event.target.value))); setResult(null); }} />
          <TextField size="small" label="Noise" type="number" value={noise} onChange={(event) => { setNoise(Math.max(0, Number(event.target.value))); setResult(null); }} />
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
              </LineChart>
            </ResponsiveContainer>
          </Box>
        </WorkspacePanel>

        <WorkspacePanel sx={{ p: 2.5 }}>
          <Typography sx={{ fontWeight: 900, fontSize: 20, mb: 1.5 }}>Generated Truth</Typography>
          <Stack spacing={1.2}>
            <ScoreTile label="Generated Slope" value={`${expectedSlope.toFixed(1)}%`} />
            <ScoreTile label="Baseline" value={baseline} />
            <ScoreTile label="Samples" value={samples} />
            <ScoreTile label="Noise" value={noise} />
          </Stack>
          <Alert severity="info" sx={{ mt: 2 }}>
            The generated slope is the rough start-to-end change. Trend Regression estimates slope using all points.
          </Alert>
        </WorkspacePanel>
      </Box>

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Stack direction={{ xs: 'column', md: 'row' }} alignItems={{ xs: 'flex-start', md: 'center' }} justifyContent="space-between" spacing={2}>
          <Box>
            <Typography sx={{ fontWeight: 900, fontSize: 20 }}>Run Trend Analyzer</Typography>
            <Typography sx={{ color: ui.muted }}>Execution uses the existing CSV validation pipeline with Trend Regression overrides for this lab run only.</Typography>
          </Box>
          <Button startIcon={runMutation.isPending ? <CircularProgress size={18} color="inherit" /> : <PlayArrowRoundedIcon />} variant="contained" onClick={() => runMutation.mutate()} disabled={runMutation.isPending} sx={{ bgcolor: '#009688', textTransform: 'none', fontWeight: 850 }}>
            Run Analyzer
          </Button>
        </Stack>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(2, 1fr)' }, gap: 1.5, mt: 2 }}>
          <TextField size="small" label="Min slope %" type="number" value={minSlopePercent} onChange={(event) => setMinSlopePercent(Math.max(0, Number(event.target.value)))} helperText={<RunsUse analyzer={inUse} path="finding_rules.min_slope_percent" value={minSlopePercent} onReset={(value) => setMinSlopePercent(Number(value))} />} />
        </Box>
        <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 2 }}>
          <Chip label={`library ${TREND_CONFIG.implementation.library}`} />
          <Chip label={`model ${TREND_CONFIG.implementation.model}`} />
          <Chip label={`min slope ${minSlopePercent}%`} />
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
                  <Typography sx={{ color: ui.muted, fontSize: 13 }}>{signal.analyzer_id} • {signal.severity} • confidence {signal.confidence.toFixed(2)}</Typography>
                </Box>
              ) : (
                <Alert severity="warning">No trend signal was emitted. Try a stronger trend, lower noise, lower min slope, or more samples.</Alert>
              )}
            </Stack>
          </WorkspacePanel>

          <WorkspacePanel sx={{ p: 2.5 }}>
            <Typography sx={{ fontWeight: 900, fontSize: 20, mb: 1.5 }}>Expected vs Actual</Typography>
            <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 1.2, mb: 2 }}>
              <ScoreTile label="Generated Slope" value={`${expectedSlope.toFixed(1)}%`} />
              <ScoreTile label="Detected Slope" value={detectedSlope === null ? 'n/a' : `${detectedSlope.toFixed(1)}%`} />
              <ScoreTile label="Min Slope Rule" value={`${minSlopePercent}%`} />
              <ScoreTile label="R Squared" value={rSquared === null ? 'n/a' : rSquared.toFixed(2)} />
              <ScoreTile label="P Value" value={pValue === null ? 'n/a' : pValue.toFixed(4)} />
              <ScoreTile label="Finding" value={result.findings.length ? 'yes' : 'no'} />
            </Box>
            <Alert severity={ruleMatched ? 'success' : 'info'}>
              {ruleMatched
                ? 'The detected slope crossed the configured min-slope finding rule.'
                : 'A non-matching rule usually means the directional change is too small or too noisy for a trend finding.'}
            </Alert>
          </WorkspacePanel>
        </Box>
      ) : null}

      <AnalyzerLabConfigPanel
        analyzerId="trend"
        labName="Trend Lab"
        values={values}
        yourFound={result ? result.findings.length > 0 : null}
        comparison={comparison}
        passFailStatus={passFailStatus}
        passFailReason={result ? `Expected finding: ${shouldFind ? 'yes' : 'no'} because generated slope is ${expectedSlope.toFixed(1)}% and min slope is ${minSlopePercent}%. Actual finding: ${result.findings.length > 0 ? 'yes' : 'no'}.` : 'Run the analyzer to mark this lab run pass or fail.'}
        productionNote="you care about sustained directional movement across the whole window, such as latency slowly rising or traffic steadily falling."
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
