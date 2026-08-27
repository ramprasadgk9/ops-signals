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
import { CartesianGrid, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../../api/queries';
import { PageHeader, WorkspacePanel } from '../../standalone/components';
import { ui } from '../../standalone/theme';
import type { CsvAnalyzerRoutingDecision, CsvValidationResult, ValidationSignal } from '../../types';
import { AnalyzerLabConfigPanel } from './AnalyzerLabConfigPanel';
import { analyzerConfigYaml, passFailFromFinding } from './labConfig';

type Pattern = 'repeated_motif' | 'noisy_motif' | 'single_event' | 'no_pattern';

type GeneratedPoint = {
  index: number;
  timestamp: string;
  value: number;
  motif_window: boolean;
};

const PATTERNS: Array<{ value: Pattern; label: string; explanation: string }> = [
  { value: 'repeated_motif', label: 'Repeated motif', explanation: 'The same subsequence shape appears multiple times in an otherwise steady series.' },
  { value: 'noisy_motif', label: 'Noisy motif', explanation: 'The repeated shape exists, but noise makes the match less clean.' },
  { value: 'single_event', label: 'Single event', explanation: 'Only one shape appears. STUMPY should be less confident because there is no repeat.' },
  { value: 'no_pattern', label: 'No pattern', explanation: 'The series is mostly random noise around a baseline, with no intentionally repeated shape.' },
];

const STUMPY_CONFIG = {
  implementation: {
    library: 'stumpy',
    algorithm: 'stump',
    window_size: 20,
    motif_count: 1,
    profile_threshold: 2.0,
  },
  finding_rules: {
    max_motif_distance: 1.0,
    min_confidence: 0.75,
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

function motifShape(windowSize: number, amplitude: number) {
  return Array.from({ length: windowSize }, (_, index) => {
    const phase = index / Math.max(windowSize - 1, 1);
    return Math.sin(phase * Math.PI * 2) * amplitude + Math.sin(phase * Math.PI * 4) * amplitude * 0.35;
  });
}

function motifStarts(input: { pattern: Pattern; samples: number; windowSize: number; repeatCount: number }) {
  if (input.pattern === 'no_pattern') return [];
  if (input.pattern === 'single_event') return [Math.floor(input.samples * 0.45)];
  const usable = Math.max(input.samples - input.windowSize - 4, 1);
  return Array.from({ length: input.repeatCount }, (_, order) => {
    const spacing = usable / Math.max(input.repeatCount, 1);
    return Math.min(Math.max(2, Math.round(spacing * order + spacing * 0.45)), input.samples - input.windowSize - 1);
  });
}

function generateSeries(input: {
  pattern: Pattern;
  samples: number;
  interval: string;
  seed: number;
  baseline: number;
  noise: number;
  amplitude: number;
  windowSize: number;
  repeatCount: number;
}) {
  const random = seededRandom(input.seed);
  const intervalMs = parseIntervalMs(input.interval);
  const start = new Date(Date.UTC(2026, 7, 24, 0, 0, 0));
  const points: GeneratedPoint[] = Array.from({ length: input.samples }, (_, index) => ({
    index,
    timestamp: new Date(start.getTime() + index * intervalMs).toISOString(),
    value: Number((input.baseline + gaussian(random) * input.noise).toFixed(3)),
    motif_window: false,
  }));

  const shape = motifShape(input.windowSize, input.amplitude);
  const starts = motifStarts(input);
  starts.forEach((startIndex) => {
    shape.forEach((offset, index) => {
      const pointIndex = startIndex + index;
      if (!points[pointIndex]) return;
      const extraNoise = input.pattern === 'noisy_motif' ? gaussian(random) * input.noise * 1.4 : 0;
      points[pointIndex] = {
        ...points[pointIndex],
        value: Number((input.baseline + offset + extraNoise).toFixed(3)),
        motif_window: true,
      };
    });
  });

  return { points, starts };
}

function toCsv(points: GeneratedPoint[]) {
  return [
    'timestamp,metric_name,value,service,motif_window',
    ...points.map((point) => `${point.timestamp},synthetic_stumpy_value,${point.value},stumpy-lab,${point.motif_window}`),
  ].join('\n');
}

function stumpySignal(result: CsvValidationResult | null): ValidationSignal | undefined {
  return result?.signals.find((signal) => signal.analyzer_id === 'stumpy');
}

function routerDecision(result: CsvValidationResult | null) {
  return ((result?.analyzer_routing ?? []) as CsvAnalyzerRoutingDecision[]).find((decision) => decision.analyzer_id === 'stumpy');
}

function numberEvidence(signal: ValidationSignal | undefined, key: string) {
  const value = signal?.evidence?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function nearestDistance(index: number | null, starts: number[]) {
  if (index === null || starts.length === 0) return null;
  return Math.min(...starts.map((start) => Math.abs(start - index)));
}

export function StumpyMotifLabPage() {
  const [pattern, setPattern] = useState<Pattern>('repeated_motif');
  const [samples, setSamples] = useState(180);
  const [interval, setInterval] = useState('5m');
  const [seed, setSeed] = useState(11);
  const [baseline, setBaseline] = useState(50);
  const [noise, setNoise] = useState(1.5);
  const [amplitude, setAmplitude] = useState(12);
  const [windowSize, setWindowSize] = useState(STUMPY_CONFIG.implementation.window_size);
  const [repeatCount, setRepeatCount] = useState(3);
  const [motifCount, setMotifCount] = useState(STUMPY_CONFIG.implementation.motif_count);
  const [profileThreshold, setProfileThreshold] = useState(STUMPY_CONFIG.implementation.profile_threshold);
  const [result, setResult] = useState<CsvValidationResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const generated = useMemo(
    () => generateSeries({ pattern, samples, interval, seed, baseline, noise, amplitude, windowSize, repeatCount }),
    [amplitude, baseline, interval, noise, pattern, repeatCount, samples, seed, windowSize],
  );
  const chartData = generated.points.map((point) => ({ ...point, time: new Date(point.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }));
  const signal = stumpySignal(result);
  const decision = routerDecision(result);
  const detectedIndex = numberEvidence(signal, 'motif_index');
  const motifDistance = numberEvidence(signal, 'motif_distance');
  const indexError = nearestDistance(detectedIndex, generated.starts);
  const withinTolerance = indexError !== null && indexError <= Math.max(3, Math.floor(windowSize / 3));
  const currentPattern = PATTERNS.find((item) => item.value === pattern);
  const implementation = {
    ...STUMPY_CONFIG.implementation,
    window_size: windowSize,
    motif_count: motifCount,
    profile_threshold: profileThreshold,
  };
  const findingRules = STUMPY_CONFIG.finding_rules;
  const shouldFind = generated.starts.length > 1 && (motifDistance === null || motifDistance <= findingRules.max_motif_distance);
  const passFailStatus = result ? passFailFromFinding(shouldFind, result.findings.length > 0) : 'unknown';
  const yamlText = analyzerConfigYaml('stumpy', {
    enabled: true,
    implementation,
    finding_rules: findingRules,
  });

  const runMutation = useMutation({
    mutationFn: async () => {
      const form = new FormData();
      form.set('file', new File([toCsv(generated.points)], 'stumpy-motif-lab.csv', { type: 'text/csv' }));
      form.set('provider', 'generic');
      form.set('analyzer_id', 'stumpy');
      form.set('service', 'stumpy-lab');
      form.set('metric_name', 'synthetic_stumpy_value');
      form.set('interval', interval);
      form.set('analyzer_overrides', JSON.stringify({
        stumpy: {
          implementation: {
            ...STUMPY_CONFIG.implementation,
            window_size: windowSize,
            motif_count: motifCount,
            profile_threshold: profileThreshold,
          },
          finding_rules: STUMPY_CONFIG.finding_rules,
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
      setError(err instanceof Error ? err.message : 'STUMPY lab execution failed');
    },
  });

  return (
    <Stack spacing={3}>
      <PageHeader title="STUMPY Motif Lab" subtitle="Generate repeated subsequences, inspect motif windows, run STUMPY, and compare expected vs detected pattern behavior." />

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Typography sx={{ fontWeight: 900, fontSize: 20, mb: 1 }}>What This Lab Shows</Typography>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: 'repeat(3, 1fr)' }, gap: 1.5 }}>
          <LearningNote title="What is STUMPY?" body="STUMPY finds repeated subsequences, also called motifs, in time-series data. It asks whether a shape repeats, not whether one point is unusual." />
          <LearningNote title="What data is generated?" body="The lab creates a baseline metric and injects the same short shape at known positions. Those highlighted windows are the generated motif truth." />
          <LearningNote title="How to read results" body="Compare the generated motif starts with STUMPY's motif index. A nearby index means the analyzer found one of the repeated shapes." />
        </Box>
        <Box sx={{ mt: 2, p: 2, border: `1px solid ${ui.border}`, borderRadius: 2, bgcolor: '#f8fafc' }}>
          <Typography sx={{ fontWeight: 900, mb: 1 }}>How This Lab Helps</Typography>
          <Typography sx={{ color: ui.muted, lineHeight: 1.6 }}>
            Use this lab to understand recurring behavior such as repeated CPU bursts, latency waves, or batch-job shapes.
            It separates generated motif truth, STUMPY detection, and whether Ops Signals should create a pattern-discovery finding.
          </Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 1.5 }}>
            <Chip size="small" label="1. Generate repeated shape" />
            <Chip size="small" label="2. Tune window size" />
            <Chip size="small" label="3. Check motif index" />
            <Chip size="small" label="4. Validate finding creation" />
          </Stack>
        </Box>
      </WorkspacePanel>

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Stack direction="row" alignItems="center" spacing={1.2} sx={{ mb: 2 }}>
          <ScienceRoundedIcon sx={{ color: '#0f766e' }} />
          <Typography sx={{ fontWeight: 900, fontSize: 20 }}>Generate Time Series</Typography>
        </Stack>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(4, 1fr)' }, gap: 1.5 }}>
          <TextField select size="small" label="Pattern" value={pattern} onChange={(event) => { setPattern(event.target.value as Pattern); setResult(null); }}>
            {PATTERNS.map((item) => <MenuItem key={item.value} value={item.value}>{item.label}</MenuItem>)}
          </TextField>
          <TextField size="small" label="Samples" type="number" value={samples} onChange={(event) => { setSamples(Math.max(50, Number(event.target.value))); setResult(null); }} />
          <TextField size="small" label="Interval" value={interval} onChange={(event) => { setInterval(event.target.value); setResult(null); }} />
          <TextField size="small" label="Seed" type="number" value={seed} onChange={(event) => { setSeed(Number(event.target.value)); setResult(null); }} />
          <TextField size="small" label="Baseline" type="number" value={baseline} onChange={(event) => { setBaseline(Number(event.target.value)); setResult(null); }} />
          <TextField size="small" label="Noise" type="number" value={noise} onChange={(event) => { setNoise(Math.max(0, Number(event.target.value))); setResult(null); }} />
          <TextField size="small" label="Amplitude" type="number" value={amplitude} onChange={(event) => { setAmplitude(Math.max(1, Number(event.target.value))); setResult(null); }} />
          <TextField size="small" label="Repeats" type="number" value={repeatCount} onChange={(event) => { setRepeatCount(Math.max(1, Number(event.target.value))); setResult(null); }} />
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
                {generated.starts.map((start) => (
                  <ReferenceArea key={start} x1={chartData[start]?.time} x2={chartData[start + windowSize - 1]?.time} fill={ui.purple} fillOpacity={0.12} />
                ))}
                {detectedIndex !== null && chartData[detectedIndex] && chartData[Math.min(detectedIndex + windowSize - 1, chartData.length - 1)] ? (
                  <ReferenceArea x1={chartData[detectedIndex].time} x2={chartData[Math.min(detectedIndex + windowSize - 1, chartData.length - 1)].time} fill={ui.red} fillOpacity={0.12} />
                ) : null}
                <Line type="monotone" dataKey="value" stroke="#009688" dot={false} strokeWidth={2.2} />
              </LineChart>
            </ResponsiveContainer>
          </Box>
        </WorkspacePanel>

        <WorkspacePanel sx={{ p: 2.5 }}>
          <Typography sx={{ fontWeight: 900, fontSize: 20, mb: 1.5 }}>Generated Truth</Typography>
          <Stack spacing={1.2}>
            <ScoreTile label="Expected Motifs" value={generated.starts.length} />
            <ScoreTile label="Motif Starts" value={generated.starts.length ? generated.starts.join(', ') : 'none'} />
            <ScoreTile label="Window Size" value={windowSize} />
            <ScoreTile label="Shape Amplitude" value={amplitude} />
          </Stack>
          <Alert severity="info" sx={{ mt: 2 }}>
            The highlighted windows are known repeated shapes. STUMPY should detect one of these starts when the repeat is clean enough.
          </Alert>
        </WorkspacePanel>
      </Box>

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Stack direction={{ xs: 'column', md: 'row' }} alignItems={{ xs: 'flex-start', md: 'center' }} justifyContent="space-between" spacing={2}>
          <Box>
            <Typography sx={{ fontWeight: 900, fontSize: 20 }}>Run STUMPY Analyzer</Typography>
            <Typography sx={{ color: ui.muted }}>Execution uses the existing CSV validation pipeline with STUMPY overrides for this lab run only.</Typography>
          </Box>
          <Button startIcon={runMutation.isPending ? <CircularProgress size={18} color="inherit" /> : <PlayArrowRoundedIcon />} variant="contained" onClick={() => runMutation.mutate()} disabled={runMutation.isPending} sx={{ bgcolor: '#009688', textTransform: 'none', fontWeight: 850 }}>
            Run Analyzer
          </Button>
        </Stack>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(3, 1fr)' }, gap: 1.5, mt: 2 }}>
          <TextField size="small" label="Window size" type="number" value={windowSize} onChange={(event) => setWindowSize(Math.max(4, Number(event.target.value)))} />
          <TextField size="small" label="Motif count" type="number" value={motifCount} onChange={(event) => setMotifCount(Math.max(1, Number(event.target.value)))} />
          <TextField size="small" label="Profile threshold" type="number" value={profileThreshold} onChange={(event) => setProfileThreshold(Math.max(0.1, Number(event.target.value)))} />
        </Box>
        <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 2 }}>
          <Chip label="library stumpy" />
          <Chip label="algorithm stump" />
          <Chip label={`window ${windowSize}`} />
          <Chip label={`threshold ${profileThreshold}`} />
          <Chip label={`max motif distance ${STUMPY_CONFIG.finding_rules.max_motif_distance}`} />
          <Chip label={`min confidence ${STUMPY_CONFIG.finding_rules.min_confidence}`} />
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
                <Alert severity="warning">No STUMPY signal was emitted. Try more repeats, lower noise, a matching window size, or more samples.</Alert>
              )}
            </Stack>
          </WorkspacePanel>

          <WorkspacePanel sx={{ p: 2.5 }}>
            <Typography sx={{ fontWeight: 900, fontSize: 20, mb: 1.5 }}>Expected vs Actual</Typography>
            <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 1.2, mb: 2 }}>
              <ScoreTile label="Expected Starts" value={generated.starts.length ? generated.starts.join(', ') : 'none'} />
              <ScoreTile label="Detected Index" value={detectedIndex === null ? 'n/a' : detectedIndex} />
              <ScoreTile label="Nearest Error" value={indexError === null ? 'n/a' : indexError} />
              <ScoreTile label="Within Tolerance" value={withinTolerance ? 'yes' : 'no'} />
              <ScoreTile label="Motif Distance" value={motifDistance === null ? 'n/a' : motifDistance.toFixed(2)} />
              <ScoreTile label="Finding" value={result.findings.length ? 'yes' : 'no'} />
            </Box>
            <Alert severity={withinTolerance ? 'success' : 'info'}>
              {withinTolerance
                ? 'The detected motif index is close to one generated repeated window.'
                : 'A failed or distant match usually means the shape is too noisy, appears only once, or the window size does not match the repeated shape.'}
            </Alert>
          </WorkspacePanel>
        </Box>
      ) : null}

      <AnalyzerLabConfigPanel
        analyzerId="stumpy"
        labName="STUMPY Motif Lab"
        yamlText={yamlText}
        implementation={implementation}
        findingRules={findingRules}
        passFailStatus={passFailStatus}
        passFailReason={result ? `Expected finding: ${shouldFind ? 'yes' : 'no'} based on ${generated.starts.length} generated motif starts and max motif distance ${findingRules.max_motif_distance}. Actual finding: ${result.findings.length > 0 ? 'yes' : 'no'}.` : 'Run the analyzer to mark this lab run pass or fail.'}
        productionNote="you care about repeated shapes, recurring bursts, batch-job patterns, or latency waves instead of single isolated points."
        benchmarkSummary={result ? { expected_starts: generated.starts, detected_index: detectedIndex, nearest_error: indexError, motif_distance: motifDistance, within_tolerance: withinTolerance } : {}}
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
