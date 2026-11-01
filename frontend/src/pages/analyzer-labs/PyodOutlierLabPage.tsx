import { useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded';
import ScienceRoundedIcon from '@mui/icons-material/ScienceRounded';
import { useMutation } from '@tanstack/react-query';
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceDot, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../../api/queries';
import { PageHeader, WorkspacePanel } from '../../standalone/components';
import { ui } from '../../standalone/theme';
import type { CsvAnalyzerRoutingDecision, CsvValidationResult } from '../../types';
import { AnalyzerLabConfigPanel } from './AnalyzerLabConfigPanel';
import { passFailFromFinding } from './labConfig';
import { LabSandboxBanner, RunsUse, useAnalyzerInUse, useInUseComparison } from './labSettings';
import { labChanges } from '../../utils/analyzerSettings';

type Pattern = 'gaussian_clean' | 'gaussian_spikes' | 'gaussian_drops' | 'gaussian_spikes_and_drops';

type GeneratedPoint = {
  index: number;
  timestamp: string;
  value: number;
  is_anomaly: boolean;
  anomaly_type: string;
};

const PATTERNS: Array<{ value: Pattern; label: string; explanation: string }> = [
  { value: 'gaussian_clean', label: 'Gaussian clean', explanation: 'Most values cluster around the mean with no injected outliers.' },
  { value: 'gaussian_spikes', label: 'Gaussian spikes', explanation: 'A bell-shaped baseline with isolated high spikes injected.' },
  { value: 'gaussian_drops', label: 'Gaussian drops', explanation: 'A bell-shaped baseline with isolated low drops injected.' },
  { value: 'gaussian_spikes_and_drops', label: 'Spikes and drops', explanation: 'A bell-shaped baseline with both high and low isolated outliers.' },
];

const PYOD_CONFIG = {
  enabled: true,
  implementation: {
    library: 'pyod',
    detector: 'KNN',
    detector_type: 'knn',
    contamination: 0.01,
    grouping_gap: '15m',
    min_samples: 50,
  },
  finding_rules: {
    min_range_excess: 0.56,
    min_sustained_points: 8,
    window: '15m',
  },
};

// Mirrors pyod_outlier's finding rule: an outlier is finding-worthy when it lies beyond the series'
// normal range (5th-95th percentile) by at least min_range_excess times that range.
function clearOutlierCount(points: GeneratedPoint[], minRangeExcess: number) {
  const sorted = points.map((point) => point.value).sort((a, b) => a - b);
  if (!sorted.length) return 0;
  const percentile = (p: number) => {
    const rank = (sorted.length - 1) * p;
    const lower = Math.floor(rank);
    const upper = Math.ceil(rank);
    return sorted[lower] + (sorted[upper] - sorted[lower]) * (rank - lower);
  };
  const low = percentile(0.05);
  const high = percentile(0.95);
  const width = high - low > 1e-12 ? high - low : stats(points).stddev || 1e-9;
  return points.filter((point) => point.is_anomaly && Math.max(point.value - high, low - point.value, 0) / width >= minRangeExcess).length;
}

function clampContamination(value: number) {
  if (!Number.isFinite(value)) return PYOD_CONFIG.implementation.contamination;
  return Math.max(0.001, Math.min(0.5, value));
}

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
  mean: number;
  noise: number;
  outlierCount: number;
  outlierMagnitude: number;
  seed: number;
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

  if (input.pattern !== 'gaussian_clean') {
    const selected = new Set<number>();
    while (selected.size < Math.min(input.outlierCount, Math.max(input.samples - 4, 0))) {
      selected.add(2 + Math.floor(random() * Math.max(input.samples - 4, 1)));
    }
    Array.from(selected).forEach((index, order) => {
      const spike = input.pattern === 'gaussian_spikes' || (input.pattern === 'gaussian_spikes_and_drops' && order % 2 === 0);
      const direction = spike ? 1 : -1;
      points[index] = {
        ...points[index],
        value: Number((input.mean + direction * input.noise * input.outlierMagnitude).toFixed(3)),
        is_anomaly: true,
        anomaly_type: spike ? 'spike' : 'drop',
      };
    });
  }

  return points;
}

function toCsv(points: GeneratedPoint[]) {
  return [
    'timestamp,metric_name,value,service,is_anomaly,anomaly_type',
    ...points.map((point) => `${point.timestamp},synthetic_pyod_value,${point.value},pyod-lab,${point.is_anomaly},${point.anomaly_type}`),
  ].join('\n');
}

function histogram(points: GeneratedPoint[]) {
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const buckets = 12;
  const width = (max - min || 1) / buckets;
  return Array.from({ length: buckets }, (_, index) => {
    const low = min + index * width;
    const high = index === buckets - 1 ? max + 0.001 : low + width;
    const bucketPoints = points.filter((point) => point.value >= low && point.value < high);
    return {
      label: `${low.toFixed(0)}-${high.toFixed(0)}`,
      count: bucketPoints.length,
      anomalies: bucketPoints.filter((point) => point.is_anomaly).length,
    };
  });
}

function stats(points: GeneratedPoint[]) {
  const values = points.map((point) => point.value);
  const mean = values.reduce((sum, value) => sum + value, 0) / Math.max(values.length, 1);
  const variance = values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / Math.max(values.length, 1);
  return {
    mean,
    stddev: Math.sqrt(variance),
    min: Math.min(...values),
    max: Math.max(...values),
    anomalies: points.filter((point) => point.is_anomaly).length,
  };
}

function detectedEvidence(result: CsvValidationResult | null) {
  const indexes = new Set<number>();
  const timestamps = new Set<string>();
  let pointCount = 0;
  for (const signal of result?.signals ?? []) {
    if (signal.analyzer_id !== 'pyod_outlier') continue;
    const evidence = signal.evidence ?? {};
    for (const key of ['outlier_indices', 'anomaly_indices', 'indices']) {
      const value = evidence[key];
      if (Array.isArray(value)) value.forEach((item) => typeof item === 'number' && indexes.add(item));
    }
    for (const key of ['outlier_timestamps', 'anomaly_timestamps', 'timestamps']) {
      const value = evidence[key];
      if (Array.isArray(value)) {
        value.forEach((item) => {
          if (typeof item === 'string') timestamps.add(new Date(item).toISOString());
        });
      }
    }
    const count = evidence.point_count;
    if (typeof count === 'number' && Number.isFinite(count)) pointCount += count;
  }
  return { indexes, timestamps, count: timestamps.size || indexes.size || pointCount, hasExactEvidence: timestamps.size > 0 || indexes.size > 0 };
}

function scoreDetection(points: GeneratedPoint[], result: CsvValidationResult | null) {
  const expectedIndexes = new Set(points.filter((point) => point.is_anomaly).map((point) => point.index));
  const expectedTimestamps = new Set(points.filter((point) => point.is_anomaly).map((point) => new Date(point.timestamp).toISOString()));
  const detected = detectedEvidence(result);
  const hasTimestamps = detected.timestamps.size > 0;
  const truePositive = hasTimestamps
    ? Array.from(detected.timestamps).filter((timestamp) => expectedTimestamps.has(timestamp)).length
    : detected.indexes.size > 0
      ? Array.from(detected.indexes).filter((index) => expectedIndexes.has(index)).length
      : Math.min(expectedIndexes.size, detected.count);
  const falsePositive = hasTimestamps
    ? Array.from(detected.timestamps).filter((timestamp) => !expectedTimestamps.has(timestamp)).length
    : detected.indexes.size > 0
      ? Array.from(detected.indexes).filter((index) => !expectedIndexes.has(index)).length
      : Math.max(0, detected.count - expectedIndexes.size);
  const falseNegative = hasTimestamps
    ? Array.from(expectedTimestamps).filter((timestamp) => !detected.timestamps.has(timestamp)).length
    : detected.indexes.size > 0
      ? Array.from(expectedIndexes).filter((index) => !detected.indexes.has(index)).length
      : Math.max(0, expectedIndexes.size - detected.count);
  const precision = truePositive + falsePositive ? truePositive / (truePositive + falsePositive) : null;
  const recall = truePositive + falseNegative ? truePositive / (truePositive + falseNegative) : null;
  const f1 = precision !== null && recall !== null && precision + recall > 0 ? (2 * precision * recall) / (precision + recall) : null;
  return { expected: expectedIndexes.size, detected: detected.count, truePositive, falsePositive, falseNegative, precision, recall, f1, hasExactEvidence: detected.hasExactEvidence, hasTimestamps };
}

function routerDecision(result: CsvValidationResult | null) {
  return ((result?.analyzer_routing ?? []) as CsvAnalyzerRoutingDecision[]).find((decision) => decision.analyzer_id === 'pyod_outlier');
}

export function PyodOutlierLabPage() {
  const [pattern, setPattern] = useState<Pattern>('gaussian_spikes');
  const [samples, setSamples] = useState(288);
  const [interval, setInterval] = useState('5m');
  const [mean, setMean] = useState(50);
  const [noise, setNoise] = useState(3);
  const [outlierCount, setOutlierCount] = useState(8);
  const [outlierMagnitude, setOutlierMagnitude] = useState(6);
  const [seed, setSeed] = useState(42);
  const [autoAlignContamination, setAutoAlignContamination] = useState(true);
  const [pyodContamination, setPyodContamination] = useState(PYOD_CONFIG.implementation.contamination);
  const [pyodMinSamples, setPyodMinSamples] = useState(PYOD_CONFIG.implementation.min_samples);
  const [pyodGroupingGap, setPyodGroupingGap] = useState(PYOD_CONFIG.implementation.grouping_gap);
  const [result, setResult] = useState<CsvValidationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { analyzer: inUse } = useAnalyzerInUse('pyod_outlier');
  const { comparison, compare } = useInUseComparison();

  const points = useMemo(() => generateSeries({ pattern, samples, interval, mean, noise, outlierCount, outlierMagnitude, seed }), [interval, mean, noise, outlierCount, outlierMagnitude, pattern, samples, seed]);
  const chartData = points.map((point) => ({ ...point, time: new Date(point.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }));
  const distribution = histogram(points);
  const summary = stats(points);
  const score = scoreDetection(points, result);
  const decision = routerDecision(result);
  const currentPattern = PATTERNS.find((item) => item.value === pattern);
  const alignedContamination = clampContamination(outlierCount / Math.max(samples, 1));
  const effectivePyodContamination = autoAlignContamination ? alignedContamination : clampContamination(pyodContamination);
  const pyodDetectionBudget = Math.round(samples * effectivePyodContamination);
  const implementation = {
    ...PYOD_CONFIG.implementation,
    contamination: effectivePyodContamination,
    min_samples: pyodMinSamples,
    grouping_gap: pyodGroupingGap,
  };
  const findingRules = PYOD_CONFIG.finding_rules;
  const clearOutliers = clearOutlierCount(points, findingRules.min_range_excess);
  const shouldFind = clearOutliers >= 1;
  const passFailStatus = result ? passFailFromFinding(shouldFind, result.findings.length > 0) : 'unknown';
  const values = { implementation, finding_rule: findingRules };
  const hasChanges = labChanges(inUse, values).length > 0;

  const runMutation = useMutation({
    mutationFn: async () => {
      const csv = toCsv(points);
      const form = new FormData();
      form.set('file', new File([csv], 'pyod-outlier-lab.csv', { type: 'text/csv' }));
      form.set('provider', 'generic');
      form.set('analyzer_id', 'pyod_outlier');
      form.set('service', 'pyod-lab');
      form.set('metric_name', 'synthetic_pyod_value');
      form.set('interval', interval);
      form.set('analyzer_overrides', JSON.stringify({
        pyod_outlier: {
          implementation: {
            ...PYOD_CONFIG.implementation,
            contamination: effectivePyodContamination,
            min_samples: pyodMinSamples,
            grouping_gap: pyodGroupingGap,
          },
          finding_rules: PYOD_CONFIG.finding_rules,
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
      setError(err instanceof Error ? err.message : 'PyOD lab execution failed');
    },
  });

  return (
    <Stack spacing={3}>
      <PageHeader title="PyOD Outlier Lab" subtitle="Generate controlled point-outlier data, inspect the shape, run pyod_outlier, and compare expected vs actual behavior." />
      <LabSandboxBanner analyzerId="pyod_outlier" paths={['implementation.contamination', 'implementation.min_samples', 'implementation.grouping_gap', 'finding_rule.min_range_excess']} />

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Typography sx={{ fontWeight: 900, fontSize: 20, mb: 1 }}>What This Lab Shows</Typography>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: 'repeat(3, 1fr)' }, gap: 1.5 }}>
          <LearningNote
            title="What is PyOD?"
            body="PyOD is a Python library for outlier detection. In this app, pyod_outlier is used when a metric mostly behaves normally but has isolated unusual points, such as sudden spikes or drops."
          />
          <LearningNote
            title="What data is generated?"
            body="The lab creates synthetic time-series data: timestamped metric values ordered over time. Most values stay near the configured mean, and selected points are injected as known outliers for testing."
          />
          <LearningNote
            title="How to read results"
            body="After execution, compare expected outliers with detected outliers. Router confidence explains whether pyod_outlier was a good analyzer choice; signals and findings explain what Ops Signals emitted."
          />
        </Box>
        <Box sx={{ mt: 2, p: 2, border: `1px solid ${ui.border}`, borderRadius: 2, bgcolor: 'var(--os-surface-alt)' }}>
          <Typography sx={{ fontWeight: 900, mb: 1 }}>How This Lab Helps</Typography>
          <Typography sx={{ color: ui.muted, lineHeight: 1.6 }}>
            Use this lab to separate generated truth, PyOD detection, and Ops Signals finding rules. First, create known outliers.
            Then check whether PyOD detects the right points without too many false positives. Finally, confirm whether the finding
            rule would promote those signals into an actionable finding.
          </Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 1.5 }}>
            <Chip size="small" label="1. Generate known outliers" />
            <Chip size="small" label="2. Tune contamination" />
            <Chip size="small" label="3. Review false positives" />
            <Chip size="small" label="4. Validate finding rule" />
          </Stack>
        </Box>
      </WorkspacePanel>

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Stack direction="row" alignItems="center" spacing={1.2} sx={{ mb: 2 }}>
          <ScienceRoundedIcon sx={{ color: 'var(--os-ink-brand)' }} />
          <Typography sx={{ fontWeight: 900, fontSize: 20 }}>Generate Time Series</Typography>
        </Stack>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(4, 1fr)' }, gap: 1.5 }}>
          <TextField select size="small" label="Pattern" value={pattern} onChange={(event) => setPattern(event.target.value as Pattern)}>
            {PATTERNS.map((item) => <MenuItem key={item.value} value={item.value}>{item.label}</MenuItem>)}
          </TextField>
          <TextField size="small" label="Samples" type="number" value={samples} onChange={(event) => setSamples(Math.max(20, Number(event.target.value)))} />
          <TextField size="small" label="Interval" value={interval} onChange={(event) => setInterval(event.target.value)} />
          <TextField size="small" label="Seed" type="number" value={seed} onChange={(event) => setSeed(Number(event.target.value))} />
          <TextField size="small" label="Mean" type="number" value={mean} onChange={(event) => setMean(Number(event.target.value))} />
          <TextField size="small" label="Noise" type="number" value={noise} onChange={(event) => setNoise(Math.max(0.1, Number(event.target.value)))} />
          <TextField size="small" label="Outliers" type="number" value={outlierCount} onChange={(event) => setOutlierCount(Math.max(0, Number(event.target.value)))} />
          <TextField size="small" label="Magnitude" type="number" value={outlierMagnitude} onChange={(event) => setOutlierMagnitude(Math.max(1, Number(event.target.value)))} />
        </Box>
      </WorkspacePanel>

      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: '1.45fr 0.85fr' }, gap: 2 }}>
        <WorkspacePanel sx={{ p: 2.5 }}>
          <Typography sx={{ fontWeight: 900, fontSize: 20, mb: 0.5 }}>Understand Data</Typography>
          <Typography sx={{ color: ui.muted, mb: 2 }}>{currentPattern?.explanation}</Typography>
          <Box sx={{ height: 300 }}>
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
          <Typography sx={{ fontWeight: 900, fontSize: 20, mb: 0.5 }}>Bell Curve View</Typography>
          <Typography sx={{ color: ui.muted, mb: 2 }}>Most Gaussian baseline values cluster around the mean. PyOD should focus on values far from that dense center.</Typography>
          <Box sx={{ height: 230 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={distribution}>
                <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={11} />
                <YAxis tickLine={false} axisLine={false} width={30} />
                <Tooltip />
                <Bar dataKey="count" radius={[5, 5, 0, 0]}>
                  {distribution.map((bucket) => <Cell key={bucket.label} fill={bucket.anomalies ? ui.red : ui.blue} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </Box>
          <Stack direction="row" spacing={1} flexWrap="wrap">
            <Chip size="small" label={`mean ${summary.mean.toFixed(2)}`} />
            <Chip size="small" label={`stddev ${summary.stddev.toFixed(2)}`} />
            <Chip size="small" label={`min ${summary.min.toFixed(2)}`} />
            <Chip size="small" label={`max ${summary.max.toFixed(2)}`} />
            <Chip size="small" label={`${summary.anomalies} expected outliers`} />
            <Chip size="small" color={pyodDetectionBudget === summary.anomalies ? 'success' : 'warning'} label={`PyOD budget ~${pyodDetectionBudget}`} />
          </Stack>
          {pyodDetectionBudget !== summary.anomalies ? (
            <Alert severity="warning" sx={{ mt: 2 }}>
              Generated outliers are {summary.anomalies}, but this run's PyOD contamination is {effectivePyodContamination.toFixed(4)}. With {samples} samples, PyOD will try to mark about {pyodDetectionBudget} points as outliers.
            </Alert>
          ) : null}
        </WorkspacePanel>
      </Box>

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Stack direction={{ xs: 'column', md: 'row' }} alignItems={{ xs: 'flex-start', md: 'center' }} justifyContent="space-between" spacing={2}>
          <Box>
            <Typography sx={{ fontWeight: 900, fontSize: 20 }}>Run pyod_outlier</Typography>
            <Typography sx={{ color: ui.muted }}>Execution uses the existing CSV validation pipeline and analyzer routing rules.</Typography>
          </Box>
          <Button startIcon={runMutation.isPending ? <CircularProgress size={18} color="inherit" /> : <PlayArrowRoundedIcon />} variant="contained" onClick={() => runMutation.mutate()} disabled={runMutation.isPending} sx={{ bgcolor: '#009688', textTransform: 'none', fontWeight: 850 }}>
            Run Analyzer
          </Button>
        </Stack>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(4, 1fr)' }, gap: 1.5, mt: 2 }}>
          <FormControlLabel
            control={<Switch checked={autoAlignContamination} onChange={(event) => setAutoAlignContamination(event.target.checked)} />}
            label="Auto-align contamination"
            sx={{ alignSelf: 'center' }}
          />
          <TextField
            size="small"
            label="Contamination"
            type="number"
            value={autoAlignContamination ? alignedContamination.toFixed(4) : pyodContamination}
            disabled={autoAlignContamination}
            inputProps={{ step: 0.001, min: 0.001, max: 0.5 }}
            onChange={(event) => setPyodContamination(clampContamination(Number(event.target.value)))}
            helperText={<RunsUse analyzer={inUse} path="implementation.contamination" value={effectivePyodContamination} onReset={(value) => { setAutoAlignContamination(false); setPyodContamination(Number(value)); }} />}
          />
          <TextField size="small" label="Min samples" type="number" value={pyodMinSamples} onChange={(event) => setPyodMinSamples(Math.max(3, Number(event.target.value)))} helperText={<RunsUse analyzer={inUse} path="implementation.min_samples" value={pyodMinSamples} onReset={(value) => setPyodMinSamples(Number(value))} />} />
          <TextField size="small" label="Grouping gap" value={pyodGroupingGap} onChange={(event) => setPyodGroupingGap(event.target.value)} helperText={<RunsUse analyzer={inUse} path="implementation.grouping_gap" value={pyodGroupingGap} onReset={(value) => setPyodGroupingGap(String(value))} />} />
        </Box>
        <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 2 }}>
          <Chip label={`enabled ${PYOD_CONFIG.enabled}`} />
          <Chip label={`library ${PYOD_CONFIG.implementation.library}`} />
          <Chip label={`detector ${PYOD_CONFIG.implementation.detector}`} />
          <Chip label={`default contamination ${PYOD_CONFIG.implementation.contamination}`} />
          <Chip color="primary" label={`run contamination ${effectivePyodContamination.toFixed(4)}`} />
          <Chip color={pyodDetectionBudget === summary.anomalies ? 'success' : 'warning'} label={`expected detector count ~${pyodDetectionBudget}`} />
          <Chip label={`run grouping gap ${pyodGroupingGap}`} />
          <Chip label={`run min samples ${pyodMinSamples}`} />
          <Chip label={`finding rule: ${PYOD_CONFIG.finding_rules.min_range_excess}x the normal range beyond it, or ${PYOD_CONFIG.finding_rules.min_sustained_points}+ outliers in a row`} />
        </Stack>
        <Alert severity="info" sx={{ mt: 2 }}>
          These are experiment-only overrides. analyzers.yaml remains the production default; this run temporarily sends contamination, min_samples, and grouping_gap to pyod_outlier.
        </Alert>
        {error ? <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert> : null}
      </WorkspacePanel>

      {result ? (
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: '1fr 1fr' }, gap: 2 }}>
          <WorkspacePanel sx={{ p: 2.5 }}>
            <Typography sx={{ fontWeight: 900, fontSize: 20, mb: 1.5 }}>Execution Result</Typography>
            <Stack spacing={1.2}>
              <Chip sx={{ alignSelf: 'flex-start', fontWeight: 850 }} color={decision?.recommendation === 'RECOMMENDED' ? 'success' : decision?.recommendation === 'REJECTED' ? 'error' : 'default'} label={decision?.recommendation ?? 'No router decision'} />
              <Typography sx={{ color: ui.text, fontWeight: 850 }}>Confidence {typeof decision?.final_score === 'number' ? decision.final_score.toFixed(2) : 'n/a'}</Typography>
              <Typography sx={{ color: ui.muted }}>{decision?.routing_reason ?? decision?.explanation ?? 'Router did not return a pyod_outlier explanation.'}</Typography>
              <Typography sx={{ color: ui.text, fontWeight: 850 }}>{result.signals.length} signals, {result.findings.length} findings</Typography>
              <Alert severity="info">
                A strong pyod_outlier result means the generated series had enough samples and isolated values far away from the normal cluster. A rejected result usually means too few samples, no variance, or a pattern better suited to another analyzer.
              </Alert>
              {result.signals.map((signal) => (
                <Box key={signal.signal_id} sx={{ borderTop: `1px solid ${ui.border}`, pt: 1 }}>
                  <Typography sx={{ fontWeight: 850 }}>{signal.summary}</Typography>
                  <Typography sx={{ color: ui.muted, fontSize: 13 }}>{signal.analyzer_id} • {signal.severity} • confidence {signal.confidence.toFixed(2)}</Typography>
                </Box>
              ))}
            </Stack>
          </WorkspacePanel>

          <WorkspacePanel sx={{ p: 2.5 }}>
            <Typography sx={{ fontWeight: 900, fontSize: 20, mb: 1.5 }}>Expected vs Actual</Typography>
            <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 1.2, mb: 2 }}>
              <ScoreTile label="Generated Outliers" value={score.expected} />
              <ScoreTile label="PyOD Budget" value={`~${pyodDetectionBudget}`} />
              <ScoreTile label="PyOD Detected" value={score.detected} />
              <ScoreTile label="True Positive" value={score.truePositive} />
              <ScoreTile label="False Positive" value={score.falsePositive} />
              <ScoreTile label="False Negative" value={score.falseNegative} />
              <ScoreTile label="F1" value={score.f1 === null ? 'n/a' : score.f1.toFixed(2)} />
            </Box>
            {pyodDetectionBudget !== score.expected ? (
              <Alert severity="warning" sx={{ mb: 1.5 }}>
                This is not a bug by itself: PyOD KNN uses contamination as the expected outlier fraction. Current settings generate {score.expected} labeled outliers, but PyOD is configured to detect about {pyodDetectionBudget}.
              </Alert>
            ) : null}
            <Alert severity="info">
              {score.hasExactEvidence
                ? `This benchmark compares exact generated outlier ${score.hasTimestamps ? 'timestamps' : 'indices'} with exact PyOD detected ${score.hasTimestamps ? 'timestamps' : 'indices'}.`
                : 'This benchmark is using PyOD point counts because this response did not include exact timestamp or index evidence.'}
            </Alert>
          </WorkspacePanel>
        </Box>
      ) : null}

      <AnalyzerLabConfigPanel
        analyzerId="pyod_outlier"
        labName="PyOD Outlier Lab"
        values={values}
        yourFound={result ? result.findings.length > 0 : null}
        comparison={comparison}
        passFailStatus={passFailStatus}
        passFailReason={result ? `Expected finding: ${shouldFind ? 'yes' : 'no'} based on ${clearOutliers} of ${summary.anomalies} generated outliers lying at least ${findingRules.min_range_excess}x the normal range beyond it. Actual finding: ${result.findings.length > 0 ? 'yes' : 'no'}.` : 'Run the analyzer to mark this lab run pass or fail.'}
        productionNote="the metric usually stays near a normal baseline and you only want findings after repeated high-confidence isolated spikes or drops in a short window."
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
