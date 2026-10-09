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
import ScienceRoundedIcon from '@mui/icons-material/ScienceRounded';
import { useMutation } from '@tanstack/react-query';
import { CartesianGrid, Line, LineChart, ReferenceDot, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../../api/queries';
import { PageHeader, WorkspacePanel } from '../../standalone/components';
import { ui } from '../../standalone/theme';
import type { CsvAnalyzerRoutingDecision, CsvValidationResult, ValidationSignal } from '../../types';
import { AnalyzerLabConfigPanel } from './AnalyzerLabConfigPanel';
import { analyzerConfigYaml, passFailFromFinding } from './labConfig';

type Pattern = 'clean' | 'spikes' | 'drops' | 'spikes_and_drops' | 'too_small';

type GeneratedPoint = {
  index: number;
  timestamp: string;
  value: number;
  is_anomaly: boolean;
  anomaly_type: string;
};

const PATTERNS: Array<{ value: Pattern; label: string; explanation: string }> = [
  { value: 'clean', label: 'Clean baseline', explanation: 'Most values stay close to the mean. Z-score should avoid findings.' },
  { value: 'spikes', label: 'High spikes', explanation: 'A normal baseline with isolated values far above the usual range.' },
  { value: 'drops', label: 'Low drops', explanation: 'A normal baseline with isolated values far below the usual range.' },
  { value: 'spikes_and_drops', label: 'Spikes and drops', explanation: 'A normal baseline with both high and low unusual values.' },
  { value: 'too_small', label: 'Too small', explanation: 'Injected changes exist, but they are usually below the z-score threshold.' },
];

const ZSCORE_CONFIG = {
  implementation: {
    library: 'pandas',
    method: 'zscore',
    zscore_threshold: 3.0,
    grouping_gap: '15m',
  },
  finding_rules: {
    min_abs_zscore: 3.0,
    min_points: 1,
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
  mean: number;
  noise: number;
  anomalyCount: number;
  anomalyMagnitude: number;
}) {
  const random = seededRandom(input.seed);
  const intervalMs = parseIntervalMs(input.interval);
  const start = new Date(Date.UTC(2026, 7, 24, 0, 0, 0));
  const points: GeneratedPoint[] = Array.from({ length: input.samples }, (_, index) => ({
    index,
    timestamp: new Date(start.getTime() + index * intervalMs).toISOString(),
    value: Number((input.mean + gaussian(random) * input.noise).toFixed(3)),
    is_anomaly: false,
    anomaly_type: '',
  }));

  if (input.pattern !== 'clean') {
    const selected = new Set<number>();
    while (selected.size < Math.min(input.anomalyCount, Math.max(input.samples - 4, 0))) {
      selected.add(2 + Math.floor(random() * Math.max(input.samples - 4, 1)));
    }
    const magnitude = input.pattern === 'too_small' ? Math.min(input.anomalyMagnitude, 2.0) : input.anomalyMagnitude;
    Array.from(selected).forEach((index, order) => {
      const high = input.pattern === 'spikes' || (input.pattern === 'spikes_and_drops' && order % 2 === 0);
      const direction = high ? 1 : -1;
      points[index] = {
        ...points[index],
        value: Number((input.mean + direction * input.noise * magnitude).toFixed(3)),
        is_anomaly: true,
        anomaly_type: high ? 'spike' : 'drop',
      };
    });
  }

  return points;
}

function toCsv(points: GeneratedPoint[]) {
  return [
    'timestamp,metric_name,value,service,is_anomaly,anomaly_type',
    ...points.map((point) => `${point.timestamp},synthetic_zscore_value,${point.value},zscore-lab,${point.is_anomaly},${point.anomaly_type}`),
  ].join('\n');
}

function zscoreSignal(result: CsvValidationResult | null): ValidationSignal | undefined {
  return result?.signals.find((signal) => signal.analyzer_id === 'anomaly_zscore');
}

function routerDecision(result: CsvValidationResult | null) {
  return ((result?.analyzer_routing ?? []) as CsvAnalyzerRoutingDecision[]).find((decision) => decision.analyzer_id === 'adtk' || decision.analyzer_id === 'pyod');
}

function numberEvidence(signal: ValidationSignal | undefined, key: string) {
  const value = signal?.evidence?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function summary(points: GeneratedPoint[]) {
  const values = points.map((point) => point.value);
  const mean = values.reduce((sum, value) => sum + value, 0) / Math.max(values.length, 1);
  const variance = values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / Math.max(values.length, 1);
  return {
    mean,
    stddev: Math.sqrt(variance),
    anomalies: points.filter((point) => point.is_anomaly).length,
  };
}

export function ZScoreAnomalyLabPage() {
  const [pattern, setPattern] = useState<Pattern>('spikes');
  const [samples, setSamples] = useState(120);
  const [interval, setInterval] = useState('5m');
  const [seed, setSeed] = useState(41);
  const [mean, setMean] = useState(50);
  const [noise, setNoise] = useState(2);
  const [anomalyCount, setAnomalyCount] = useState(3);
  const [anomalyMagnitude, setAnomalyMagnitude] = useState(8);
  const [zscoreThreshold, setZscoreThreshold] = useState(ZSCORE_CONFIG.implementation.zscore_threshold);
  const [groupingGap, setGroupingGap] = useState(ZSCORE_CONFIG.implementation.grouping_gap);
  const [minAbsZscore, setMinAbsZscore] = useState(ZSCORE_CONFIG.finding_rules.min_abs_zscore);
  const [minPoints, setMinPoints] = useState(ZSCORE_CONFIG.finding_rules.min_points);
  const [result, setResult] = useState<CsvValidationResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const points = useMemo(
    () => generateSeries({ pattern, samples, interval, seed, mean, noise, anomalyCount, anomalyMagnitude }),
    [anomalyCount, anomalyMagnitude, interval, mean, noise, pattern, samples, seed],
  );
  const chartData = points.map((point) => ({ ...point, time: new Date(point.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }));
  const generated = summary(points);
  const signal = zscoreSignal(result);
  const decision = routerDecision(result);
  const maxAbsZscore = numberEvidence(signal, 'max_abs_zscore');
  const pointCount = numberEvidence(signal, 'point_count');
  const confidence = signal?.confidence ?? null;
  const ruleMatched = signal?.evidence?.finding_rule_matched === true;
  const currentPattern = PATTERNS.find((item) => item.value === pattern);
  const implementation = {
    ...ZSCORE_CONFIG.implementation,
    zscore_threshold: zscoreThreshold,
    grouping_gap: groupingGap,
  };
  const findingRules = {
    min_abs_zscore: minAbsZscore,
    min_points: minPoints,
  };
  const shouldFind = generated.anomalies >= minPoints && pattern !== 'clean' && pattern !== 'too_small';
  const passFailStatus = result ? passFailFromFinding(shouldFind, result.findings.length > 0) : 'unknown';
  const yamlText = analyzerConfigYaml('anomaly_zscore', {
    enabled: true,
    implementation,
    finding_rules: findingRules,
  });

  const runMutation = useMutation({
    mutationFn: async () => {
      const form = new FormData();
      form.set('file', new File([toCsv(points)], 'zscore-anomaly-lab.csv', { type: 'text/csv' }));
      form.set('provider', 'generic');
      form.set('analyzer_id', 'anomaly_zscore');
      form.set('service', 'zscore-lab');
      form.set('metric_name', 'synthetic_zscore_value');
      form.set('interval', interval);
      form.set('analyzer_overrides', JSON.stringify({
        anomaly_zscore: {
          implementation: {
            ...ZSCORE_CONFIG.implementation,
            zscore_threshold: zscoreThreshold,
            grouping_gap: groupingGap,
          },
          finding_rules: {
            min_abs_zscore: minAbsZscore,
            min_points: minPoints,
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
      setError(err instanceof Error ? err.message : 'Z-score lab execution failed');
    },
  });

  return (
    <Stack spacing={3}>
      <PageHeader title="Z-Score Anomaly Lab" subtitle="Generate unusual points, run anomaly_zscore, and decide when z-score groups become findings." />

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Typography sx={{ fontWeight: 900, fontSize: 20, mb: 1 }}>What This Lab Shows</Typography>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: 'repeat(3, 1fr)' }, gap: 1.5 }}>
          <LearningNote title="What is z-score?" body="A z-score says how far a value is from normal, measured in standard deviations. A value with z-score 3 is roughly three standard deviations away from the average." />
          <LearningNote title="What data is generated?" body="The lab creates a normal baseline around a mean, then optionally injects high spikes or low drops at known points." />
          <LearningNote title="How to read results" body="Compare generated anomalies with detected z-score groups. A finding is created when max z-score and grouped point count pass the rule." />
        </Box>
        <Box sx={{ mt: 2, p: 2, border: `1px solid ${ui.border}`, borderRadius: 2, bgcolor: 'var(--os-surface-alt)' }}>
          <Typography sx={{ fontWeight: 900, mb: 1 }}>How This Lab Helps</Typography>
          <Typography sx={{ color: ui.muted, lineHeight: 1.6 }}>
            Use this lab to validate simple statistical anomaly detection before using heavier outlier libraries.
            Z-score is best when values are mostly stable and unusual points are far away from the normal cluster.
          </Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 1.5 }}>
            <Chip size="small" label="1. Generate normal baseline" />
            <Chip size="small" label="2. Inject spikes or drops" />
            <Chip size="small" label="3. Tune z-score threshold" />
            <Chip size="small" label="4. Validate finding creation" />
          </Stack>
        </Box>
      </WorkspacePanel>

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Stack direction="row" alignItems="center" spacing={1.2} sx={{ mb: 2 }}>
          <ScienceRoundedIcon sx={{ color: 'var(--os-ink-brand)' }} />
          <Typography sx={{ fontWeight: 900, fontSize: 20 }}>Generate Time Series</Typography>
        </Stack>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(4, 1fr)' }, gap: 1.5 }}>
          <TextField select size="small" label="Pattern" value={pattern} onChange={(event) => { setPattern(event.target.value as Pattern); setResult(null); }}>
            {PATTERNS.map((item) => <MenuItem key={item.value} value={item.value}>{item.label}</MenuItem>)}
          </TextField>
          <TextField size="small" label="Samples" type="number" value={samples} onChange={(event) => { setSamples(Math.max(10, Number(event.target.value))); setResult(null); }} />
          <TextField size="small" label="Interval" value={interval} onChange={(event) => { setInterval(event.target.value); setResult(null); }} />
          <TextField size="small" label="Seed" type="number" value={seed} onChange={(event) => { setSeed(Number(event.target.value)); setResult(null); }} />
          <TextField size="small" label="Mean" type="number" value={mean} onChange={(event) => { setMean(Number(event.target.value)); setResult(null); }} />
          <TextField size="small" label="Noise" type="number" value={noise} onChange={(event) => { setNoise(Math.max(0.1, Number(event.target.value))); setResult(null); }} />
          <TextField size="small" label="Anomaly count" type="number" value={anomalyCount} onChange={(event) => { setAnomalyCount(Math.max(0, Number(event.target.value))); setResult(null); }} />
          <TextField size="small" label="Anomaly magnitude" type="number" value={anomalyMagnitude} onChange={(event) => { setAnomalyMagnitude(Math.max(0, Number(event.target.value))); setResult(null); }} />
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
                {chartData.filter((point) => point.is_anomaly).map((point) => (
                  <ReferenceDot key={point.index} x={point.time} y={point.value} r={5} fill={ui.red} stroke="var(--os-surface)" />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </Box>
        </WorkspacePanel>

        <WorkspacePanel sx={{ p: 2.5 }}>
          <Typography sx={{ fontWeight: 900, fontSize: 20, mb: 1.5 }}>Generated Truth</Typography>
          <Stack spacing={1.2}>
            <ScoreTile label="Generated Anomalies" value={generated.anomalies} />
            <ScoreTile label="Mean" value={generated.mean.toFixed(2)} />
            <ScoreTile label="Stddev" value={generated.stddev.toFixed(2)} />
            <ScoreTile label="Samples" value={samples} />
          </Stack>
          <Alert severity="info" sx={{ mt: 2 }}>
            Red points are injected anomalies. The analyzer recalculates mean and standard deviation from the full submitted series.
          </Alert>
        </WorkspacePanel>
      </Box>

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Stack direction={{ xs: 'column', md: 'row' }} alignItems={{ xs: 'flex-start', md: 'center' }} justifyContent="space-between" spacing={2}>
          <Box>
            <Typography sx={{ fontWeight: 900, fontSize: 20 }}>Run Z-Score Analyzer</Typography>
            <Typography sx={{ color: ui.muted }}>Execution uses the existing CSV validation pipeline with z-score overrides for this lab run only.</Typography>
          </Box>
          <Button startIcon={runMutation.isPending ? <CircularProgress size={18} color="inherit" /> : <PlayArrowRoundedIcon />} variant="contained" onClick={() => runMutation.mutate()} disabled={runMutation.isPending} sx={{ bgcolor: '#009688', textTransform: 'none', fontWeight: 850 }}>
            Run Analyzer
          </Button>
        </Stack>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(4, 1fr)' }, gap: 1.5, mt: 2 }}>
          <TextField size="small" label="Z-score threshold" type="number" value={zscoreThreshold} onChange={(event) => setZscoreThreshold(Math.max(0.1, Number(event.target.value)))} />
          <TextField size="small" label="Grouping gap" value={groupingGap} onChange={(event) => setGroupingGap(event.target.value)} />
          <TextField size="small" label="Min abs z-score" type="number" value={minAbsZscore} onChange={(event) => setMinAbsZscore(Math.max(0, Number(event.target.value)))} />
          <TextField size="small" label="Min points" type="number" value={minPoints} onChange={(event) => setMinPoints(Math.max(1, Number(event.target.value)))} />
        </Box>
        <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 2 }}>
          <Chip label={`library ${ZSCORE_CONFIG.implementation.library}`} />
          <Chip label={`method ${ZSCORE_CONFIG.implementation.method}`} />
          <Chip label={`z-score ${zscoreThreshold}`} />
          <Chip label={`min points ${minPoints}`} />
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
                <Alert severity="warning">No z-score signal was emitted. Try stronger anomalies, lower threshold, or more stable baseline noise.</Alert>
              )}
            </Stack>
          </WorkspacePanel>

          <WorkspacePanel sx={{ p: 2.5 }}>
            <Typography sx={{ fontWeight: 900, fontSize: 20, mb: 1.5 }}>Expected vs Actual</Typography>
            <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 1.2, mb: 2 }}>
              <ScoreTile label="Generated Anomalies" value={generated.anomalies} />
              <ScoreTile label="Detected Points" value={pointCount === null ? 'n/a' : pointCount} />
              <ScoreTile label="Max Abs Z-Score" value={maxAbsZscore === null ? 'n/a' : maxAbsZscore.toFixed(2)} />
              <ScoreTile label="Min Z Rule" value={minAbsZscore} />
              <ScoreTile label="Confidence" value={confidence === null ? 'n/a' : confidence.toFixed(2)} />
              <ScoreTile label="Finding" value={result.findings.length ? 'yes' : 'no'} />
            </Box>
            <Alert severity={ruleMatched ? 'success' : 'info'}>
              {ruleMatched
                ? 'The detected z-score group crossed the configured finding rule.'
                : 'A non-matching rule usually means the points are not far enough from normal, or the group has too few points.'}
            </Alert>
          </WorkspacePanel>
        </Box>
      ) : null}

      <AnalyzerLabConfigPanel
        analyzerId="anomaly_zscore"
        labName="Z-Score Anomaly Lab"
        yamlText={yamlText}
        implementation={implementation}
        findingRules={findingRules}
        passFailStatus={passFailStatus}
        passFailReason={result ? `Expected finding: ${shouldFind ? 'yes' : 'no'} based on ${generated.anomalies} generated anomalies and ${minPoints} min point rule. Actual finding: ${result.findings.length > 0 ? 'yes' : 'no'}.` : 'Run the analyzer to mark this lab run pass or fail.'}
        productionNote="the metric has a stable statistical baseline and you want simple, explainable detection for points far away from the normal range."
        benchmarkSummary={result ? { generated_anomalies: generated.anomalies, detected_points: pointCount, max_abs_zscore: maxAbsZscore, confidence, rule_matched: ruleMatched } : {}}
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
