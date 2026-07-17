import { useState } from 'react';
import { Box, Button, Chip, Collapse, Divider, IconButton, Paper, Stack, TextField, Typography } from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { ErrorState } from '../components/ErrorState';

function formatFactValue(value: unknown): string {
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (value === null || value === undefined) return 'n/a';
  return JSON.stringify(value);
}

export function BehaviorIntelligencePage() {
  const definitionsQuery = useQuery({ queryKey: ['behavior-definitions'], queryFn: api.behaviorDefinitions });
  const runsQuery = useQuery({ queryKey: ['analysis-runs'], queryFn: api.analysisRuns });
  const [analysisRunId, setAnalysisRunId] = useState('');
  const [serviceFilter, setServiceFilter] = useState('');
  const [openIntro, setOpenIntro] = useState(true);
  const findingsQuery = useQuery({
    queryKey: ['behavior-findings', analysisRunId, serviceFilter],
    queryFn: () => api.behaviorFindings(analysisRunId.trim() || undefined, serviceFilter.trim() || undefined),
  });
  const [openReasoning, setOpenReasoning] = useState<Record<string, boolean>>({});
  const [openDataLineage, setOpenDataLineage] = useState<Record<string, boolean>>({});
  const selectedRun = runsQuery.data?.find((run) => run.id === analysisRunId.trim());
  const sampleTimeseriesQuery = useQuery({
    queryKey: ['behavior-run-timeseries', analysisRunId, selectedRun?.service, selectedRun?.metric_name],
    queryFn: () => api.timeseries(selectedRun!.service, selectedRun!.metric_name, selectedRun!.id),
    enabled: Boolean(analysisRunId.trim() && selectedRun?.service && selectedRun?.metric_name),
  });
  const definitionCount = definitionsQuery.data?.length ?? 0;
  const findingCount = findingsQuery.data?.length ?? 0;

  if (definitionsQuery.isLoading || findingsQuery.isLoading || runsQuery.isLoading) return <LoadingSkeleton />;
  if (definitionsQuery.error || findingsQuery.error || runsQuery.error) return <ErrorState message="Failed to load behavior intelligence" />;

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <Box>
        <Typography variant="h4" sx={{ mb: 1 }}>Behavior Intelligence</Typography>
        <Typography variant="body2" color="text.secondary">
          Behavior definitions combine evidence from multiple analyzers across one or more metrics. Instead of relying on a single detector,
          a behavior is reported only when several analyzer signals independently support the same operational condition.
        </Typography>
      </Box>

      <Paper sx={{ p: 3, bgcolor: 'rgba(15, 118, 110, 0.05)', border: '1px solid rgba(15, 118, 110, 0.14)' }}>
        <Stack spacing={2}>
          <Box
            sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 2, cursor: 'pointer' }}
            onClick={() => setOpenIntro((current) => !current)}
          >
            <Typography variant="h6">Behavior Intelligence</Typography>
            <KeyboardArrowDownIcon
              style={{
                transform: openIntro ? 'rotate(180deg)' : 'rotate(0deg)',
                transition: 'transform 0.2s ease',
                color: '#0f766e',
              }}
            />
          </Box>

          <Collapse in={openIntro} timeout="auto" unmountOnExit>
            <Stack spacing={2}>
              <Box>
                <Typography variant="body2" color="text.secondary">
                  Behavior Intelligence correlates evidence produced by multiple analyzers across one or more metrics to identify higher-level operational conditions. Instead of relying on a single analyzer, a behavior is generated only when the configured analyzer evidence satisfies the defined rule.
                </Typography>
              </Box>

              <Box>
                <Typography variant="h6" sx={{ mb: 0.75 }}>How it works</Typography>
                <Typography variant="body2" color="text.secondary">
                  Metric Data
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'pre-line', fontFamily: 'IBM Plex Mono, monospace', mt: 1 }}>
                  {'     ↓\nAnalyzer Results\n(Baseline Shift, Ruptures, Trend, Threshold...)\n     ↓\nBehavior Rule Evaluation\n     ↓\nOperational Behavior'}
                </Typography>
              </Box>

              <Box>
                <Typography variant="h6" sx={{ mb: 0.75 }}>Example</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'pre-line' }}>
                  {'Behavior: Possible CPU Throttling\n\nCPU Usage\n✓ Baseline Shift\n✓ Ruptures\n\nCPU Throttling\n✓ Baseline Shift\n\nRule:\nIF CPU Usage shows Baseline Shift + Ruptures\nAND CPU Throttling shows Baseline Shift\n\nTHEN\n✓ Possible CPU Throttling'}
                </Typography>
              </Box>

              <Box>
                <Typography variant="h6" sx={{ mb: 0.75 }}>Behavior Definitions</Typography>
                <Typography variant="body2" color="text.secondary">
                  Reusable YAML-based rules define:
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'pre-line', mt: 1 }}>
                  {'Metrics to evaluate\nRequired analyzer evidence\nCorrelation conditions\nBehavior name and description shown in the UI'}
                </Typography>
              </Box>
            </Stack>
          </Collapse>
        </Stack>
      </Paper>

      <Paper sx={{ p: 3 }}>
        <Typography variant="h6" sx={{ mb: 2 }}>Behavior Findings</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          These are the results produced after the rule engine checks the configured inputs and conditions. Expand a card to see the exact
          facts, matched conditions, and evidence used to justify the decision.
        </Typography>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} sx={{ mb: 2 }}>
          <TextField
            label="Filter by analysis run ID"
            value={analysisRunId}
            onChange={(event) => setAnalysisRunId(event.target.value)}
            placeholder="927a74e0ceff499f8188cf7f3df86458"
            size="small"
            fullWidth
            helperText="Paste a run ID to view only findings from that analysis run."
          />
          <TextField
            label="Filter by service"
            value={serviceFilter}
            onChange={(event) => setServiceFilter(event.target.value)}
            placeholder="checkout"
            size="small"
            fullWidth
            helperText="Optional: narrow results to one service."
          />
          <Button
            variant="outlined"
            sx={{ alignSelf: { xs: 'stretch', md: 'center' }, whiteSpace: 'nowrap' }}
            onClick={() => {
              setAnalysisRunId('');
              setServiceFilter('');
            }}
          >
            Clear
          </Button>
        </Stack>
        {(analysisRunId.trim() || serviceFilter.trim()) && (
          <Typography variant="caption" sx={{ display: 'block', mb: 2, color: 'text.secondary' }}>
            Showing filtered findings for {analysisRunId.trim() ? <Box component="span" sx={{ fontFamily: 'IBM Plex Mono, monospace' }}>{analysisRunId.trim()}</Box> : 'all runs'}
            {serviceFilter.trim() ? ` / ${serviceFilter.trim()}` : ''}
          </Typography>
        )}
        {analysisRunId.trim() && (
          <Box
            sx={{
              mb: 2,
              p: 1.5,
              borderRadius: 2,
              bgcolor: 'rgba(15, 118, 110, 0.05)',
              border: '1px solid rgba(15, 118, 110, 0.12)',
            }}
          >
            <Typography variant="subtitle2" sx={{ mb: 0.75, color: 'primary.main' }}>
              Run input preview
            </Typography>
            {selectedRun ? (
              <>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                  This run came from <Box component="span" sx={{ fontFamily: 'IBM Plex Mono, monospace' }}>{selectedRun.service}</Box> /{' '}
                  <Box component="span" sx={{ fontFamily: 'IBM Plex Mono, monospace' }}>{selectedRun.metric_name}</Box>.
                </Typography>
                <Typography variant="caption" sx={{ display: 'block', mb: 1, color: 'text.secondary' }}>
                  Sample rows from this run:
                </Typography>
                <Stack spacing={0.75}>
                  {(sampleTimeseriesQuery.data ?? []).slice(0, 5).map((point) => (
                    <Box
                      key={point.timestamp}
                      sx={{
                        display: 'grid',
                        gridTemplateColumns: { xs: '1fr', md: '1.2fr 0.8fr 0.8fr' },
                        gap: 1,
                        p: 1,
                        borderRadius: 1.5,
                        bgcolor: 'background.paper',
                      }}
                    >
                      <Typography variant="body2" sx={{ fontFamily: 'IBM Plex Mono, monospace' }}>
                        {point.timestamp}
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        value: {point.value}
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        metric: {point.metric_name}
                      </Typography>
                    </Box>
                  ))}
                  {sampleTimeseriesQuery.data?.length === 0 && (
                    <Typography variant="body2" color="text.secondary">
                      No sample rows were returned for this run.
                    </Typography>
                  )}
                </Stack>
              </>
            ) : (
              <Typography variant="body2" color="text.secondary">
                We could not find this run in the analysis history yet, so the source rows cannot be previewed.
              </Typography>
            )}
          </Box>
        )}
        <Stack spacing={2}>
          {(findingsQuery.data ?? []).map((finding) => (
            <Box key={`${finding.definition_id}-${finding.analysis_run_id}-${finding.id}`} sx={{ p: 2, borderRadius: 2, bgcolor: 'background.default' }}>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                <Typography variant="subtitle1">{finding.title}</Typography>
                <Chip size="small" label={`Confidence ${Math.round(finding.confidence * 100)}%`} />
                <Chip size="small" label={finding.severity} />
                <Box sx={{ flex: 1 }} />
                <IconButton
                  size="small"
                  onClick={() =>
                    setOpenReasoning((current) => ({
                      ...current,
                      [finding.id]: !current[finding.id],
                    }))
                  }
                  aria-label="toggle reasoning"
                >
                  <ExpandMoreIcon
                    style={{
                      transform: openReasoning[finding.id] ? 'rotate(180deg)' : 'rotate(0deg)',
                      transition: 'transform 0.2s ease',
                      color: '#0f766e',
                    }}
                  />
                </IconButton>
              </Stack>
              <Typography variant="body2" color="text.secondary">{finding.description}</Typography>
              <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: 'wrap' }}>
                <Chip
                  size="small"
                  label="Show data lineage"
                  variant="outlined"
                  onClick={() =>
                    setOpenDataLineage((current) => ({
                      ...current,
                      [finding.id]: !current[finding.id],
                    }))
                  }
                />
              </Stack>
              <Collapse in={openDataLineage[finding.id]} timeout="auto" unmountOnExit>
                <Box
                  sx={{
                    mt: 2,
                    p: 1.5,
                    borderRadius: 2,
                    bgcolor: 'rgba(2, 132, 199, 0.06)',
                    border: '1px solid rgba(2, 132, 199, 0.16)',
                  }}
                >
                  <Typography variant="subtitle2" sx={{ color: 'primary.main', mb: 0.75 }}>
                    Where the data came from
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                    The uploaded CSV is normalized into common fields before analysis. This is the shape the engine expects:
                  </Typography>
                  <Stack spacing={0.75}>
                    {[
                      ['timestamp', 'when the metric point happened'],
                      ['value', 'the measured number'],
                      ['metric_name', 'which metric this row belongs to'],
                      ['service', 'the service or workload name'],
                      ['env', 'the environment, such as prod or staging'],
                    ].map(([field, meaning]) => (
                      <Box key={field} sx={{ display: 'flex', justifyContent: 'space-between', gap: 2, p: 1, borderRadius: 1.5, bgcolor: 'background.paper' }}>
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>{field}</Typography>
                        <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'right' }}>{meaning}</Typography>
                      </Box>
                    ))}
                  </Stack>
                  <Typography variant="caption" sx={{ display: 'block', mt: 1, color: 'text.secondary' }}>
                    In this app, the source usually comes from a CSV upload or one of the sample files under
                    <Box component="span" sx={{ fontFamily: 'IBM Plex Mono, monospace' }}>sample_data/</Box>.
                  </Typography>
                </Box>
              </Collapse>

              <Collapse in={openReasoning[finding.id]} timeout="auto" unmountOnExit>
                <Divider sx={{ my: 2, borderColor: 'rgba(15, 118, 110, 0.2)' }} />
                <Stack spacing={1.5}>
                  <Box
                    sx={{
                      p: 1.5,
                      borderRadius: 2,
                      bgcolor: 'rgba(59, 130, 246, 0.08)',
                      border: '1px solid rgba(59, 130, 246, 0.18)',
                    }}
                  >
                    <Typography variant="subtitle2" sx={{ color: 'primary.main', mb: 0.5 }}>
                      Plain-English summary
                    </Typography>
                    <Typography variant="body2" sx={{ color: 'text.primary' }}>
                      {finding.title} was reported because the configured analyzers and rule checks matched the expected operational pattern.
                    </Typography>
                  </Box>

                  <Box
                    sx={{
                      p: 1.5,
                      borderRadius: 2,
                      bgcolor: 'rgba(15, 118, 110, 0.08)',
                      border: '1px solid rgba(15, 118, 110, 0.18)',
                    }}
                  >
                    <Typography variant="subtitle2" sx={{ color: 'primary.main', mb: 0.5 }}>
                      Why this matched
                    </Typography>
                    <Typography variant="body2" sx={{ color: 'text.primary' }}>
                      Category: {finding.category} • Service: {finding.service ?? 'any'} • Analysis run: {finding.analysis_run_id ?? 'n/a'}
                    </Typography>
                    <Typography variant="body2" sx={{ mt: 0.75, color: 'text.secondary' }}>
                      Confidence rises when the key facts are true, the correlation windows overlap, and the required conditions pass.
                    </Typography>
                    <Typography variant="body2" sx={{ mt: 0.75, color: 'text.secondary' }}>
                      Why this qualified: {finding.matched_conditions_json.filter((condition) => Boolean(condition.passed)).length} of {finding.matched_conditions_json.length} conditions passed.
                    </Typography>
                  </Box>

                  <Box
                    sx={{
                      p: 1.5,
                      borderRadius: 2,
                      bgcolor: 'rgba(15, 23, 42, 0.04)',
                      border: '1px solid rgba(15, 23, 42, 0.10)',
                    }}
                  >
                    <Typography variant="subtitle2" sx={{ color: 'primary.main', mb: 0.75 }}>
                      Matched metrics
                    </Typography>
                    <Stack spacing={0.75}>
                      {Object.entries(finding.input_metrics_json ?? {}).map(([alias, metricName]) => (
                        <Box
                          key={alias}
                          sx={{
                            display: 'grid',
                            gridTemplateColumns: { xs: '1fr', md: '160px 1fr' },
                            gap: 1,
                            p: 1,
                            borderRadius: 1.5,
                            bgcolor: 'background.paper',
                          }}
                        >
                          <Typography variant="body2" sx={{ fontWeight: 600 }}>
                            {alias}
                          </Typography>
                          <Typography variant="body2" color="text.secondary">
                            {String(metricName)}
                          </Typography>
                        </Box>
                      ))}
                    </Stack>
                  </Box>

                  <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}>
                    <Box
                      sx={{
                        flex: 1,
                        p: 1.5,
                        borderRadius: 2,
                        bgcolor: 'rgba(124, 45, 18, 0.08)',
                        border: '1px solid rgba(124, 45, 18, 0.16)',
                      }}
                    >
                      <Typography variant="caption" sx={{ display: 'block', mb: 0.75, color: 'secondary.main', fontWeight: 700 }}>
                        Matched facts
                      </Typography>
                      <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', fontFamily: 'IBM Plex Mono, monospace', fontSize: 13 }}>
                        {JSON.stringify(finding.facts_json, null, 2)}
                      </Typography>
                    </Box>

                    <Box
                      sx={{
                        flex: 1,
                        p: 1.5,
                        borderRadius: 2,
                        bgcolor: 'rgba(15, 118, 110, 0.06)',
                        border: '1px solid rgba(15, 118, 110, 0.14)',
                      }}
                    >
                      <Typography variant="caption" sx={{ display: 'block', mb: 0.75, color: 'primary.main', fontWeight: 700 }}>
                        Condition check
                      </Typography>
                      <Stack spacing={0.75}>
                        {finding.matched_conditions_json.map((condition, index) => (
                          <Box
                            key={`${finding.id}-${index}`}
                            sx={{
                              p: 1,
                              borderRadius: 1.5,
                              bgcolor: condition.passed ? 'rgba(34, 197, 94, 0.12)' : 'rgba(239, 68, 68, 0.10)',
                              border: condition.passed ? '1px solid rgba(34, 197, 94, 0.25)' : '1px solid rgba(239, 68, 68, 0.20)',
                            }}
                          >
                            <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
                              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                {condition.group ?? 'all'} • {condition.fact}
                              </Typography>
                              <Chip
                                size="small"
                                label={condition.passed ? 'passed' : 'failed'}
                                color={condition.passed ? 'success' : 'error'}
                                sx={{ height: 22 }}
                              />
                            </Stack>
                            <Typography variant="caption" sx={{ display: 'block', mt: 0.5, color: 'text.secondary' }}>
                              {condition.operator} {String(condition.value)}
                            </Typography>
                          </Box>
                        ))}
                      </Stack>
                    </Box>
                  </Stack>

                  <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}>
                    <Box
                      sx={{
                        flex: 1,
                        p: 1.5,
                        borderRadius: 2,
                        bgcolor: 'rgba(15, 118, 110, 0.05)',
                        border: '1px solid rgba(15, 118, 110, 0.14)',
                      }}
                    >
                      <Typography variant="caption" sx={{ display: 'block', mb: 0.75, color: 'primary.main', fontWeight: 700 }}>
                        Evidence fields
                      </Typography>
                      <Stack spacing={0.75}>
                        {(finding.evidence_json ?? []).map((evidence) => {
                          const segments = evidence.split('.');
                          const label = segments[segments.length - 1] ?? evidence;
                          return (
                            <Box
                              key={evidence}
                              sx={{
                                p: 1,
                                borderRadius: 1.5,
                                bgcolor: 'background.paper',
                                border: '1px solid rgba(15, 118, 110, 0.10)',
                              }}
                            >
                              <Typography variant="body2" sx={{ fontWeight: 600, color: 'text.primary' }}>
                                {label.replaceAll('_', ' ')}
                              </Typography>
                              <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                                derived from {evidence}
                              </Typography>
                            </Box>
                          );
                        })}
                      </Stack>
                    </Box>

                    <Box
                      sx={{
                        flex: 1,
                        p: 1.5,
                        borderRadius: 2,
                        bgcolor: 'rgba(124, 45, 18, 0.05)',
                        border: '1px solid rgba(124, 45, 18, 0.14)',
                      }}
                    >
                      <Typography variant="caption" sx={{ display: 'block', mb: 0.75, color: 'secondary.main', fontWeight: 700 }}>
                        Correlation summary
                      </Typography>
                      <Stack spacing={0.75}>
                        {Object.entries(finding.correlation_json ?? {}).map(([key, value]) => (
                          <Box
                            key={key}
                            sx={{
                              p: 1,
                              borderRadius: 1.5,
                              bgcolor: 'background.paper',
                              border: '1px solid rgba(124, 45, 18, 0.12)',
                            }}
                          >
                            <Typography variant="body2" sx={{ fontWeight: 600, color: 'text.primary' }}>
                              {key.replaceAll('_', ' ')}
                            </Typography>
                            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                              {formatFactValue(value)}
                            </Typography>
                          </Box>
                        ))}
                      </Stack>
                    </Box>
                  </Stack>
                </Stack>
              </Collapse>
            </Box>
          ))}
          {(findingsQuery.data ?? []).length === 0 && (
            <Typography variant="body2" color="text.secondary">No behavior evaluations found yet.</Typography>
          )}
        </Stack>
      </Paper>
    </Box>
  );
}
