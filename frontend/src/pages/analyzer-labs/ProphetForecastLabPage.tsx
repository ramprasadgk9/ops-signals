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
import { analyzerConfigYaml, passFailFromFinding } from './labConfig';

type Pattern = 'forecast_breakout' | 'forecast_drop' | 'seasonal_normal' | 'noisy_forecast';

type GeneratedPoint = {
  index: number;
  timestamp: string;
  value: number;
  injected_deviation: boolean;
};

const PATTERNS: Array<{ value: Pattern; label: string; explanation: string }> = [
  { value: 'forecast_breakout', label: 'Forecast breakout', explanation: 'The metric follows a predictable wave, then ends above the expected path.' },
  { value: 'forecast_drop', label: 'Forecast drop', explanation: 'The metric follows a predictable wave, then ends below the expected path.' },
  { value: 'seasonal_normal', label: 'Seasonal normal', explanation: 'The metric follows a recurring seasonal path with no injected final deviation.' },
  { value: 'noisy_forecast', label: 'Noisy forecast', explanation: 'The expected path exists, but noise makes the final forecast comparison less clean.' },
];

const PROPHET_CONFIG = {
  implementation: {
    library: 'prophet',
    horizon_points: 10,
    changepoint_prior_scale: 0.05,
    uncertainty_threshold: 0.15,
  },
  finding_rules: {
    min_relative_error: 0.25,
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

function generateSeries(input: {
  pattern: Pattern;
  samples: number;
  interval: string;
  seed: number;
  baseline: number;
  amplitude: number;
  trend: number;
  noise: number;
  deviationPercent: number;
}) {
  const random = seededRandom(input.seed);
  const intervalMs = parseIntervalMs(input.interval);
  const start = new Date(Date.UTC(2026, 7, 24, 0, 0, 0));
  const noisy = input.pattern === 'noisy_forecast';
  const direction = input.pattern === 'forecast_drop' ? -1 : 1;
  const deviationStart = Math.max(8, input.samples - PROPHET_CONFIG.implementation.horizon_points);

  return Array.from({ length: input.samples }, (_, index): GeneratedPoint => {
    const seasonal = Math.sin((index / 24) * Math.PI * 2) * input.amplitude;
    const expected = input.baseline + seasonal + input.trend * index;
    const shouldDeviate = ['forecast_breakout', 'forecast_drop', 'noisy_forecast'].includes(input.pattern) && index >= deviationStart;
    const deviation = shouldDeviate ? direction * input.baseline * (input.deviationPercent / 100) : 0;
    const noise = gaussian(random) * input.noise * (noisy ? 2.5 : 1);
    return {
      index,
      timestamp: new Date(start.getTime() + index * intervalMs).toISOString(),
      value: Number((expected + deviation + noise).toFixed(3)),
      injected_deviation: shouldDeviate,
    };
  });
}

function toCsv(points: GeneratedPoint[]) {
  return [
    'timestamp,metric_name,value,service,injected_deviation',
    ...points.map((point) => `${point.timestamp},synthetic_prophet_value,${point.value},prophet-lab,${point.injected_deviation}`),
  ].join('\n');
}

function prophetSignal(result: CsvValidationResult | null): ValidationSignal | undefined {
  return result?.signals.find((signal) => signal.analyzer_id === 'prophet');
}

function routerDecision(result: CsvValidationResult | null) {
  return ((result?.analyzer_routing ?? []) as CsvAnalyzerRoutingDecision[]).find((decision) => decision.analyzer_id === 'prophet');
}

function numberEvidence(signal: ValidationSignal | undefined, key: string) {
  const value = signal?.evidence?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function ProphetForecastLabPage() {
  const [pattern, setPattern] = useState<Pattern>('forecast_breakout');
  const [samples, setSamples] = useState(168);
  const [interval, setInterval] = useState('5m');
  const [seed, setSeed] = useState(19);
  const [baseline, setBaseline] = useState(100);
  const [amplitude, setAmplitude] = useState(12);
  const [trend, setTrend] = useState(0.03);
  const [noise, setNoise] = useState(1.5);
  const [deviationPercent, setDeviationPercent] = useState(35);
  const [horizonPoints, setHorizonPoints] = useState(PROPHET_CONFIG.implementation.horizon_points);
  const [changepointPriorScale, setChangepointPriorScale] = useState(PROPHET_CONFIG.implementation.changepoint_prior_scale);
  const [uncertaintyThreshold, setUncertaintyThreshold] = useState(PROPHET_CONFIG.implementation.uncertainty_threshold);
  const [minRelativeError, setMinRelativeError] = useState(PROPHET_CONFIG.finding_rules.min_relative_error);
  const [result, setResult] = useState<CsvValidationResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const points = useMemo(
    () => generateSeries({ pattern, samples, interval, seed, baseline, amplitude, trend, noise, deviationPercent }),
    [amplitude, baseline, deviationPercent, interval, noise, pattern, samples, seed, trend],
  );
  const chartData = points.map((point) => ({ ...point, time: new Date(point.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }));
  const deviationStart = points.find((point) => point.injected_deviation)?.index ?? null;
  const signal = prophetSignal(result);
  const decision = routerDecision(result);
  const relativeError = numberEvidence(signal, 'relative_error');
  const forecastValue = numberEvidence(signal, 'forecast_value');
  const actualValue = numberEvidence(signal, 'actual_value');
  const confidence = signal?.confidence ?? null;
  const ruleMatched = signal?.evidence?.finding_rule_matched === true;
  const currentPattern = PATTERNS.find((item) => item.value === pattern);
  const implementation = {
    ...PROPHET_CONFIG.implementation,
    horizon_points: horizonPoints,
    changepoint_prior_scale: changepointPriorScale,
    uncertainty_threshold: uncertaintyThreshold,
  };
  const findingRules = { min_relative_error: minRelativeError };
  const shouldFind = (relativeError ?? 0) >= minRelativeError;
  const passFailStatus = result ? passFailFromFinding(shouldFind, result.findings.length > 0) : 'unknown';
  const yamlText = analyzerConfigYaml('prophet', {
    enabled: true,
    implementation,
    finding_rules: findingRules,
  });

  const runMutation = useMutation({
    mutationFn: async () => {
      const form = new FormData();
      form.set('file', new File([toCsv(points)], 'prophet-forecast-lab.csv', { type: 'text/csv' }));
      form.set('provider', 'generic');
      form.set('analyzer_id', 'prophet');
      form.set('service', 'prophet-lab');
      form.set('metric_name', 'synthetic_prophet_value');
      form.set('interval', interval);
      form.set('analyzer_overrides', JSON.stringify({
        prophet: {
          implementation: {
            ...PROPHET_CONFIG.implementation,
            horizon_points: horizonPoints,
            changepoint_prior_scale: changepointPriorScale,
            uncertainty_threshold: uncertaintyThreshold,
          },
          finding_rules: {
            min_relative_error: minRelativeError,
          },
        },
      }));
      return api.runCsvValidation(form);
    },
    onSuccess: (nextResult) => {
      setError(null);
      setResult(nextResult);
    },
    onError: (err: unknown) => {
      setResult(null);
      setError(err instanceof Error ? err.message : 'Prophet lab execution failed');
    },
  });

  return (
    <Stack spacing={3}>
      <PageHeader title="Prophet Forecast Lab" subtitle="Generate predictable series, inject forecast deviations, run Prophet, and decide when forecast misses become findings." />

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Typography sx={{ fontWeight: 900, fontSize: 20, mb: 1 }}>What This Lab Shows</Typography>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: 'repeat(3, 1fr)' }, gap: 1.5 }}>
          <LearningNote title="What is Prophet?" body="Prophet forecasts the expected path of a metric. In Ops Signals, it helps identify when recent values move away from that expected path." />
          <LearningNote title="What data is generated?" body="The lab creates a predictable seasonal series, then optionally injects a final breakout or drop so you know the expected forecast violation." />
          <LearningNote title="How to read results" body="Compare actual value, forecast value, relative error, confidence, and whether the configured finding rule matched." />
        </Box>
        <Box sx={{ mt: 2, p: 2, border: `1px solid ${ui.border}`, borderRadius: 2, bgcolor: '#f8fafc' }}>
          <Typography sx={{ fontWeight: 900, mb: 1 }}>How This Lab Helps</Typography>
          <Typography sx={{ color: ui.muted, lineHeight: 1.6 }}>
            Use this lab to understand forecast-based anomalies: when a metric still has a normal-looking shape, but its latest values
            are too far above or below the expected path. Findings are created when relative error crosses the configured rule.
          </Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 1.5 }}>
            <Chip size="small" label="1. Generate expected path" />
            <Chip size="small" label="2. Inject deviation" />
            <Chip size="small" label="3. Tune relative error" />
            <Chip size="small" label="4. Validate finding rule" />
          </Stack>
        </Box>
      </WorkspacePanel>

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Stack direction="row" alignItems="center" spacing={1.2} sx={{ mb: 2 }}>
          <TimelineRoundedIcon sx={{ color: '#0f766e' }} />
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
          <TextField size="small" label="Amplitude" type="number" value={amplitude} onChange={(event) => { setAmplitude(Math.max(0, Number(event.target.value))); setResult(null); }} />
          <TextField size="small" label="Trend / point" type="number" value={trend} onChange={(event) => { setTrend(Number(event.target.value)); setResult(null); }} />
          <TextField size="small" label="Deviation %" type="number" value={deviationPercent} onChange={(event) => { setDeviationPercent(Math.max(0, Number(event.target.value))); setResult(null); }} />
        </Box>
      </WorkspacePanel>

      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: '1.45fr 0.85fr' }, gap: 2 }}>
        <WorkspacePanel sx={{ p: 2.5 }}>
          <Typography sx={{ fontWeight: 900, fontSize: 20, mb: 0.5 }}>Understand Data</Typography>
          <Typography sx={{ color: ui.muted, mb: 2 }}>{currentPattern?.explanation}</Typography>
          <Box sx={{ height: 320 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="time" tickLine={false} axisLine={false} minTickGap={24} />
                <YAxis tickLine={false} axisLine={false} width={46} />
                <Tooltip />
                <Line type="monotone" dataKey="value" stroke="#009688" dot={false} strokeWidth={2.2} />
                {deviationStart !== null && chartData[deviationStart] ? <ReferenceLine x={chartData[deviationStart].time} stroke={ui.red} strokeDasharray="5 5" label="deviation" /> : null}
              </LineChart>
            </ResponsiveContainer>
          </Box>
        </WorkspacePanel>

        <WorkspacePanel sx={{ p: 2.5 }}>
          <Typography sx={{ fontWeight: 900, fontSize: 20, mb: 1.5 }}>Generated Truth</Typography>
          <Stack spacing={1.2}>
            <ScoreTile label="Deviation Injected" value={deviationStart === null ? 'no' : 'yes'} />
            <ScoreTile label="Deviation Start" value={deviationStart === null ? 'none' : deviationStart} />
            <ScoreTile label="Deviation %" value={`${deviationPercent}%`} />
            <ScoreTile label="Horizon Points" value={horizonPoints} />
          </Stack>
          <Alert severity="info" sx={{ mt: 2 }}>
            Prophet compares recent actual values against an expected path. The finding rule decides when that miss is important enough.
          </Alert>
        </WorkspacePanel>
      </Box>

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Stack direction={{ xs: 'column', md: 'row' }} alignItems={{ xs: 'flex-start', md: 'center' }} justifyContent="space-between" spacing={2}>
          <Box>
            <Typography sx={{ fontWeight: 900, fontSize: 20 }}>Run Prophet Analyzer</Typography>
            <Typography sx={{ color: ui.muted }}>Execution uses the existing CSV validation pipeline with Prophet overrides for this lab run only.</Typography>
          </Box>
          <Button startIcon={runMutation.isPending ? <CircularProgress size={18} color="inherit" /> : <PlayArrowRoundedIcon />} variant="contained" onClick={() => runMutation.mutate()} disabled={runMutation.isPending} sx={{ bgcolor: '#009688', textTransform: 'none', fontWeight: 850 }}>
            Run Analyzer
          </Button>
        </Stack>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(4, 1fr)' }, gap: 1.5, mt: 2 }}>
          <TextField size="small" label="Horizon points" type="number" value={horizonPoints} onChange={(event) => setHorizonPoints(Math.max(3, Number(event.target.value)))} />
          <TextField size="small" label="Changepoint prior" type="number" value={changepointPriorScale} onChange={(event) => setChangepointPriorScale(Math.max(0.001, Number(event.target.value)))} />
          <TextField size="small" label="Uncertainty threshold" type="number" value={uncertaintyThreshold} onChange={(event) => setUncertaintyThreshold(Math.max(0.01, Number(event.target.value)))} />
          <TextField size="small" label="Min relative error" type="number" value={minRelativeError} onChange={(event) => setMinRelativeError(Math.max(0, Number(event.target.value)))} />
        </Box>
        <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 2 }}>
          <Chip label="library prophet" />
          <Chip label={`horizon ${horizonPoints}`} />
          <Chip label={`min relative error ${minRelativeError}`} />
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
                <Alert severity="warning">No Prophet signal was emitted. Try more samples, a stronger final deviation, or lower thresholds.</Alert>
              )}
            </Stack>
          </WorkspacePanel>

          <WorkspacePanel sx={{ p: 2.5 }}>
            <Typography sx={{ fontWeight: 900, fontSize: 20, mb: 1.5 }}>Expected vs Actual</Typography>
            <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 1.2, mb: 2 }}>
              <ScoreTile label="Forecast Value" value={forecastValue === null ? 'n/a' : forecastValue.toFixed(2)} />
              <ScoreTile label="Actual Value" value={actualValue === null ? 'n/a' : actualValue.toFixed(2)} />
              <ScoreTile label="Relative Error" value={relativeError === null ? 'n/a' : `${(relativeError * 100).toFixed(1)}%`} />
              <ScoreTile label="Confidence" value={confidence === null ? 'n/a' : confidence.toFixed(2)} />
              <ScoreTile label="Rule Matched" value={ruleMatched ? 'yes' : 'no'} />
              <ScoreTile label="Finding" value={result.findings.length ? 'yes' : 'no'} />
            </Box>
            <Alert severity={ruleMatched ? 'success' : 'info'}>
              {ruleMatched
                ? 'The forecast miss met the configured relative-error rule.'
                : 'A non-matching rule usually means the forecast miss is too small for a finding.'}
            </Alert>
          </WorkspacePanel>
        </Box>
      ) : null}

      <AnalyzerLabConfigPanel
        analyzerId="prophet"
        labName="Prophet Forecast Lab"
        yamlText={yamlText}
        implementation={implementation}
        findingRules={findingRules}
        passFailStatus={passFailStatus}
        passFailReason={result ? `Expected finding: ${shouldFind ? 'yes' : 'no'} because relative error is ${relativeError === null ? 'n/a' : `${(relativeError * 100).toFixed(1)}%`} and min relative error is ${(minRelativeError * 100).toFixed(1)}%. Actual finding: ${result.findings.length > 0 ? 'yes' : 'no'}.` : 'Run the analyzer to mark this lab run pass or fail.'}
        productionNote="the metric has recurring or forecastable behavior and you want findings when recent actual values drift meaningfully away from the expected path."
        benchmarkSummary={result ? { forecast_value: forecastValue, actual_value: actualValue, relative_error: relativeError, rule_matched: ruleMatched } : {}}
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
