import { Box } from '@mui/material';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { AutonomousMonitoringDashboard } from '../autonomous/AutonomousMonitoringDashboard';
import { buildAutonomousDashboardData } from '../autonomous/dashboardModel';
import { api, type FindingsWindow } from '../api/queries';
import { LoadingSkeleton } from '../components/LoadingSkeleton';

const completedRunStatuses = new Set(['completed', 'partial']);

export function AutonomousMonitoringPage() {
  const [askQuestion, setAskQuestion] = useState('');
  const [lookupWindow, setLookupWindow] = useState<FindingsWindow>('24h');
  const [lookupQuery, setLookupQuery] = useState('');
  const [lookupService, setLookupService] = useState('');
  const [lookupMetricName, setLookupMetricName] = useState('');

  const findingsQuery = useQuery({ queryKey: ['autonomous-findings', '24h'], queryFn: () => api.findings(undefined, undefined, undefined, '24h') });
  const casesQuery = useQuery({ queryKey: ['autonomous-cases'], queryFn: () => api.cases(100) });
  const runsQuery = useQuery({ queryKey: ['autonomous-analysis-runs'], queryFn: api.analysisRuns });
  const behaviorQuery = useQuery({ queryKey: ['autonomous-behavior-findings'], queryFn: () => api.behaviorFindings() });
  const policyRunsQuery = useQuery({ queryKey: ['autonomous-policy-runs'], queryFn: () => api.autonomousPolicyRuns(25), retry: false });
  const policyRuns = policyRunsQuery.data ?? [];
  const latestPolicyRunId = policyRuns[0]?.policy_run_id ?? policyRuns[0]?.id ?? null;
  const askMutation = useMutation({
    mutationFn: (question: string) => api.autonomousQuestionAnswer({
      question,
      policy_run_id: latestPolicyRunId,
      window: lookupWindow,
      service: lookupService.trim() || undefined,
      metric_name: lookupMetricName.trim() || undefined,
    }),
  });
  const lookupFindingsQuery = useQuery({
    queryKey: ['autonomous-findings-search', lookupWindow, lookupQuery, lookupService, lookupMetricName],
    queryFn: () => api.findingsSearch({
      window: lookupWindow,
      q: lookupQuery.trim() || undefined,
      service: lookupService.trim() || undefined,
      metric_name: lookupMetricName.trim() || undefined,
      limit: 8,
    }),
  });

  const isLoading = findingsQuery.isLoading || casesQuery.isLoading || runsQuery.isLoading || behaviorQuery.isLoading || policyRunsQuery.isLoading;
  if (isLoading) return <LoadingSkeleton />;

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
    void lookupFindingsQuery.refetch();
  };
  const ask = (question?: string) => {
    const nextQuestion = question ?? askQuestion;
    if (!nextQuestion.trim()) return;
    if (question) setAskQuestion(question);
    askMutation.mutate(nextQuestion);
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
        askOps={{
          question: askQuestion,
          answer: askMutation.data ?? null,
          isLoading: askMutation.isPending,
          error: askMutation.error ? 'Could not answer from autonomous evidence. Check backend logs and try again.' : null,
          onQuestionChange: setAskQuestion,
          onAsk: ask,
        }}
        findingsLookup={{
          window: lookupWindow,
          query: lookupQuery,
          service: lookupService,
          metricName: lookupMetricName,
          findings: lookupFindingsQuery.data ?? [],
          isLoading: lookupFindingsQuery.isFetching,
          error: lookupFindingsQuery.error ? 'Could not search stored findings. Check backend connectivity.' : null,
          onWindowChange: setLookupWindow,
          onQueryChange: setLookupQuery,
          onServiceChange: setLookupService,
          onMetricNameChange: setLookupMetricName,
          onSearch: () => void lookupFindingsQuery.refetch(),
          onAskAboutFinding: (finding) => ask(`What should I investigate first for ${finding.service} / ${finding.metric_name}?`),
        }}
      />
    </Box>
  );
}
