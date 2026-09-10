import React from 'react';
import { Box, Card, CardContent, Grid, Stack, Typography, Chip } from '@mui/material';
import SavingsRoundedIcon from '@mui/icons-material/SavingsRounded';
import SpeedRoundedIcon from '@mui/icons-material/SpeedRounded';
import MemoryRoundedIcon from '@mui/icons-material/MemoryRounded';
import GavelRoundedIcon from '@mui/icons-material/GavelRounded';
import type { BenchmarkReportResponse } from '../../types/benchmark';

interface ParetoMetricsOverviewProps {
  report: BenchmarkReportResponse;
}

export const ParetoMetricsOverview: React.FC<ParetoMetricsOverviewProps> = ({ report }) => {
  const { summary } = report;
  const { iam, baseline_a, baseline_b, pareto } = summary;

  const totalAgentTokens = baseline_a.total_tokens + baseline_b.total_tokens;
  const totalAgentCost = (baseline_a.total_cost_usd + baseline_b.total_cost_usd).toFixed(4);

  return (
    <Grid container spacing={2}>
      <Grid item xs={12} sm={6} md={3}>
        <Card variant="outlined" sx={{ height: '100%', borderRadius: 2 }}>
          <CardContent>
            <Stack spacing={1}>
              <Stack direction="row" alignItems="center" justifyContent="space-between">
                <Typography variant="overline" color="text.secondary" sx={{ fontWeight: 700 }}>
                  IAM Incident Cost
                </Typography>
                <SavingsRoundedIcon color="success" />
              </Stack>
              <Typography variant="h4" sx={{ fontWeight: 800, color: 'success.main' }}>
                $0.00
              </Typography>
              <Typography variant="caption" color="text.secondary">
                100% cost reduction vs LLM agents (${totalAgentCost} spent)
              </Typography>
              <Box sx={{ pt: 0.5 }}>
                <Chip label="Deterministic Algorithms" size="small" color="success" variant="outlined" />
              </Box>
            </Stack>
          </CardContent>
        </Card>
      </Grid>

      <Grid item xs={12} sm={6} md={3}>
        <Card variant="outlined" sx={{ height: '100%', borderRadius: 2 }}>
          <CardContent>
            <Stack spacing={1}>
              <Stack direction="row" alignItems="center" justifyContent="space-between">
                <Typography variant="overline" color="text.secondary" sx={{ fontWeight: 700 }}>
                  Token Consumption
                </Typography>
                <MemoryRoundedIcon color="primary" />
              </Stack>
              <Typography variant="h4" sx={{ fontWeight: 800, color: 'primary.main' }}>
                0
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {pareto.token_reduction_vs_a_pct}% reduction vs {totalAgentTokens.toLocaleString()} baseline tokens
              </Typography>
              <Box sx={{ pt: 0.5 }}>
                <Chip label="Zero Model Quota" size="small" color="primary" variant="outlined" />
              </Box>
            </Stack>
          </CardContent>
        </Card>
      </Grid>

      <Grid item xs={12} sm={6} md={3}>
        <Card variant="outlined" sx={{ height: '100%', borderRadius: 2 }}>
          <CardContent>
            <Stack spacing={1}>
              <Stack direction="row" alignItems="center" justifyContent="space-between">
                <Typography variant="overline" color="text.secondary" sx={{ fontWeight: 700 }}>
                  Triage Latency
                </Typography>
                <SpeedRoundedIcon color="warning" />
              </Stack>
              <Typography variant="h4" sx={{ fontWeight: 800, color: 'text.primary' }}>
                {(iam.avg_latency_s * 1000).toFixed(0)} ms
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Instant localized triage vs multi-turn LLM inference
              </Typography>
              <Box sx={{ pt: 0.5 }}>
                <Chip label="Real-time Streaming" size="small" color="warning" variant="outlined" />
              </Box>
            </Stack>
          </CardContent>
        </Card>
      </Grid>

      <Grid item xs={12} sm={6} md={3}>
        <Card variant="outlined" sx={{ height: '100%', borderRadius: 2 }}>
          <CardContent>
            <Stack spacing={1}>
              <Stack direction="row" alignItems="center" justifyContent="space-between">
                <Typography variant="overline" color="text.secondary" sx={{ fontWeight: 700 }}>
                  Judge Consensus
                </Typography>
                <GavelRoundedIcon color="info" />
              </Stack>
              <Typography variant="h4" sx={{ fontWeight: 800, color: 'info.main' }}>
                {iam.avg_judge_actionability.toFixed(1)} / 5.0
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Panel SRE Likert rating (Attribution & Actionability)
              </Typography>
              <Box sx={{ pt: 0.5 }}>
                <Chip label="Calibrated Rubric" size="small" color="info" variant="outlined" />
              </Box>
            </Stack>
          </CardContent>
        </Card>
      </Grid>
    </Grid>
  );
};
