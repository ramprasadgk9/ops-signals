import { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/queries';

type Provider = 'generic' | 'prometheus' | 'datadog';

export function CsvUploadPanel() {
  const queryClient = useQueryClient();
  const [provider, setProvider] = useState<Provider>('prometheus');
  const [service, setService] = useState('checkout');
  const [metricName, setMetricName] = useState('cpu_usage');
  const [interval, setInterval] = useState('5m');
  const [file, setFile] = useState<File | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('Select a CSV file first');
      const form = new FormData();
      form.set('file', file);
      form.set('provider', provider);
      form.set('service', service);
      form.set('metric_name', metricName);
      form.set('interval', interval);
      return api.runCsvUpload(form);
    },
    onSuccess: async (result) => {
      setError(null);
      setMessage(`Analysis run created: ${result.analysis_run_id} (${result.findings_count} findings)`);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['analysis-runs'] }),
        queryClient.invalidateQueries({ queryKey: ['capabilities'] }),
        queryClient.invalidateQueries({ queryKey: ['questions-available'] }),
        queryClient.invalidateQueries({ queryKey: ['signals'] }),
        queryClient.invalidateQueries({ queryKey: ['timeseries'] }),
      ]);
    },
    onError: (err: unknown) => {
      setMessage(null);
      setError(err instanceof Error ? err.message : 'Upload failed');
    },
  });

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="h6">Upload CSV And Run Analysis</Typography>
          <Typography variant="body2" color="text.secondary">
            Upload a Prometheus, Datadog, or generic timeseries CSV and process it directly from the UI.
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
            <TextField fullWidth label="Service" value={service} onChange={(e) => setService(e.target.value)} />
            <TextField fullWidth label="Metric" value={metricName} onChange={(e) => setMetricName(e.target.value)} />
            <TextField fullWidth label="Interval" value={interval} onChange={(e) => setInterval(e.target.value)} />
          </Stack>

          <Box>
            <Button variant="outlined" component="label">
              {file ? `Selected: ${file.name}` : 'Choose CSV File'}
              <input
                hidden
                type="file"
                accept=".csv,text/csv"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
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
              {mutation.isPending ? <CircularProgress size={20} color="inherit" /> : 'Run Analysis'}
            </Button>
          </Box>

          {message ? <Alert severity="success">{message}</Alert> : null}
          {error ? <Alert severity="error">{error}</Alert> : null}
        </Stack>
      </CardContent>
    </Card>
  );
}
