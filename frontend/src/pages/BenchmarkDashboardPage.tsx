import React, { useState } from 'react';
import {
  Alert,
  Box,
  Card,
  CardContent,
  CircularProgress,
  Divider,
  Stack,
  Tab,
  Tabs,
  Typography,
} from '@mui/material';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import CompareArrowsRoundedIcon from '@mui/icons-material/CompareArrowsRounded';
import { api } from '../api/queries';
import { ParetoMetricsOverview } from '../components/benchmark/ParetoMetricsOverview';
import { ParetoScorecardTable } from '../components/benchmark/ParetoScorecardTable';
import { BenchmarkAnalysisCard } from '../components/benchmark/BenchmarkAnalysisCard';
import { ScenarioTrajectoryDrawer } from '../components/benchmark/ScenarioTrajectoryDrawer';
import { BenchmarkRunControls } from '../components/benchmark/BenchmarkRunControls';
import type {
  BenchmarkReportResponse,
  BenchmarkRunRequestPayload,
  BenchmarkScenarioDescriptor,
  BenchmarkScenarioResult,
} from '../types/benchmark';

export function BenchmarkDashboardPage() {
  const queryClient = useQueryClient();
  const [selectedScenario, setSelectedScenario] = useState<BenchmarkScenarioResult | null>(null);
  const [selectedSystemKey, setSelectedSystemKey] = useState<'iam' | 'baseline_a' | 'baseline_b' | null>(null);
  const [drawerOpen, setDrawerOpen] = useState<boolean>(false);
  const [runError, setRunError] = useState<string | null>(null);

  const {
    data: scenarios = [],
    isLoading: isScenariosLoading,
  } = useQuery<BenchmarkScenarioDescriptor[]>({
    queryKey: ['benchmark-scenarios'],
    queryFn: () => api.benchmarkScenarios(),
  });

  const {
    data: report,
    isLoading: isReportLoading,
    error: reportError,
  } = useQuery<BenchmarkReportResponse>({
    queryKey: ['benchmark-report'],
    queryFn: () => api.benchmarkReport(),
  });

  const runMutation = useMutation({
    mutationFn: (payload: BenchmarkRunRequestPayload) => api.runBenchmark(payload),
    onSuccess: (updatedReport) => {
      queryClient.setQueryData(['benchmark-report'], updatedReport);
      setRunError(null);
    },
    onError: (err: any) => {
      const msg = err?.message || 'Benchmark run failed. Ensure API keys are configured.';
      setRunError(msg);
    },
  });

  const handleSelectRun = (scenario: BenchmarkScenarioResult, systemKey: 'iam' | 'baseline_a' | 'baseline_b') => {
    setSelectedScenario(scenario);
    setSelectedSystemKey(systemKey);
    setDrawerOpen(true);
  };

  const handleCloseDrawer = () => {
    setDrawerOpen(false);
  };

  const handleRunBenchmark = async (payload: BenchmarkRunRequestPayload) => {
    setRunError(null);
    await runMutation.mutateAsync(payload);
  };

  if (isReportLoading || isScenariosLoading) {
    return (
      <Stack alignItems="center" justifyContent="center" sx={{ py: 12 }}>
        <CircularProgress />
        <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
          Loading Benchmark Evaluation Results...
        </Typography>
      </Stack>
    );
  }

  if (reportError || !report) {
    return (
      <Stack sx={{ p: 4 }} spacing={2}>
        <Alert severity="error">
          Failed to load benchmark report. Please ensure the backend service is running.
        </Alert>
      </Stack>
    );
  }

  return (
    <Stack spacing={3}>
      {/* Header Banner */}
      <Card variant="outlined" sx={{ borderRadius: 2 }}>
        <CardContent>
          <Stack spacing={1}>
            <Stack direction="row" alignItems="center" spacing={1.5}>
              <CompareArrowsRoundedIcon color="primary" sx={{ fontSize: 32 }} />
              <Typography variant="h4" sx={{ fontWeight: 800 }}>
                IAM vs. LLM Benchmark & Evaluation
              </Typography>
            </Stack>
            <Typography variant="body1" color="text.secondary">
              Empirical Pareto evaluation comparing deterministic Incident Analysis & Management (IAM)
              against frontier agentic LLM SRE baselines across multi-source incident scenarios.
            </Typography>
            {report.generated_at && (
              <Typography variant="caption" color="text.secondary">
                Report generated: {new Date(report.generated_at).toLocaleString()}
              </Typography>
            )}
          </Stack>
        </CardContent>
      </Card>

      {/* KPI Overview */}
      <ParetoMetricsOverview report={report} />

      {/* Execution Controls */}
      <BenchmarkRunControls
        scenarios={scenarios}
        isRunning={runMutation.isPending}
        onRun={handleRunBenchmark}
        error={runError}
      />

      {/* Pareto Scorecard Table */}
      <ParetoScorecardTable
        scenarios={report.scenarios}
        onSelectRun={handleSelectRun}
      />

      {/* Benchmark Architectural Analysis & Strategic Insights */}
      <BenchmarkAnalysisCard report={report} />

      {/* Trajectory Drawer */}
      <ScenarioTrajectoryDrawer
        open={drawerOpen}
        onClose={handleCloseDrawer}
        scenario={selectedScenario}
        systemKey={selectedSystemKey}
      />
    </Stack>
  );
}
