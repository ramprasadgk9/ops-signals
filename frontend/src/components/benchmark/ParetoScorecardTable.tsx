import React, { useState } from 'react';
import {
  Box,
  Card,
  CardContent,
  Chip,
  IconButton,
  MenuItem,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material';
import VisibilityRoundedIcon from '@mui/icons-material/VisibilityRounded';
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded';
import WarningAmberRoundedIcon from '@mui/icons-material/WarningAmberRounded';
import ErrorOutlineRoundedIcon from '@mui/icons-material/ErrorOutlineRounded';
import type { BenchmarkScenarioResult, BenchmarkSystemRunResult } from '../../types/benchmark';

interface ParetoScorecardTableProps {
  scenarios: BenchmarkScenarioResult[];
  onSelectRun: (scenario: BenchmarkScenarioResult, systemKey: 'iam' | 'baseline_a' | 'baseline_b') => void;
}

export const ParetoScorecardTable: React.FC<ParetoScorecardTableProps> = ({ scenarios, onSelectRun }) => {
  const [scenarioFilter, setScenarioFilter] = useState<string>('all');

  const filteredScenarios = scenarioFilter === 'all'
    ? scenarios
    : scenarios.filter((s) => s.scenario === scenarioFilter);

  const renderStatusChip = (status: string) => {
    const norm = status.toUpperCase();
    if (norm === 'SUCCESS') {
      return (
        <Chip
          icon={<CheckCircleRoundedIcon fontSize="small" />}
          label="SUCCESS"
          color="success"
          size="small"
          sx={{ fontWeight: 700 }}
        />
      );
    }
    if (norm === 'PARTIAL') {
      return (
        <Chip
          icon={<WarningAmberRoundedIcon fontSize="small" />}
          label="PARTIAL"
          color="warning"
          size="small"
          sx={{ fontWeight: 700 }}
        />
      );
    }
    return (
      <Chip
        icon={<ErrorOutlineRoundedIcon fontSize="small" />}
        label="FAILED"
        color="error"
        size="small"
        sx={{ fontWeight: 700 }}
      />
    );
  };

  const renderJudgeRating = (run?: BenchmarkSystemRunResult) => {
    if (!run?.judge?.consensus) return <Typography variant="caption" color="text.secondary">N/A</Typography>;
    const { attribution, grounding, actionability } = run.judge.consensus;
    return (
      <Tooltip title={`Attribution: ${attribution}/5, Grounding: ${grounding}/5, Actionability: ${actionability}/5`}>
        <Chip
          label={`${attribution}/${grounding}/${actionability}`}
          size="small"
          variant="outlined"
          color={actionability >= 5 ? 'success' : actionability >= 4 ? 'info' : 'warning'}
          sx={{ fontWeight: 600 }}
        />
      </Tooltip>
    );
  };

  const systems: Array<{ key: 'iam' | 'baseline_a' | 'baseline_b'; label: string; tag: string }> = [
    { key: 'iam', label: 'IAM Engine', tag: 'Deterministic' },
    { key: 'baseline_a', label: 'Baseline A', tag: 'Raw ReAct' },
    { key: 'baseline_b', label: 'Baseline B', tag: 'Signals ReAct' },
  ];

  return (
    <Card variant="outlined" sx={{ borderRadius: 2 }}>
      <CardContent>
        <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 2 }}>
          <Stack spacing={0.5}>
            <Typography variant="h6" sx={{ fontWeight: 700 }}>
              Multi-Scenario Pareto Frontier Scorecard
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Side-by-side diagnostic efficacy, calibrated judge ratings, and economic costs.
            </Typography>
          </Stack>
          <Box sx={{ minWidth: 220 }}>
            <Select
              size="small"
              fullWidth
              value={scenarioFilter}
              onChange={(e) => setScenarioFilter(e.target.value)}
            >
              <MenuItem value="all">All Scenarios ({scenarios.length})</MenuItem>
              {scenarios.map((s) => (
                <MenuItem key={s.scenario} value={s.scenario}>
                  {s.scenario.replace('scenario_', '').replace(/_/g, ' ')}
                </MenuItem>
              ))}
            </Select>
          </Box>
        </Stack>

        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow sx={{ bgcolor: 'action.hover' }}>
                <TableCell sx={{ fontWeight: 700 }}>Scenario & Entity</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>System</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>Status</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>Diagnosed Cause</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>Evidence F1</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>Judge (Attr/Grd/Act)</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>Tokens</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>Cost ($)</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>Latency</TableCell>
                <TableCell align="center" sx={{ fontWeight: 700 }}>Details</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {filteredScenarios.map((scenario) => {
                const scenarioName = scenario.scenario.replace('scenario_', '').replace(/_/g, ' ');
                const gtEntity = scenario.ground_truth.entity || 'Unknown';
                const gtCause = scenario.ground_truth.root_cause || 'Unknown';

                return systems.map((sys, idx) => {
                  const run = scenario[sys.key];
                  if (!run) return null;

                  return (
                    <TableRow
                      key={`${scenario.scenario}-${sys.key}`}
                      hover
                      sx={{
                        borderBottom: idx === systems.length - 1 ? '2px solid rgba(15, 23, 42, 0.12)' : undefined,
                        bgcolor: sys.key === 'iam' ? 'rgba(46, 125, 50, 0.03)' : undefined,
                      }}
                    >
                      {idx === 0 ? (
                        <TableCell rowSpan={systems.length} sx={{ verticalAlign: 'top', pt: 2 }}>
                          <Typography variant="subtitle2" sx={{ fontWeight: 700, textTransform: 'capitalize' }}>
                            {scenarioName}
                          </Typography>
                          <Typography variant="caption" color="text.secondary" display="block">
                            Culprit: <strong>{gtEntity}</strong>
                          </Typography>
                          <Typography variant="caption" color="text.secondary" display="block">
                            Truth: <strong>{gtCause}</strong>
                          </Typography>
                        </TableCell>
                      ) : null}
                      <TableCell>
                        <Stack direction="row" spacing={1} alignItems="center">
                          <Typography variant="body2" sx={{ fontWeight: sys.key === 'iam' ? 700 : 500 }}>
                            {sys.label}
                          </Typography>
                          <Chip
                            label={sys.tag}
                            size="small"
                            variant={sys.key === 'iam' ? 'filled' : 'outlined'}
                            color={sys.key === 'iam' ? 'success' : 'default'}
                            sx={{ height: 20, fontSize: '0.7rem' }}
                          />
                        </Stack>
                      </TableCell>
                      <TableCell>{renderStatusChip(run.status)}</TableCell>
                      <TableCell>
                        <Typography variant="body2" sx={{ fontFamily: 'monospace', fontWeight: 600 }}>
                          {run.root_cause}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>
                          {(run.evidence_f1 ?? 0).toFixed(2)}
                        </Typography>
                      </TableCell>
                      <TableCell>{renderJudgeRating(run)}</TableCell>
                      <TableCell>
                        <Typography variant="body2" color={run.tokens === 0 ? 'success.main' : 'text.primary'}>
                          {run.tokens.toLocaleString()}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2" color={run.cost_usd === 0 ? 'success.main' : 'text.primary'} sx={{ fontWeight: 600 }}>
                          ${run.cost_usd.toFixed(4)}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2">
                          {run.execution_time_seconds.toFixed(3)}s
                        </Typography>
                      </TableCell>
                      <TableCell align="center">
                        <Tooltip title="Inspect Trajectory & Evidence">
                          <IconButton
                            size="small"
                            color="primary"
                            onClick={() => onSelectRun(scenario, sys.key)}
                          >
                            <VisibilityRoundedIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      </TableCell>
                    </TableRow>
                  );
                });
              })}
            </TableBody>
          </Table>
        </TableContainer>
      </CardContent>
    </Card>
  );
};
