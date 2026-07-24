import { useState } from 'react';
import { Alert, Box, Button, Card, CardContent, Chip, CircularProgress, FormControl, InputLabel, MenuItem, Select, Stack, TextField, Typography } from '@mui/material';
import { useMutation } from '@tanstack/react-query';
import { api } from '../api/queries';

function analyzerGroup(analyzer: string) {
  if (['ruptures', 'trend_regression'].includes(analyzer)) return 'Structural Breakpoint & Drift';
  if (['prophet', 'darts'].includes(analyzer)) return 'Forecasting';
  if (['stumpy', 'alibi_detect'].includes(analyzer)) return 'Pattern & Shape Matching';
  if (['river', 'adtk', 'pyod'].includes(analyzer)) return 'Anomaly & Outlier Detection';
  if (analyzer === 'kats') return 'Mixed Behavior';
  return 'Other';
}

function groupExplanation(group: string) {
  switch (group) {
    case 'Structural Breakpoint & Drift':
      return 'Why this group? These analyzers look for persistent level changes, gradual drift, or regime shifts in a series.';
    case 'Forecasting':
      return 'Why this group? These analyzers are best when the series has enough history and a stable repeating pattern to project forward.';
    case 'Pattern & Shape Matching':
      return 'Why this group? These analyzers compare recurring shapes, motifs, or distribution patterns to find structure or change.';
    case 'Anomaly & Outlier Detection':
      return 'Why this group? These analyzers are tuned to catch spikes, rare points, or abnormal deviations rather than long baseline shifts.';
    case 'Mixed Behavior':
      return 'Why this group? This category is for analyzers that benefit from a combination of trend, seasonality, and change-point evidence.';
    default:
      return 'Why this group? These analyzers did not fit one of the main categories cleanly.';
  }
}

export function AnalyzerRouterExperimentPage() {
  const [file, setFile] = useState<File | null>(null);
  const [timestampColumn, setTimestampColumn] = useState('timestamp');
  const [valueColumn, setValueColumn] = useState('value');
  const [routingMode, setRoutingMode] = useState('automatic_with_override');
  const [selectedAnalyzers, setSelectedAnalyzers] = useState('');

  const mutation = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('Choose a CSV file first');
      const form = new FormData();
      form.set('file', file);
      form.set('timestamp_column', timestampColumn);
      form.set('value_column', valueColumn);
      form.set('routing_mode', routingMode);
      form.set('selected_analyzers', selectedAnalyzers);
      return api.analyzerRouterRoute(form);
    },
  });

  const groupedDecisions = mutation.data?.analyzers.reduce<Record<string, typeof mutation.data.analyzers>>((acc, decision) => {
    const group = analyzerGroup(decision.analyzer);
    acc[group] = acc[group] ?? [];
    acc[group].push(decision);
    return acc;
  }, {}) ?? {};

  return (
    <Stack spacing={3}>
      <Card variant="outlined">
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h4">Universal Time-Series Analyzer Router</Typography>
            <Typography variant="body2" color="text.secondary">
              Profile a time series, see which analyzers are eligible, and route only the ones that fit the signal.
              Only timestamp and value are required. Metric name and service are optional metadata.
            </Typography>
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
              <TextField fullWidth label="Timestamp column" value={timestampColumn} onChange={(e) => setTimestampColumn(e.target.value)} helperText="Required" />
              <TextField fullWidth label="Value column" value={valueColumn} onChange={(e) => setValueColumn(e.target.value)} helperText="Required" />
              <FormControl fullWidth>
                <InputLabel>Routing mode</InputLabel>
                <Select value={routingMode} label="Routing mode" onChange={(e) => setRoutingMode(String(e.target.value))}>
                  <MenuItem value="automatic">Automatic</MenuItem>
                  <MenuItem value="manual">Manual analyzer selection</MenuItem>
                  <MenuItem value="automatic_with_override">Automatic with manual override</MenuItem>
                </Select>
              </FormControl>
            </Stack>
            <TextField
              fullWidth
              label="Selected analyzers"
              value={selectedAnalyzers}
              onChange={(e) => setSelectedAnalyzers(e.target.value)}
              helperText="Optional. Comma-separated, for example ruptures,stumpy"
            />
            <Box>
              <Button variant="outlined" component="label">
                {file ? file.name : 'Choose CSV file'}
                <input hidden type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              </Button>
            </Box>
            <Box>
              <Button variant="contained" disabled={!file || mutation.isPending} onClick={() => mutation.mutate()}>
                {mutation.isPending ? <CircularProgress size={20} color="inherit" /> : 'Run Router'}
              </Button>
            </Box>
          </Stack>
        </CardContent>
      </Card>

      {mutation.data ? (
        <>
          <Alert severity="info">{mutation.data.summary}</Alert>
          <Card variant="outlined">
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="h6">Routing Decisions</Typography>
                {Object.entries(groupedDecisions).map(([group, decisions]) => (
                  <Box key={group}>
                    <Typography variant="subtitle1" sx={{ mb: 1, fontWeight: 700 }}>
                      {group}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                      {groupExplanation(group)}
                    </Typography>
                    <Stack spacing={1.5}>
                      {decisions.map((decision) => (
                        <Card key={decision.analyzer} variant="outlined" sx={{ p: 2 }}>
                          <Stack spacing={1}>
                            <Stack direction="row" spacing={1} flexWrap="wrap">
                              <Chip label={decision.display_name} />
                              <Chip label={decision.recommendation} color={decision.recommendation === 'RECOMMENDED' ? 'success' : decision.recommendation === 'OPTIONAL' ? 'warning' : 'default'} />
                              <Chip label={`eligible=${String(decision.eligible)}`} />
                            </Stack>
                            <Typography variant="body2">Final score: {decision.final_score}</Typography>
                            <Typography variant="body2" color="text.secondary">{decision.explanation}</Typography>
                          </Stack>
                        </Card>
                      ))}
                    </Stack>
                  </Box>
                ))}
              </Stack>
            </CardContent>
          </Card>
        </>
      ) : null}
    </Stack>
  );
}
