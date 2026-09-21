import { useState } from 'react';
import { Box, Stack } from '@mui/material';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/queries';
import { AutonomousConfigurePanel } from '../autonomous/AutonomousConfigurePanel';
import { AutonomousMonitoringDashboard } from '../autonomous/AutonomousMonitoringDashboard';
import { buildAutonomousDashboardData, type AutonomousPreviewResponse, type AutonomousRunResponse, type MonitoringCategory } from '../autonomous/dashboardModel';
import { PageHeader } from '../standalone/components';

export function AutonomousMonitoringPage() {
  const queryClient = useQueryClient();
  const [runResult, setRunResult] = useState<AutonomousRunResponse | null>(null);
  const [previewResult, setPreviewResult] = useState<AutonomousPreviewResponse | null>(null);
  const [enableCategoryRequest, setEnableCategoryRequest] = useState<MonitoringCategory | null>(null);
  const [previewNowSignal, setPreviewNowSignal] = useState(false);
  const [isPreviewingNow, setIsPreviewingNow] = useState(false);

  const refreshAutonomousData = () => {
    void queryClient.invalidateQueries({ queryKey: ['overview-autonomous-policy-runs'] });
    void queryClient.invalidateQueries({ queryKey: ['autonomous-policy-runs'] });
    void queryClient.invalidateQueries({ queryKey: ['findings-overview', '24h'] });
    void queryClient.invalidateQueries({ queryKey: ['cases-overview'] });
    void queryClient.invalidateQueries({ queryKey: ['behavior-findings-overview'] });
  };

  const handleRunComplete = (result: AutonomousRunResponse) => {
    setRunResult(result);
    refreshAutonomousData();
  };

  const findingsQuery = useQuery({
    queryKey: ['findings-overview', '24h'],
    queryFn: () => api.findings(undefined, undefined, undefined, '24h'),
    enabled: Boolean(runResult),
  });
  const casesQuery = useQuery({
    queryKey: ['cases-overview'],
    queryFn: () => api.cases(200),
    enabled: Boolean(runResult),
  });
  const behaviorsQuery = useQuery({
    queryKey: ['behavior-findings-overview'],
    queryFn: () => api.behaviorFindings(),
    enabled: Boolean(runResult),
  });
  const policyRunsQuery = useQuery({
    queryKey: ['overview-autonomous-policy-runs'],
    queryFn: () => api.autonomousPolicyRuns(10),
    retry: false,
    enabled: Boolean(runResult),
  });

  const dashboardState = !runResult
    ? 'idle'
    : findingsQuery.isLoading || casesQuery.isLoading || behaviorsQuery.isLoading || policyRunsQuery.isLoading
      ? 'loading'
      : findingsQuery.error || casesQuery.error || behaviorsQuery.error
        ? 'error'
        : 'ready';

  const dashboardData = buildAutonomousDashboardData({
    findings: findingsQuery.data ?? [],
    cases: casesQuery.data ?? [],
    analysisRuns: [],
    behaviorFindings: behaviorsQuery.data ?? [],
    policyRuns: policyRunsQuery.data ?? [],
    previewResult,
    runResult,
    findingHref: () => '/findings?window=24h',
    caseHref: (caseItem) => `/cases/${caseItem.id}`,
  });

  return (
    <Box sx={{ mx: { xs: -2, md: 0 }, p: { xs: 1, md: 0 } }}>
      <Stack spacing={3}>
        <PageHeader title="Autonomous Analysis Configure" subtitle="Configure scope, monitoring categories, execution limits, and run autonomous analysis." />
        <AutonomousConfigurePanel
          onRunComplete={handleRunComplete}
          onPreviewComplete={setPreviewResult}
          enableCategoryRequest={enableCategoryRequest}
          onEnableCategoryHandled={() => setEnableCategoryRequest(null)}
          previewNowSignal={previewNowSignal}
          onPreviewNowHandled={() => setPreviewNowSignal(false)}
          onPreviewNowStateChange={setIsPreviewingNow}
        />
        <Box id="autonomous-overview">
          <AutonomousMonitoringDashboard
            data={dashboardData}
            context={{ timeWindow: runResult?.analysis_window, policy: 'Current monitoring policy' }}
            state={dashboardState}
            error={findingsQuery.error || casesQuery.error || behaviorsQuery.error ? 'Autonomous summary unavailable.' : null}
            onRetry={refreshAutonomousData}
            onEnableCategory={setEnableCategoryRequest}
            onPreviewNow={() => setPreviewNowSignal(true)}
            isPreviewingNow={isPreviewingNow}
          />
        </Box>
      </Stack>
    </Box>
  );
}
