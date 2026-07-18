import { useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import type { ValidationFinding, ValidationSignal } from '../types';

type Provider = 'generic' | 'prometheus' | 'datadog';

const ANALYZER_OPTIONS = [
  { id: 'ruptures', label: 'Ruptures' },
  { id: 'stumpy', label: 'STUMPY' },
  { id: 'prophet', label: 'Prophet' },
  { id: 'baseline_shift', label: 'Baseline Shift' },
  { id: 'anomaly_zscore', label: 'Anomaly Z-Score' },
  { id: 'trend', label: 'Trend' },
];

export function ValidateDataPage() {
  const [provider, setProvider] = useState<Provider>('prometheus');
  const [analyzerId, setAnalyzerId] = useState('ruptures');
  const [service, setService] = useState('checkout');
  const [metricName, setMetricName] = useState('cpu_usage');
  const [interval, setInterval] = useState('5m');
  const [file, setFile] = useState<File | null>(null);
  const [resultSignals, setResultSignals] = useState<ValidationSignal[]>([]);
  const [resultFindings, setResultFindings] = useState<ValidationFinding[]>([]);
  const [previewRows, setPreviewRows] = useState<Array<Record<string, unknown>>>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const capabilitiesQuery = useQuery({
    queryKey: ['capabilities'],
    queryFn: () => api.capabilities(),
  });

  const analyzerOptions = useMemo(() => {
    const enabledFromCapabilities = (capabilitiesQuery.data ?? [])
      .map((capability) => capability.analyzer_id)
      .filter((value, index, array) => array.indexOf(value) === index);
    const fromCapabilities = ANALYZER_OPTIONS.filter((option) => enabledFromCapabilities.includes(option.id));
    return fromCapabilities.length > 0 ? fromCapabilities : ANALYZER_OPTIONS;
  }, [capabilitiesQuery.data]);

  const mutation = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('Select a CSV file first');
      const form = new FormData();
      form.set('file', file);
      form.set('provider', provider);
      form.set('analyzer_id', analyzerId);
      form.set('service', service);
      form.set('metric_name', metricName);
      form.set('interval', interval);
      return api.runCsvValidation(form);
    },
    onSuccess: (result) => {
      setError(null);
      setMessage(`Preview generated for ${result.analyzer_id} with ${result.sample_count} samples.`);
      setResultSignals(result.signals);
      setResultFindings(result.findings);
      setPreviewRows(result.normalized_preview);
    },
    onError: (err: unknown) => {
      setMessage(null);
      setError(err instanceof Error ? err.message : 'Validation failed');
    },
  });

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <Card variant="outlined">
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h5">Dry-Run with Analyzers</Typography>
            <Typography variant="body2" color="text.secondary">
              Upload a timeseries, choose an analyzer, and preview signals and findings without saving anything.
            </Typography>

            <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
              <FormControl fullWidth>
                <InputLabel>Provider</InputLabel>
                <Select value={provider} label="Provider" onChange={(e) => setProvider(e.target.value as Provider)}>
                  <MenuItem value="prometheus">Prometheus</MenuItem>
                  <MenuItem value="datadog">Datadog</MenuItem>
                  <MenuItem value="generic">Generic</MenuItem>
                </Select>
              </FormControl>
              <FormControl fullWidth>
                <InputLabel>Analyzer</InputLabel>
                <Select value={analyzerId} label="Analyzer" onChange={(e) => setAnalyzerId(e.target.value)}>
                  {analyzerOptions.map((option) => (
                    <MenuItem key={option.id} value={option.id}>
                      {option.label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <TextField fullWidth label="Service" value={service} onChange={(e) => setService(e.target.value)} />
              <TextField fullWidth label="Metric" value={metricName} onChange={(e) => setMetricName(e.target.value)} />
              <TextField fullWidth label="Interval" value={interval} onChange={(e) => setInterval(e.target.value)} />
            </Stack>

            <Box>
              <Button variant="outlined" component="label">
                {file ? `Selected: ${file.name}` : 'Choose CSV File'}
                <input hidden type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              </Button>
            </Box>

            <Box>
              <Button
                variant="contained"
                disabled={mutation.isPending || !file}
                onClick={() => {
                  setMessage(null);
                  setError(null);
                  mutation.mutate();
                }}
              >
                {mutation.isPending ? <CircularProgress size={20} color="inherit" /> : 'Validate Data'}
              </Button>
            </Box>

            {message ? <Alert severity="success">{message}</Alert> : null}
            {error ? <Alert severity="error">{error}</Alert> : null}
          </Stack>
        </CardContent>
      </Card>

      {previewRows.length > 0 ? (
        <Card variant="outlined">
          <CardContent>
            <Stack spacing={2}>
              <Typography variant="h6">Normalized Preview</Typography>
              <Box sx={{ overflowX: 'auto' }}>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      {Object.keys(previewRows[0] ?? {}).map((key) => (
                        <TableCell key={key}>{key}</TableCell>
                      ))}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {previewRows.slice(0, 10).map((row, index) => (
                      <TableRow key={index}>
                        {Object.values(row).map((value, valueIndex) => (
                          <TableCell key={valueIndex}>{typeof value === 'object' ? JSON.stringify(value) : String(value ?? '')}</TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Box>
            </Stack>
          </CardContent>
        </Card>
      ) : null}

      <Card variant="outlined">
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h6">Signals</Typography>
            {resultSignals.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                No signals returned yet.
              </Typography>
            ) : (
              resultSignals.map((signal) => (
                <Card key={signal.signal_id} variant="outlined" sx={{ p: 2 }}>
                  <Stack spacing={1}>
                    <Stack direction="row" spacing={1} flexWrap="wrap">
                      <Chip label={signal.signal_type} size="small" />
                      <Chip label={signal.severity} size="small" />
                      <Chip label={signal.analyzer_id} size="small" />
                    </Stack>
                    <Typography variant="subtitle1">{signal.summary}</Typography>
                    <Typography variant="body2" color="text.secondary">
                      {signal.metric_name} · {signal.service ?? 'n/a'} · confidence {signal.confidence.toFixed(2)}
                    </Typography>
                  </Stack>
                </Card>
              ))
            )}
          </Stack>
        </CardContent>
      </Card>

      <Card variant="outlined">
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h6">Findings</Typography>
            {resultFindings.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                No findings returned yet.
              </Typography>
            ) : (
              resultFindings.map((finding) => (
                <Card key={`${finding.metric_name}-${finding.title}`} variant="outlined" sx={{ p: 2 }}>
                  <Stack spacing={1}>
                    <Stack direction="row" spacing={1} flexWrap="wrap">
                      <Chip label={finding.health_status} size="small" />
                      <Chip label={finding.category} size="small" />
                    </Stack>
                    <Typography variant="subtitle1">{finding.title}</Typography>
                    <Typography variant="body2" color="text.secondary">
                      {finding.summary}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      Importance {finding.importance_score.toFixed(2)} · Priority {finding.investigation_priority}
                    </Typography>
                  </Stack>
                </Card>
              ))
            )}
          </Stack>
        </CardContent>
      </Card>
    </Box>
  );
}
