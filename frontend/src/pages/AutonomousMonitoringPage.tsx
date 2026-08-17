import { Box } from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import { AutonomousMonitoringDashboard } from '../autonomous/AutonomousMonitoringDashboard';
import { buildAutonomousDashboardData } from '../autonomous/dashboardModel';
import { api } from '../api/queries';
import { LoadingSkeleton } from '../components/LoadingSkeleton';

const completedRunStatuses = new Set(['completed', 'partial']);

export function AutonomousMonitoringPage() {
  const findingsQuery = useQuery({ queryKey: ['autonomous-findings', '24h'], queryFn: () => api.findings(undefined, undefined, undefined, '24h') });
  const casesQuery = useQuery({ queryKey: ['autonomous-cases'], queryFn: () => api.cases(100) });
  const runsQuery = useQuery({ queryKey: ['autonomous-analysis-runs'], queryFn: api.analysisRuns });
  const behaviorQuery = useQuery({ queryKey: ['autonomous-behavior-findings'], queryFn: () => api.behaviorFindings() });
  const policyRunsQuery = useQuery({ queryKey: ['autonomous-policy-runs'], queryFn: () => api.autonomousPolicyRuns(25), retry: false });

  const isLoading = findingsQuery.isLoading || casesQuery.isLoading || runsQuery.isLoading || behaviorQuery.isLoading || policyRunsQuery.isLoading;
  if (isLoading) return <LoadingSkeleton />;

  const policyRuns = policyRunsQuery.data ?? [];
  const hasCompletedAutonomousRun = policyRuns.some((run) => completedRunStatuses.has(String(run.status ?? '').toLowerCase()));

  const data = buildAutonomousDashboardData({
    findings: findingsQuery.data ?? [],
    cases: casesQuery.data ?? [],
    analysisRuns: runsQuery.data ?? [],
    behaviorFindings: behaviorQuery.data ?? [],
    policyRuns,
    findingHref: () => '/findings?window=24h',
    caseHref: (caseItem) => `/cases/${caseItem.id}`,
  });

  const partialError = [
    findingsQuery.error ? 'Findings unavailable.' : '',
    casesQuery.error ? 'Cases unavailable.' : '',
    runsQuery.error ? 'Analysis runs unavailable.' : '',
    behaviorQuery.error ? 'Behavior findings unavailable.' : '',
    policyRunsQuery.error ? 'Autonomous policy run history unavailable.' : '',
  ].filter(Boolean).join(' ');
  const state = policyRunsQuery.error && !hasCompletedAutonomousRun ? 'error' : hasCompletedAutonomousRun ? 'ready' : 'idle';
  const retry = () => {
    void findingsQuery.refetch();
    void casesQuery.refetch();
    void runsQuery.refetch();
    void behaviorQuery.refetch();
    void policyRunsQuery.refetch();
  };

  return (
    <Box sx={{ mx: { xs: -2, md: 0 }, p: { xs: 1, md: 0 } }}>
      <AutonomousMonitoringDashboard
        data={data}
        context={{
          environment: 'Production',
          datasource: 'Prometheus',
          policy: 'Current monitoring policy',
          timeWindow: 'Last 24 hours',
          sourceLabel: 'Prometheus',
        }}
        state={state}
        error={partialError ? 'Some autonomous summary data could not be refreshed.' : null}
        onRetry={retry}
      />
    </Box>
  );
}
