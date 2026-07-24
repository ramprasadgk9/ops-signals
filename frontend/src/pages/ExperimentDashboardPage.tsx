import { useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Divider,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Typography,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Button,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';

function classifyChange(percent: number | null | undefined) {
  const value = Math.abs(percent ?? 0);
  if (value > 50) return 'Major change';
  if (value > 25) return 'Significant change';
  if (value >= 10) return 'Noticeable change';
  return 'Minor change';
}

export function ExperimentDashboardPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['experiments'],
    queryFn: () => api.experiments(),
  });
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const selectedExperiment = data?.find((item) => item.experiment_id === selectedIds[0]) ?? data?.[0] ?? null;

  const comparisonQuery = useQuery({
    queryKey: ['experiment-comparison', selectedIds],
    queryFn: () => api.experimentCompare(selectedIds),
    enabled: selectedIds.length >= 2,
  });

  const summary = useMemo(() => {
    if (!selectedExperiment) return null;
    const events = selectedExperiment.results.events;
    const stable = events.length <= 2 ? 'mostly stable' : 'frequently changing';
    const primary = events[0];
    const percent = Number(primary?.details?.percentage_change ?? 0);
    return {
      stable,
      eventCount: selectedExperiment.results.event_count,
      firstTimestamp: primary?.timestamp,
      impact: classifyChange(percent),
      explanation: primary?.interpretation ?? selectedExperiment.plain_language_summary ?? 'No summary available.',
    };
  }, [selectedExperiment]);

  if (isLoading) {
    return (
      <Stack alignItems="center" sx={{ py: 6 }}>
        <CircularProgress />
      </Stack>
    );
  }

  if (error) {
    return <Alert severity="error">Failed to load experiments.</Alert>;
  }

  return (
    <Stack spacing={3}>
      <Card variant="outlined">
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h4">Analyzer Experiment Dashboard</Typography>
            <Typography variant="body2" color="text.secondary">
              Review structured experiment results in plain language, compare configurations, and inspect technical details only when needed.
            </Typography>
            <FormControl fullWidth>
              <InputLabel>Selected experiment</InputLabel>
              <Select
                value={selectedIds}
                label="Selected experiment"
                multiple
                renderValue={(selected) => `${selected.length} selected`}
                onChange={(e) => setSelectedIds(typeof e.target.value === 'string' ? e.target.value.split(',') : e.target.value)}
              >
                {(data ?? []).map((experiment) => (
                  <MenuItem key={experiment.experiment_id} value={experiment.experiment_id}>
                    {experiment.dataset.name} · {experiment.analyzer.algorithm ?? experiment.analyzer.name} · penalty {String(experiment.analyzer.parameters.penalty ?? '-')}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Stack direction="row" spacing={1} flexWrap="wrap">
              {(data ?? []).slice(0, 5).map((experiment) => (
                <Chip
                  key={experiment.experiment_id}
                  label={`${experiment.dataset.name} · ${experiment.analyzer.parameters.penalty ?? '-'}`}
                  onClick={() => setSelectedIds([experiment.experiment_id])}
                  variant={selectedIds.includes(experiment.experiment_id) ? 'filled' : 'outlined'}
                />
              ))}
            </Stack>
          </Stack>
        </CardContent>
      </Card>

      {selectedExperiment && summary ? (
        <>
          <Card variant="outlined">
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="h5">What the analyzer found</Typography>
                <Typography variant="body1">{summary.explanation}</Typography>
                <Stack direction="row" spacing={1} flexWrap="wrap">
                  <Chip label={summary.stable} />
                  <Chip label={`${summary.eventCount} meaningful changes`} />
                  <Chip label={summary.impact} />
                </Stack>
                <Typography variant="body2" color="text.secondary">
                  Most important change: {summary.firstTimestamp ? new Date(summary.firstTimestamp).toLocaleString() : 'n/a'}
                </Typography>
              </Stack>
            </CardContent>
          </Card>

          <Card variant="outlined">
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="h6">Events</Typography>
                {selectedExperiment.results.events.map((event) => (
                  <Card key={event.event_id} variant="outlined" sx={{ p: 2 }}>
                    <Stack spacing={1}>
                      <Stack direction="row" spacing={1} flexWrap="wrap">
                        <Chip label={event.event_type} size="small" />
                        <Chip label={classifyChange(Number(event.details?.percentage_change ?? 0))} size="small" />
                        {event.severity ? <Chip label={event.severity} size="small" /> : null}
                      </Stack>
                      <Typography variant="subtitle1">{event.interpretation}</Typography>
                      <Typography variant="body2" color="text.secondary">
                        {event.timestamp ? new Date(event.timestamp).toLocaleString() : 'n/a'} · value {event.value ?? 'n/a'}
                      </Typography>
                      <Accordion>
                        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                          <Typography variant="body2">Technical details</Typography>
                        </AccordionSummary>
                        <AccordionDetails>
                          <Typography variant="body2" color="text.secondary">
                            {event.technical_summary}
                          </Typography>
                          <pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{JSON.stringify(event.details, null, 2)}</pre>
                        </AccordionDetails>
                      </Accordion>
                    </Stack>
                  </Card>
                ))}
              </Stack>
            </CardContent>
          </Card>

          <Card variant="outlined">
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="h6">Comparison</Typography>
                {comparisonQuery.data ? (
                  <>
                    <Typography variant="body1">{comparisonQuery.data.comparison_summary}</Typography>
                    <Typography variant="body2" color="text.secondary">
                      Shared events: {comparisonQuery.data.shared_event_count} · Unique events: {comparisonQuery.data.unique_event_count}
                    </Typography>
                    <Divider />
                    <Stack spacing={1}>
                      {comparisonQuery.data.items.map((item) => (
                        <Typography key={item.experiment_id} variant="body2">
                          penalty {item.penalty ?? '-'} detected {item.event_count} events
                        </Typography>
                      ))}
                    </Stack>
                  </>
                ) : (
                  <Typography variant="body2" color="text.secondary">
                    Select at least two experiments to compare configurations.
                  </Typography>
                )}
              </Stack>
            </CardContent>
          </Card>

          <Card variant="outlined">
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="h6">Observations</Typography>
                {selectedExperiment.observations.map((item) => (
                  <Typography key={item} variant="body2">
                    {item}
                  </Typography>
                ))}
              </Stack>
            </CardContent>
          </Card>

          <Card variant="outlined">
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="h6">Recommendation</Typography>
                <Typography variant="body1">{selectedExperiment.recommendation.summary}</Typography>
                <Typography variant="body2" color="text.secondary">
                  {selectedExperiment.recommendation.recommended_configuration}
                </Typography>
                <Stack direction="row" spacing={1} flexWrap="wrap">
                  {selectedExperiment.recommendation.suitable_for.map((value) => (
                    <Chip key={value} label={`Suitable: ${value}`} />
                  ))}
                  {selectedExperiment.recommendation.not_suitable_for.map((value) => (
                    <Chip key={value} label={`Not suitable: ${value}`} variant="outlined" />
                  ))}
                </Stack>
              </Stack>
            </CardContent>
          </Card>

          <Card variant="outlined">
            <CardContent>
              <Typography variant="h6">Artifacts</Typography>
              <Stack spacing={1} sx={{ mt: 1 }}>
                <Typography variant="body2">Raw plot: {selectedExperiment.artifacts.raw_plot ?? 'n/a'}</Typography>
                <Typography variant="body2">Result plot: {selectedExperiment.artifacts.result_plot ?? 'n/a'}</Typography>
                <Typography variant="body2">Comparison plot: {selectedExperiment.artifacts.comparison_plot ?? 'n/a'}</Typography>
              </Stack>
            </CardContent>
          </Card>
        </>
      ) : null}
    </Stack>
  );
}
