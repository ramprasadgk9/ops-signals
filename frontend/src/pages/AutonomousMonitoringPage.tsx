import { useState } from 'react';
import { Box, Stack } from '@mui/material';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/queries';
import { AutonomousConfigurePanel } from '../autonomous/AutonomousConfigurePanel';
import { AutonomousMonitoringDashboard } from '../autonomous/AutonomousMonitoringDashboard';
import { buildAutonomousDashboardData, latestFinishedPolicyRun, type AutonomousPreviewResponse, type AutonomousRunResponse, type MonitoringCategory } from '../autonomous/dashboardModel';
import { FeatureNeedsSource } from '../components/FeatureNeedsSource';
import { PageHeader } from '../standalone/components';
import { useWebPermissions } from '../hooks/useWebPermissions';

export function AutonomousMonitoringPage() {
  const queryClient = useQueryClient();
  // A Viewer sees what runs and what it found, without the set-up part (backend/app/roles.py READ_ONLY_PAGES).
  const readOnly = useWebPermissions().isReadOnly('/autonomous-monitoring');
  const [runResult, setRunResult] = useState<AutonomousRunResponse | null>(null);
  const [previewResult, setPreviewResult] = useState<AutonomousPreviewResponse | null>(null);
  const [enableCategoryRequest, setEnableCategoryRequest] = useState<MonitoringCategory | null>(null);
  const [previewNowSignal, setPreviewNowSignal] = useState(false);
  const [isPreviewingNow, setIsPreviewingNow] = useState(false);

  const refreshAutonomousData = () => {
    void queryClient.invalidateQueries({ queryKey: ['overview-autonomous-policy-runs'] });
    void queryClient.invalidateQueries({ queryKey: ['autonomous-policy-runs'] });
    void queryClient.invalidateQueries({ queryKey: ['overview-autonomous-policy-run-jobs'] });
    void queryClient.invalidateQueries({ queryKey: ['findings-overview', '24h'] });
    void queryClient.invalidateQueries({ queryKey: ['cases-overview'] });
    void queryClient.invalidateQueries({ queryKey: ['behavior-findings-overview'] });
  };

  const handleRunComplete = (result: AutonomousRunResponse) => {
    setRunResult(result);
    refreshAutonomousData();
  };

  // The overview shows a manual run from this page when there is one, and otherwise the latest
  // finished scheduled run. It used to show only manual runs, and once a scheduled policy was
  // saved the page no longer offers a manual Run button - so the overview stayed empty.
  const policyRunsQuery = useQuery({
    queryKey: ['overview-autonomous-policy-runs'],
    queryFn: () => api.autonomousPolicyRuns(10),
    retry: false,
  });
  const scheduledRun = runResult ? undefined : latestFinishedPolicyRun(policyRunsQuery.data ?? []);
  const scheduledRunJobsQuery = useQuery({
    queryKey: ['overview-autonomous-policy-run-jobs', scheduledRun?.id],
    queryFn: () => api.autonomousPolicyRunJobs(scheduledRun!.id),
    retry: false,
    enabled: Boolean(scheduledRun),
  });
  const hasRun = Boolean(runResult || scheduledRun);

  const findingsQuery = useQuery({
    queryKey: ['findings-overview', '24h'],
    queryFn: () => api.findings(undefined, undefined, undefined, '24h'),
    enabled: hasRun,
  });
  const casesQuery = useQuery({
    queryKey: ['cases-overview'],
    queryFn: () => api.cases(200),
    enabled: hasRun,
  });
  const behaviorsQuery = useQuery({
    queryKey: ['behavior-findings-overview'],
    queryFn: () => api.behaviorFindings(),
    enabled: hasRun,
  });

  const dashboardState = !hasRun
    ? policyRunsQuery.isLoading ? 'loading' : 'idle'
    : findingsQuery.isLoading || casesQuery.isLoading || behaviorsQuery.isLoading || policyRunsQuery.isLoading || scheduledRunJobsQuery.isLoading
      ? 'loading'
      : findingsQuery.error || casesQuery.error || behaviorsQuery.error
        ? 'error'
        : 'ready';

  const scheduledRunAnalysisRunIds = (scheduledRunJobsQuery.data ?? [])
    .map((job) => job.analysis_run_id)
    .filter((id): id is string => typeof id === 'string' && id.length > 0);
  const scheduledWindow = (scheduledRun?.policy_snapshot?.execution_policy as { analysis_window?: string } | undefined)?.analysis_window;

  const dashboardData = buildAutonomousDashboardData({
    findings: findingsQuery.data ?? [],
    cases: casesQuery.data ?? [],
    analysisRuns: [],
    behaviorFindings: behaviorsQuery.data ?? [],
    policyRuns: policyRunsQuery.data ?? [],
    previewResult,
    runResult,
    scheduledRunAnalysisRunIds,
    caseHref: (caseItem) => `/cases/${caseItem.id}`,
  });

  return (
    <Box sx={{ mx: { xs: -2, md: 0 }, p: { xs: 1, md: 0 } }}>
      <Stack spacing={3}>
        {readOnly ? (
          <PageHeader title="Autonomous Analysis" subtitle="What runs on a schedule, and what it found." />
        ) : (
          <PageHeader title="Autonomous Analysis Configure" subtitle="Configure scope, monitoring categories, execution limits, and run autonomous analysis." />
        )}
        <FeatureNeedsSource feature="autonomous_analysis">
          <AutonomousConfigurePanel
            onRunComplete={handleRunComplete}
            onPreviewComplete={setPreviewResult}
            enableCategoryRequest={enableCategoryRequest}
            onEnableCategoryHandled={() => setEnableCategoryRequest(null)}
            previewNowSignal={previewNowSignal}
            onPreviewNowHandled={() => setPreviewNowSignal(false)}
            onPreviewNowStateChange={setIsPreviewingNow}
            readOnly={readOnly}
          />
          <Box id="autonomous-overview">
            <AutonomousMonitoringDashboard
              data={dashboardData}
              context={{ timeWindow: runResult?.analysis_window ?? scheduledWindow, policy: 'Current monitoring policy' }}
              state={dashboardState}
              error={findingsQuery.error || casesQuery.error || behaviorsQuery.error ? 'Autonomous summary unavailable.' : null}
              onRetry={refreshAutonomousData}
              onEnableCategory={readOnly ? undefined : setEnableCategoryRequest}
              onPreviewNow={() => setPreviewNowSignal(true)}
              isPreviewingNow={isPreviewingNow}
            />
          </Box>
        </FeatureNeedsSource>
      </Stack>
    </Box>
  );
}
