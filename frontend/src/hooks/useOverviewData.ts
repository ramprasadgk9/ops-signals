import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';

export function useOverviewData() {
  const runsQuery = useQuery({ queryKey: ['analysis-runs'], queryFn: api.analysisRuns });
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  // Latest run is always the first (newest) in the list
  const latestRun = useMemo(() => runsQuery.data?.[0] ?? null, [runsQuery.data]);

  // Selected run is either user-picked or falls back to latest
  const selectedRun = useMemo(() => {
    if (selectedRunId && runsQuery.data) {
      return runsQuery.data.find((r) => r.id === selectedRunId) ?? runsQuery.data[0];
    }
    return runsQuery.data?.[0];
  }, [selectedRunId, runsQuery.data]);

  // For SELECTED run (findings, signals, timeseries)
  const service = selectedRun?.service ?? '';
  const metric = selectedRun?.metric_name ?? '';
  const runId = selectedRun?.id ?? '';

  // For LATEST run (operational questions)
  const latestService = latestRun?.service ?? '';
  const latestMetric = latestRun?.metric_name ?? '';
  const latestRunId = latestRun?.id ?? '';

  // Questions for selected run (used for Top Findings context)
  const questionsQuery = useQuery({
    queryKey: ['questions-available', service, metric, runId],
    queryFn: () => api.availableQuestions(service, metric, runId),
    enabled: Boolean(service && metric && runId),
  });

  // Questions for LATEST run (used for Ask Operational Questions)
  const latestRunQuestionsQuery = useQuery({
    queryKey: ['questions-available-latest', latestService, latestMetric, latestRunId],
    queryFn: () => api.availableQuestions(latestService, latestMetric, latestRunId),
    enabled: Boolean(latestService && latestMetric && latestRunId),
  });

  const capabilityQuery = useQuery({ queryKey: ['capabilities'], queryFn: api.capabilities });

  const findingQuery = useQuery({
    queryKey: ['findings', service, metric, runId],
    queryFn: () => api.findings(service, metric, runId),
    enabled: Boolean(service && metric && runId),
  });

  const signalQuery = useQuery({
    queryKey: ['signals', service, metric, runId],
    queryFn: () => api.signals(service, metric, runId),
    enabled: Boolean(service && metric && runId),
  });

  const timeSeriesQuery = useQuery({
    queryKey: ['timeseries', service, metric, runId],
    queryFn: () => api.timeseries(service, metric, runId),
    enabled: Boolean(service && metric && runId),
  });

  return {
    runsQuery,
    latestRun,
    latestService,
    latestMetric,
    latestRunId,
    latestRunQuestionsQuery,
    questionsQuery,
    capabilityQuery,
    findingQuery,
    signalQuery,
    timeSeriesQuery,
    selectedRun,
    selectedRunId,
    setSelectedRunId,
    service,
    metric,
    runId,
  };
}
