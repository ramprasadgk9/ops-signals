import React, { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  CircularProgress,
  FormControl,
  FormControlLabel,
  FormGroup,
  Grid,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';
import TuneRoundedIcon from '@mui/icons-material/TuneRounded';
import KeyRoundedIcon from '@mui/icons-material/KeyRounded';
import type { BenchmarkRunRequestPayload, BenchmarkScenarioDescriptor } from '../../types/benchmark';

interface BenchmarkRunControlsProps {
  scenarios: BenchmarkScenarioDescriptor[];
  isRunning: boolean;
  onRun: (payload: BenchmarkRunRequestPayload) => Promise<void>;
  error?: string | null;
}

export const BenchmarkRunControls: React.FC<BenchmarkRunControlsProps> = ({
  scenarios,
  isRunning,
  onRun,
  error,
}) => {
  const [provider, setProvider] = useState<'mock' | 'gemini' | 'openai' | 'openrouter'>('mock');
  const [modelId, setModelId] = useState<string>('mock-frontier-sre');
  const [selectedScenarios, setSelectedScenarios] = useState<string[]>(
    scenarios.map((s) => s.id)
  );

  const handleProviderChange = (newProvider: 'mock' | 'gemini' | 'openai' | 'openrouter') => {
    setProvider(newProvider);
    if (newProvider === 'gemini') {
      setModelId('gemini-3.8-flash');
    } else if (newProvider === 'openai') {
      setModelId('gpt-4o');
    } else if (newProvider === 'openrouter') {
      setModelId('anthropic/claude-3.5-sonnet');
    } else {
      setModelId('mock-frontier-sre');
    }
  };

  const handleToggleScenario = (scenarioId: string) => {
    setSelectedScenarios((prev) =>
      prev.includes(scenarioId) ? prev.filter((id) => id !== scenarioId) : [...prev, scenarioId]
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await onRun({
      provider,
      model_id: modelId,
      scenarios: selectedScenarios.length > 0 ? selectedScenarios : undefined,
    });
  };

  return (
    <Card variant="outlined" sx={{ borderRadius: 2 }}>
      <CardContent>
        <form onSubmit={handleSubmit}>
          <Stack spacing={2.5}>
            <Stack direction="row" alignItems="center" spacing={1}>
              <TuneRoundedIcon color="primary" />
              <Typography variant="h6" sx={{ fontWeight: 700 }}>
                Run Benchmark Evaluation
              </Typography>
            </Stack>

            {error && <Alert severity="error">{error}</Alert>}

            {provider === 'gemini' && (
              <Alert severity="info" icon={<KeyRoundedIcon fontSize="inherit" />}>
                Live Gemini evaluation requires <strong>GEMINI_API_KEY</strong> set in your backend environment.
                Queries will be routed via Google's OpenAI-compatible endpoint at official Flash pricing ($0.10/Mtok in, $0.40/Mtok out).
              </Alert>
            )}

            {provider === 'mock' && (
              <Alert severity="success">
                Offline mock execution runs with zero latency, zero API costs, and 100% deterministic repeatable evaluation.
              </Alert>
            )}

            <Grid container spacing={2}>
              <Grid item xs={12} sm={4}>
                <FormControl fullWidth size="small">
                  <InputLabel id="provider-select-label">Execution Provider</InputLabel>
                  <Select
                    labelId="provider-select-label"
                    label="Execution Provider"
                    value={provider}
                    disabled={isRunning}
                    onChange={(e) => handleProviderChange(e.target.value as any)}
                  >
                    <MenuItem value="mock">Mock (Offline, Zero Cost)</MenuItem>
                    <MenuItem value="gemini">Google Gemini (Live API)</MenuItem>
                    <MenuItem value="openai">OpenAI (Live API)</MenuItem>
                    <MenuItem value="openrouter">OpenRouter (Multi-Provider)</MenuItem>
                  </Select>
                </FormControl>
              </Grid>

              <Grid item xs={12} sm={4}>
                <TextField
                  fullWidth
                  size="small"
                  label="Model Identifier"
                  value={modelId}
                  disabled={isRunning || provider === 'mock'}
                  onChange={(e) => setModelId(e.target.value)}
                  helperText={
                    provider === 'gemini'
                      ? 'e.g. gemini-3.8-flash, gemini-3.5-flash, gemini-3-pro'
                      : provider === 'openai'
                      ? 'e.g. gpt-4o, gpt-4o-mini'
                      : 'Model name or mock alias'
                  }
                />
              </Grid>

              <Grid item xs={12} sm={4} sx={{ display: 'flex', alignItems: 'flex-start' }}>
                <Button
                  type="submit"
                  variant="contained"
                  color="primary"
                  fullWidth
                  disabled={isRunning || selectedScenarios.length === 0}
                  startIcon={isRunning ? <CircularProgress size={18} color="inherit" /> : <PlayArrowRoundedIcon />}
                  sx={{ height: 40, fontWeight: 700 }}
                >
                  {isRunning ? 'Evaluating Scenarios...' : 'Execute Benchmark'}
                </Button>
              </Grid>
            </Grid>

            <Box>
              <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 700, display: 'block', mb: 1 }}>
                TARGET SCENARIOS:
              </Typography>
              <FormGroup row>
                {scenarios.map((scen) => (
                  <FormControlLabel
                    key={scen.id}
                    control={
                      <Checkbox
                        size="small"
                        checked={selectedScenarios.includes(scen.id)}
                        disabled={isRunning}
                        onChange={() => handleToggleScenario(scen.id)}
                      />
                    }
                    label={
                      <Typography variant="body2" sx={{ fontWeight: 500 }}>
                        {scen.title}
                      </Typography>
                    }
                  />
                ))}
              </FormGroup>
            </Box>
          </Stack>
        </form>
      </CardContent>
    </Card>
  );
};
