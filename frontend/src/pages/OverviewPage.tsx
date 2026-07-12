import { useMemo, useState } from 'react';
import { Box, Grid2 as Grid, Typography, Stack, Card, CardContent, Button } from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { AnalysisRunSelector } from '../components/AnalysisRunSelector';
import { AnswerDrawer } from '../components/AnswerDrawer';
import { CurrentAnalysisContext } from '../components/CurrentAnalysisContext';
import { CsvUploadPanel } from '../components/CsvUploadPanel';
import { EmptyState } from '../components/EmptyState';
import { ErrorState } from '../components/ErrorState';
import { FindingDetailsDrawer } from '../components/FindingDetailsDrawer';
import { HealthScoreCard } from '../components/HealthScoreCard';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { QuestionGrid } from '../components/QuestionGrid';
import { SignalDetailsDrawer } from '../components/SignalDetailsDrawer';
import { TopFindingsList } from '../components/TopFindingsList';
import { useOverviewData } from '../hooks/useOverviewData';
import type { Question, Signal, Finding } from '../types';

export function OverviewPage() {
  const { runsQuery, selectedRun, setSelectedRunId, service, metric, runId } = useOverviewData();
  const [activeQuestion, setActiveQuestion] = useState<Question | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedSignal, setSelectedSignal] = useState<Signal | null>(null);
  const [signalDrawerOpen, setSignalDrawerOpen] = useState(false);
  const [selectedFinding, setSelectedFinding] = useState<Finding | null>(null);
  const [findingDrawerOpen, setFindingDrawerOpen] = useState(false);

  // Questions for SELECTED run (not latest)
  const questionsQuery = useQuery({
    queryKey: ['questions-available', service, metric, runId],
    queryFn: () => api.availableQuestions(service, metric, runId),
    enabled: Boolean(service && metric && runId),
  });

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

  const answerQuery = useQuery({
    queryKey: ['answer', activeQuestion?.id, service, metric, runId],
    queryFn: () => api.questionAnswer(activeQuestion!.id, service, metric, runId),
    enabled: Boolean(activeQuestion?.id && service && metric && runId),
  });

  // Calculate health metrics from findings
  const health = useMemo(() => {
    const findings = findingQuery.data ?? [];
    
    // Count findings by health status
    const criticalCount = findings.filter((f) => f.health_status === 'critical').length;
    const significantCount = findings.filter((f) => f.health_status === 'significant').length;
    
    // Calculate score impacts
    const criticalImpact = Math.min(40, criticalCount * 20);
    const significantImpact = Math.min(30, significantCount * 10);
    
    const score = Math.max(0, 100 - (criticalImpact + significantImpact));
    const status = score >= 80 ? 'Healthy' : score >= 60 ? 'Watch' : score >= 30 ? 'Needs Attention' : 'Critical';
    
    return {
      score: Math.round(score),
      status,
      breakdown: {
        critical: -criticalImpact,
        significant: -significantImpact,
        normal: 0,
      },
    };
  }, [findingQuery.data]);

  if (runsQuery.isLoading) return <LoadingSkeleton />;
  if (runsQuery.error) return <ErrorState message="Failed to load analysis runs" />;
  if (!selectedRun) {
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        <CsvUploadPanel />
        <EmptyState title="No analysis runs" description="Upload a CSV above to generate operational intelligence." />
      </Box>
    );
  }

  const recentRuns = (runsQuery.data ?? []).slice(1, 6);

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <CsvUploadPanel />

      {/* Analysis Run Selector */}
      <AnalysisRunSelector 
        runs={runsQuery.data ?? []} 
        value={selectedRun.id} 
        onChange={setSelectedRunId} 
      />

      {/* Current Analysis Context */}
      <CurrentAnalysisContext run={selectedRun} />

      {/* Operational Health */}
      <Grid container spacing={2}>
        <Grid size={{ xs: 12 }}>
          <HealthScoreCard 
            score={health.score} 
            status={health.status}
            breakdown={health.breakdown}
          />
        </Grid>
      </Grid>

      {/* Ask Questions About This Analysis Run */}
      <Box>
        <Typography variant="subtitle1" sx={{ mb: 2, fontWeight: 600 }}>
          Ask Questions About This Analysis Run
        </Typography>
        <QuestionGrid
          questions={(questionsQuery.data ?? []) as Question[]}
          onOpen={(question) => {
            setActiveQuestion(question);
            setDrawerOpen(true);
          }}
        />
      </Box>

      {/* Top Findings */}
      <Box>
        <Typography variant="subtitle1" sx={{ mb: 2, fontWeight: 600 }}>
          Top Findings
        </Typography>
        <TopFindingsList 
          findings={findingQuery.data ?? []}
          onViewDetails={(finding) => {
            setSelectedFinding(finding);
            setFindingDrawerOpen(true);
          }}
        />
      </Box>

      {/* Metric Timeline */}
      <Box>
        <Typography variant="subtitle1" sx={{ mb: 2, fontWeight: 600 }}>
          Metric Timeline
        </Typography>
        {/* The timeline is displayed in the AnswerDrawer, could add a standalone view here */}
      </Box>

      {/* Recent Runs */}
      {recentRuns.length > 0 && (
        <Box>
          <Typography variant="subtitle1" sx={{ mb: 2, fontWeight: 600 }}>
            Recent Runs
          </Typography>
          <Grid container spacing={2}>
            {recentRuns.map((run) => (
              <Grid key={run.id} size={{ xs: 12, md: 6 }}>
                <Card 
                  sx={{ 
                    cursor: 'pointer',
                    transition: 'all 200ms',
                    '&:hover': { 
                      boxShadow: 2,
                      transform: 'translateY(-2px)',
                    }
                  }}
                  onClick={() => setSelectedRunId(run.id)}
                >
                  <CardContent>
                    <Stack spacing={1}>
                      <Typography variant="h6">
                        {new Date(run.start_time).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} – {new Date(run.end_time).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                      </Typography>
                      <Stack direction="row" spacing={3} sx={{ pt: 1 }}>
                        <Box>
                          <Typography variant="caption" color="text.secondary">Service</Typography>
                          <Typography variant="body2">{run.service}</Typography>
                        </Box>
                        <Box>
                          <Typography variant="caption" color="text.secondary">Metric</Typography>
                          <Typography variant="body2">{run.metric_name}</Typography>
                        </Box>
                        <Box>
                          <Typography variant="caption" color="text.secondary">Samples</Typography>
                          <Typography variant="body2">{run.sample_count}</Typography>
                        </Box>
                      </Stack>
                      <Button variant="text" size="small" sx={{ alignSelf: 'flex-start', mt: 1 }}>
                        View Run
                      </Button>
                    </Stack>
                  </CardContent>
                </Card>
              </Grid>
            ))}
          </Grid>
        </Box>
      )}

      <AnswerDrawer
        open={drawerOpen}
        question={activeQuestion}
        answer={answerQuery.data ?? null}
        signals={signalQuery.data ?? []}
        timeseries={timeSeriesQuery.data ?? []}
        onClose={() => setDrawerOpen(false)}
      />

      <SignalDetailsDrawer
        open={signalDrawerOpen}
        signal={selectedSignal}
        timeseries={timeSeriesQuery.data ?? []}
        onClose={() => setSignalDrawerOpen(false)}
      />

      <FindingDetailsDrawer
        open={findingDrawerOpen}
        finding={selectedFinding}
        onClose={() => setFindingDrawerOpen(false)}
      />
    </Box>
  );
}
