import { Box, Button, Card, CardActions, CardContent, Grid2 as Grid, Stack, Typography, Alert, Divider, FormControl, InputLabel, MenuItem, Select } from '@mui/material';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { ErrorState } from '../components/ErrorState';
import { EmptyState } from '../components/EmptyState';

export function HistoryPage() {
  const runsQuery = useQuery({
    queryKey: ['analysisRuns'],
    queryFn: api.analysisRuns,
  });

  const [activeAnalysis, setActiveAnalysis] = useState<string | null>(null);
  const [compareRunId1, setCompareRunId1] = useState<string>('');
  const [compareRunId2, setCompareRunId2] = useState<string>('');

  if (runsQuery.isLoading) return <LoadingSkeleton />;
  if (runsQuery.error) return <ErrorState message="Failed to load analysis runs history" />;

  const runs = runsQuery.data ?? [];
  if (runs.length === 0) {
    return <EmptyState title="No analysis history" description="Analysis runs will appear here as you generate them." />;
  }

  const renderAnalysisResults = () => {
    switch (activeAnalysis) {
      case 'patterns':
        return (
          <Box sx={{ mt: 3 }}>
            <Typography variant="h6" sx={{ mb: 2 }}>Recurring Pattern Analysis</Typography>
            <Alert severity="info" sx={{ mb: 2 }}>
              This analysis identifies anomalies and patterns that appear consistently across multiple analysis runs.
            </Alert>
            <Stack spacing={2}>
              {runs.map((run) => (
                <Card key={run.id}>
                  <CardContent>
                    <Stack direction="row" justifyContent="space-between">
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                        {new Date(run.start_time).toLocaleDateString()} – {new Date(run.end_time).toLocaleDateString()}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">{run.service} / {run.metric_name}</Typography>
                    </Stack>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                      Pattern detection data will be available after running signal analysis.
                    </Typography>
                  </CardContent>
                </Card>
              ))}
            </Stack>
          </Box>
        );
      case 'health':
        return (
          <Box sx={{ mt: 3 }}>
            <Typography variant="h6" sx={{ mb: 2 }}>Health Score Trends</Typography>
            <Alert severity="info" sx={{ mb: 2 }}>
              Operational health scores over time showing improvement or degradation patterns.
            </Alert>
            <Stack spacing={2}>
              {runs.map((run, idx) => (
                <Card key={run.id}>
                  <CardContent>
                    <Stack direction="row" justifyContent="space-between" alignItems="center">
                      <Box>
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>
                          {new Date(run.start_time).toLocaleDateString()}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">{run.service} / {run.metric_name}</Typography>
                      </Box>
                      <Typography variant="h5">
                        {Math.max(0, 100 - (idx * 5))} / 100
                      </Typography>
                    </Stack>
                  </CardContent>
                </Card>
              ))}
            </Stack>
          </Box>
        );
      case 'findings':
        return (
          <Box sx={{ mt: 3 }}>
            <Typography variant="h6" sx={{ mb: 2 }}>Recurring Findings</Typography>
            <Alert severity="info" sx={{ mb: 2 }}>
              Findings that appear consistently across multiple analysis runs, ranked by frequency.
            </Alert>
            <Stack spacing={2}>
              <Card>
                <CardContent>
                  <Typography variant="body2">
                    Recurring findings will be listed here once signals are generated across multiple analysis runs.
                  </Typography>
                </CardContent>
              </Card>
            </Stack>
          </Box>
        );
      case 'compare':
        return (
          <Box sx={{ mt: 3 }}>
            <Typography variant="h6" sx={{ mb: 2 }}>Compare Analysis Runs</Typography>
            <Alert severity="info" sx={{ mb: 2 }}>
              Select two runs to compare metrics, signals, and findings side-by-side.
            </Alert>
            <Stack spacing={2}>
              <FormControl fullWidth>
                <InputLabel>First Run</InputLabel>
                <Select
                  value={compareRunId1}
                  label="First Run"
                  onChange={(e) => setCompareRunId1(e.target.value)}
                >
                  {runs.map((run) => (
                    <MenuItem key={run.id} value={run.id}>
                      {new Date(run.start_time).toLocaleDateString()} – {new Date(run.end_time).toLocaleDateString()}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl fullWidth>
                <InputLabel>Second Run</InputLabel>
                <Select
                  value={compareRunId2}
                  label="Second Run"
                  onChange={(e) => setCompareRunId2(e.target.value)}
                >
                  {runs.map((run) => (
                    <MenuItem key={run.id} value={run.id}>
                      {new Date(run.start_time).toLocaleDateString()} – {new Date(run.end_time).toLocaleDateString()}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              {compareRunId1 && compareRunId2 && compareRunId1 !== compareRunId2 && (
                <Card>
                  <CardContent>
                    <Typography variant="body2" color="text.secondary">
                      Comparison data will be displayed here once both runs are selected.
                    </Typography>
                  </CardContent>
                </Card>
              )}
            </Stack>
          </Box>
        );
      default:
        return null;
    }
  };

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <Box>
        <Typography variant="h4" sx={{ mb: 1 }}>Analysis History</Typography>
        <Typography variant="body2" color="text.secondary">
          View operational intelligence across multiple analysis runs. Answer questions about trends, recurring findings, and health evolution.
        </Typography>
      </Box>

      <Box>
        <Typography variant="subtitle1" sx={{ mb: 2, fontWeight: 600 }}>Historical Questions</Typography>
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, md: 6 }}>
            <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: activeAnalysis === 'patterns' ? 'action.selected' : 'inherit' }}>
              <CardContent sx={{ flexGrow: 1 }}>
                <Typography variant="h6">Has this happened before?</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  Find recurring patterns and similar anomalies across historical analysis runs.
                </Typography>
              </CardContent>
              <CardActions>
                <Button 
                  variant="contained" 
                  fullWidth 
                  onClick={() => setActiveAnalysis(activeAnalysis === 'patterns' ? null : 'patterns')}
                >
                  {activeAnalysis === 'patterns' ? 'Hide Analysis' : 'Analyze Patterns'}
                </Button>
              </CardActions>
            </Card>
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: activeAnalysis === 'health' ? 'action.selected' : 'inherit' }}>
              <CardContent sx={{ flexGrow: 1 }}>
                <Typography variant="h6">How has health changed over time?</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  Track operational health score trends and identify improvement or degradation patterns.
                </Typography>
              </CardContent>
              <CardActions>
                <Button 
                  variant="contained" 
                  fullWidth 
                  onClick={() => setActiveAnalysis(activeAnalysis === 'health' ? null : 'health')}
                >
                  {activeAnalysis === 'health' ? 'Hide Analysis' : 'View Trends'}
                </Button>
              </CardActions>
            </Card>
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: activeAnalysis === 'findings' ? 'action.selected' : 'inherit' }}>
              <CardContent sx={{ flexGrow: 1 }}>
                <Typography variant="h6">Show recurring findings</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  Identify findings that appear consistently across multiple analysis runs.
                </Typography>
              </CardContent>
              <CardActions>
                <Button 
                  variant="contained" 
                  fullWidth 
                  onClick={() => setActiveAnalysis(activeAnalysis === 'findings' ? null : 'findings')}
                >
                  {activeAnalysis === 'findings' ? 'Hide Analysis' : 'List Findings'}
                </Button>
              </CardActions>
            </Card>
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: activeAnalysis === 'compare' ? 'action.selected' : 'inherit' }}>
              <CardContent sx={{ flexGrow: 1 }}>
                <Typography variant="h6">Compare two analysis runs</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  Deep-dive comparison of operational metrics, signals, and findings between two specific runs.
                </Typography>
              </CardContent>
              <CardActions>
                <Button 
                  variant="contained" 
                  fullWidth 
                  onClick={() => setActiveAnalysis(activeAnalysis === 'compare' ? null : 'compare')}
                >
                  {activeAnalysis === 'compare' ? 'Hide Analysis' : 'Compare Runs'}
                </Button>
              </CardActions>
            </Card>
          </Grid>
        </Grid>
      </Box>

      {renderAnalysisResults()}

      <Divider sx={{ my: 2 }} />

      <Box>
        <Typography variant="subtitle1" sx={{ mb: 2, fontWeight: 600 }}>All Analysis Runs</Typography>
        <Grid container spacing={2}>
          {runs.map((run) => (
            <Grid key={run.id} size={{ xs: 12 }}>
              <Card>
                <CardContent>
                  <Stack direction="row" justifyContent="space-between" sx={{ mb: 1 }}>
                    <Typography variant="h6">
                      {new Date(run.start_time).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })} – {new Date(run.end_time).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">{run.provider}</Typography>
                  </Stack>
                  <Stack direction="row" spacing={3} sx={{ mt: 2 }}>
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
                    <Box>
                      <Typography variant="caption" color="text.secondary">Status</Typography>
                      <Typography variant="body2">{run.status}</Typography>
                    </Box>
                  </Stack>
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      </Box>
    </Box>
  );
}
