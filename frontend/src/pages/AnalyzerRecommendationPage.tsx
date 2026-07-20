import { useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  Collapse,
  FormControl,
  Grid2 as Grid,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Tooltip,
  TextField,
  Typography,
} from '@mui/material';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { ErrorState } from '../components/ErrorState';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import type { MetricContext } from '../types';

const useCaseOptions = [
  'Detect gradual trend',
  'Detect baseline changes',
  'Detect unusual spikes',
  'Find repeated patterns',
  'Forecast future values',
];

const questionTemplates = [
  'Is memory gradually increasing?',
  'Did behavior change after deployment?',
  'Are there unusual spikes?',
  'Can future values be predicted reliably?',
];

const metricTemplates = {
  memory: {
    operational_purpose: 'Monitor memory health and identify growth before resource exhaustion.',
    use_cases: ['Detect gradual trend', 'Detect baseline changes', 'Detect unusual spikes'],
    operational_questions: ['Is memory gradually increasing?', 'Did behavior change after deployment?', 'Are there unusual spikes?'],
  },
  cpu: {
    operational_purpose: 'Identify sustained CPU pressure and unusual workload behavior.',
    use_cases: ['Detect unusual spikes', 'Detect baseline changes', 'Find repeated patterns'],
    operational_questions: ['Is CPU usage unusually high?', 'Did normal CPU behavior change?', 'Does this pattern repeat?'],
  },
  latency: {
    operational_purpose: 'Detect service degradation and latency behavior changes.',
    use_cases: ['Detect baseline changes', 'Detect unusual spikes', 'Forecast future values'],
    operational_questions: ['Did latency increase permanently?', 'Are there abnormal latency windows?', 'Is latency behavior predictable?'],
  },
} as const;

function recommendationColor(recommendation: string) {
  if (recommendation === 'recommended') return 'success';
  if (recommendation === 'conditional') return 'warning';
  return 'error';
}

function uniquePush(values: string[], value: string) {
  return values.includes(value) ? values : [...values, value];
}

function removeItem(values: string[], value: string) {
  return values.filter((item) => item !== value);
}

function emptyContext(): MetricContext {
  return {
    metric_name: '',
    metric_description: '',
    metric_type: 'unknown',
    provider: 'prometheus',
    unit: '',
    operational_purpose: '',
    use_cases: [],
    operational_questions: [],
    example_values: [],
    additional_notes: '',
  };
}

function summarizeContext(context: MetricContext) {
  const parts = [context.metric_name, context.provider, context.metric_type, context.operational_purpose].filter(Boolean);
  return parts.join(' · ');
}

function copyText(text: string) {
  void navigator.clipboard.writeText(text);
}

function yamlExample(context: MetricContext) {
  return `metric_context:
  metric_name: ${context.metric_name || 'container_memory_usage_bytes'}
  metric_description: ${context.metric_description || 'Current memory consumed by a Kubernetes container.'}
  metric_type: ${context.metric_type || 'gauge'}
  provider: ${context.provider || 'prometheus'}
  unit: ${context.unit || 'bytes'}
  operational_purpose: ${context.operational_purpose || 'Monitor memory health and identify growth before resource exhaustion.'}
  use_cases:
    - ${context.use_cases[0] || 'Detect gradual trend'}
    - ${context.use_cases[1] || 'Detect baseline changes'}
  operational_questions:
    - ${context.operational_questions[0] || 'Is memory gradually increasing?'}
  additional_notes: ${context.additional_notes || 'Memory normally increases during batch processing and should drop afterward.'}`;
}

function analyzerSnippet(recommendations: Array<{ analyzer_id: string; display_name: string; recommendation: string; evidence: Record<string, unknown> }>) {
  const lines = recommendations.length
    ? recommendations
        .map(
          (item) => `    ${item.analyzer_id}:
      enabled: ${item.recommendation !== 'not_recommended'}
      # ${item.display_name}
      # Evidence: ${JSON.stringify(item.evidence)}`
        )
        .join('\n')
    : `    trend:
      enabled: true
      # Trend Analyzer
      # Evidence: Add a representative sample to populate evidence`;
  return `# Copy this into config/analyzers.yaml
analysis:
  analyzers:
${lines}`;
}

export function AnalyzerRecommendationPage() {
  const samplesQuery = useQuery({ queryKey: ['metric-analyzer-samples'], queryFn: api.metricAnalyzerSamples });
  const [context, setContext] = useState<MetricContext>(emptyContext());
  const [selectedSample, setSelectedSample] = useState('');
  const [message, setMessage] = useState('Give me matching analyzers for this metric.');
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [runEvaluation, setRunEvaluation] = useState(true);
  const [includeVectorDiscovery, setIncludeVectorDiscovery] = useState(true);
  const [requestedAnalyzers, setRequestedAnalyzers] = useState('');
  const [chatResult, setChatResult] = useState<Awaited<ReturnType<typeof api.metricAnalyzerChat>> | null>(null);
  const [contextOpen, setContextOpen] = useState(true);
  const [advisorOpen, setAdvisorOpen] = useState(true);
  const [resultsOpen, setResultsOpen] = useState(true);

  const chatMutation = useMutation({
    mutationFn: () =>
      api.metricAnalyzerChat({
        conversation_id: conversationId,
        message,
        metric_context: context,
        options: {
          include_vector_discovery: includeVectorDiscovery,
          run_sample_evaluation: runEvaluation,
          requested_analyzers: requestedAnalyzers
            .split(',')
            .map((item) => item.trim())
            .filter(Boolean),
        },
      }),
    onSuccess: (result) => {
      setConversationId(result.conversation_id);
      setChatResult(result);
    },
  });

  const sampleOptions = useMemo(() => samplesQuery.data ?? [], [samplesQuery.data]);
  const missingFields = [
    !context.metric_name?.trim() ? 'Metric name' : null,
    !context.metric_description?.trim() ? 'Metric description' : null,
    !context.operational_purpose?.trim() ? 'Operational purpose' : null,
    context.use_cases.length === 0 ? 'At least one use case' : null,
    context.operational_questions.length === 0 || context.operational_questions.every((question) => !question.trim())
      ? 'At least one operational question'
      : null,
  ].filter(Boolean) as string[];

  if (samplesQuery.isLoading) return <LoadingSkeleton />;
  if (samplesQuery.error) return <ErrorState message="Failed to load metric samples" />;

  const applyTemplate = (template: 'memory' | 'cpu' | 'latency') => {
    const preset = metricTemplates[template];
    setContext((current) => ({
      ...current,
      operational_purpose: preset.operational_purpose,
      use_cases: [...preset.use_cases],
      operational_questions: [...preset.operational_questions],
    }));
  };

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <Box>
        <Typography variant="h4" sx={{ mb: 1 }}>Analyzer Recommendation</Typography>
        <Typography variant="body2" color="text.secondary">
          Fill in metric context, optionally attach a historical sample, then ask the advisor which analyzers fit best.
        </Typography>
      </Box>

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 7 }}>
          <Paper sx={{ p: 3, bgcolor: 'rgba(15,118,110,0.04)' }}>
            <Stack spacing={2}>
              <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={2}>
                <Box>
                  <Typography variant="h6">Metric Context</Typography>
                  <Typography variant="body2" color="text.secondary">Tell the advisor what this metric means in simple terms.</Typography>
                </Box>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  <Button size="small" variant="outlined" onClick={() => applyTemplate('memory')}>Memory Template</Button>
                  <Button size="small" variant="outlined" onClick={() => applyTemplate('cpu')}>CPU Template</Button>
                  <Button size="small" variant="outlined" onClick={() => applyTemplate('latency')}>Latency Template</Button>
                </Stack>
              </Stack>

              <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>Required</Typography>
              <Grid container spacing={2}>
                <Grid size={{ xs: 12, md: 6 }}>
                  <Tooltip title="Example: container_memory_usage_bytes or system.cpu.user" arrow>
                    <TextField
                      fullWidth
                      required
                      label="Metric Name"
                      value={context.metric_name}
                      onChange={(event) => setContext((current) => ({ ...current, metric_name: event.target.value }))}
                      helperText="Prometheus-style names and provider-specific names are supported."
                    />
                  </Tooltip>
                  <Alert severity="info" sx={{ mt: 1 }}>
                    This is the metric identifier. It can contain dots, dashes, colons, or slashes.
                  </Alert>
                </Grid>
                <Grid size={{ xs: 12 }}>
                  <Tooltip title="Example: Current memory consumed by a Kubernetes container." arrow>
                    <TextField
                      fullWidth
                      required
                      multiline
                      minRows={3}
                      label="Metric Description"
                      value={context.metric_description}
                      onChange={(event) => setContext((current) => ({ ...current, metric_description: event.target.value }))}
                      helperText="Describe what the metric measures, not what analyzer you expect."
                    />
                  </Tooltip>
                </Grid>
                <Grid size={{ xs: 12 }}>
                  <Tooltip title="Example: Monitor memory health and identify growth before resource exhaustion." arrow>
                    <TextField
                      fullWidth
                      required
                      multiline
                      minRows={3}
                      label="Operational Purpose"
                      value={context.operational_purpose}
                      onChange={(event) => setContext((current) => ({ ...current, operational_purpose: event.target.value }))}
                    />
                  </Tooltip>
                </Grid>
                <Grid size={{ xs: 12 }}>
                  <Typography variant="subtitle2" sx={{ mb: 1 }}>Operational Use Cases</Typography>
                  <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
                    {useCaseOptions.map((item) => {
                      const selected = context.use_cases.includes(item);
                      return (
                        <Chip
                          key={item}
                          label={item}
                          color={selected ? 'primary' : 'default'}
                          onClick={() =>
                            setContext((current) => ({
                              ...current,
                              use_cases: selected ? removeItem(current.use_cases, item) : uniquePush(current.use_cases, item),
                            }))
                          }
                        />
                      );
                    })}
                  </Stack>
                </Grid>
                <Grid size={{ xs: 12 }}>
                  <Typography variant="subtitle2" sx={{ mb: 1 }}>Operational Questions</Typography>
                  <Stack spacing={1}>
                    {context.operational_questions.map((question, index) => (
                      <Stack key={`${question}-${index}`} direction="row" spacing={1}>
                        <TextField
                          fullWidth
                          value={question}
                          onChange={(event) =>
                            setContext((current) => ({
                              ...current,
                              operational_questions: current.operational_questions.map((item, idx) => (idx === index ? event.target.value : item)),
                            }))
                          }
                        />
                        <Button onClick={() => setContext((current) => ({ ...current, operational_questions: removeItem(current.operational_questions, question) }))}>
                          Remove
                        </Button>
                      </Stack>
                    ))}
                    <Button variant="outlined" onClick={() => setContext((current) => ({ ...current, operational_questions: [...current.operational_questions, ''] }))}>
                      + Add another question
                    </Button>
                    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                      {questionTemplates.map((item) => (
                        <Chip
                          key={item}
                          label={item}
                          variant="outlined"
                          onClick={() => setContext((current) => ({ ...current, operational_questions: uniquePush(current.operational_questions, item) }))}
                        />
                      ))}
                    </Stack>
                  </Stack>
                </Grid>
              </Grid>

              <Stack direction="row" alignItems="center" justifyContent="space-between">
                <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>Optional</Typography>
                <Button size="small" variant="text" onClick={() => setContextOpen((current) => !current)}>
                  {contextOpen ? 'Hide optional fields' : 'Show optional fields'}
                </Button>
              </Stack>

              <Collapse in={contextOpen}>
                <Stack spacing={2}>
                  <Grid container spacing={2}>
                    <Grid size={{ xs: 12, md: 6 }}>
                      <FormControl fullWidth>
                        <InputLabel>Metric Type</InputLabel>
                        <Select
                          label="Metric Type"
                          value={context.metric_type ?? 'unknown'}
                          onChange={(event) => setContext((current) => ({ ...current, metric_type: event.target.value }))}
                        >
                          {['Gauge', 'Counter', 'Rate', 'Percentage', 'Latency', 'Duration', 'Histogram-derived', 'Sparse event', 'Unknown'].map((item) => (
                            <MenuItem key={item} value={item.toLowerCase().split(' ').join('-')}>
                              {item}
                            </MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                      <Alert severity="info" sx={{ mt: 1 }}>
                        Metric type is the behavior shape: gauge = a level, counter = only rises, latency = response time, percentage = percent values.
                      </Alert>
                    </Grid>
                    <Grid size={{ xs: 12, md: 6 }}>
                      <FormControl fullWidth>
                        <InputLabel>Provider</InputLabel>
                        <Select
                          label="Provider"
                          value={context.provider ?? 'prometheus'}
                          onChange={(event) => setContext((current) => ({ ...current, provider: event.target.value }))}
                        >
                          {['Prometheus', 'Datadog', 'CloudWatch', 'OpenTelemetry', 'Custom CSV', 'Other'].map((item) => (
                            <MenuItem key={item} value={item.toLowerCase().split(' ').join('-')}>
                              {item}
                            </MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                      <Alert severity="info" sx={{ mt: 1 }}>
                        Provider is the source system or file format you uploaded from. It tells the app how to interpret timestamps, mappings, and labels.
                      </Alert>
                    </Grid>
                    <Grid size={{ xs: 12, md: 6 }}>
                      <TextField
                        fullWidth
                        label="Unit"
                        value={context.unit ?? ''}
                        onChange={(event) => setContext((current) => ({ ...current, unit: event.target.value }))}
                      />
                      <Alert severity="info" sx={{ mt: 1 }}>
                        Unit is the measurement, like bytes, percentage, milliseconds, count, or requests/second.
                      </Alert>
                    </Grid>
                    <Grid size={{ xs: 12, md: 6 }}>
                      <TextField
                        fullWidth
                        label="Example Values"
                        multiline
                        minRows={2}
                        value={context.example_values.map((item) => `${item.timestamp}, ${item.value}`).join('\n')}
                        onChange={(event) =>
                          setContext((current) => ({
                            ...current,
                            example_values: event.target.value
                              .split('\n')
                              .map((line) => line.trim())
                              .filter(Boolean)
                              .map((line) => {
                                const [timestamp, value] = line.split(',').map((part) => part.trim());
                                return { timestamp, value: Number(value) };
                              })
                              .filter((item) => item.timestamp && Number.isFinite(item.value)),
                          }))
                        }
                        helperText="Optional. A few representative timestamp,value rows."
                      />
                    </Grid>
                    <Grid size={{ xs: 12 }}>
                      <TextField
                        fullWidth
                        label="Additional Notes"
                        multiline
                        minRows={2}
                        value={context.additional_notes ?? ''}
                        onChange={(event) => setContext((current) => ({ ...current, additional_notes: event.target.value }))}
                      />
                    </Grid>
                  </Grid>

                  <Typography variant="subtitle2">Historical Sample</Typography>
                  <FormControl fullWidth>
                    <InputLabel>Select Existing Sample</InputLabel>
                    <Select
                      label="Select Existing Sample"
                      value={selectedSample}
                      onChange={(event) => {
                        const value = String(event.target.value);
                        setSelectedSample(value);
                        const sample = sampleOptions.find((item) => `${item.service}::${item.metric_name}::${item.analysis_run_id ?? ''}` === value);
                        if (sample) {
                          setContext((current) => ({
                            ...current,
                            metric_name: sample.metric_name,
                            sample_id: undefined,
                            provider: current.provider ?? sample.service,
                          }));
                        }
                      }}
                    >
                      {sampleOptions.map((sample) => (
                        <MenuItem key={`${sample.service}-${sample.metric_name}-${sample.analysis_run_id ?? 'none'}`} value={`${sample.service}::${sample.metric_name}::${sample.analysis_run_id ?? ''}`}>
                          {sample.service} / {sample.metric_name} {sample.analysis_run_id ? `(${sample.analysis_run_id})` : ''}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                </Stack>
              </Collapse>

              <Alert severity="info">A historical sample is optional. Without it, the advisor gives a preliminary recommendation.</Alert>

              <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
                <TextField fullWidth label="Chat message" value={message} onChange={(event) => setMessage(event.target.value)} />
                <Button
                  variant="contained"
                  disabled={chatMutation.isPending || missingFields.length > 0}
                  onClick={() => chatMutation.mutate()}
                >
                  {chatMutation.isPending ? 'Evaluating...' : selectedSample ? 'Evaluate with Sample' : 'Get Preliminary Recommendation'}
                </Button>
              </Stack>
              {missingFields.length > 0 ? (
                <Alert severity="warning">Missing: {missingFields.join(', ')}</Alert>
              ) : (
                <Alert severity="success">Ready to evaluate. Historical sample is optional.</Alert>
              )}
            </Stack>
          </Paper>
        </Grid>

        <Grid size={{ xs: 12, lg: 5 }}>
          <Stack spacing={2}>
            <Paper sx={{ p: 3, bgcolor: 'rgba(124,45,18,0.05)' }}>
              <Stack spacing={2}>
                <Typography variant="h6">Chat Advisor</Typography>
                <Box sx={{ p: 2, borderRadius: 2, bgcolor: 'background.default' }}>
                  <Typography variant="subtitle2" color="text.secondary">Chatting about:</Typography>
                  <Typography variant="subtitle1">{context.metric_name || '—'}</Typography>
                  <Typography variant="body2" color="text.secondary">{summarizeContext(context)}</Typography>
                </Box>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  <Button size="small" variant="outlined" onClick={() => copyText(yamlExample(context))}>Copy YAML</Button>
                  <Button size="small" variant="text" onClick={() => copyText(context.metric_name)}>Copy metric name</Button>
                  <Button size="small" variant="text" onClick={() => setAdvisorOpen((current) => !current)}>
                    {advisorOpen ? 'Collapse' : 'Expand'}
                  </Button>
                </Stack>
                <Collapse in={advisorOpen}>
                  <Stack spacing={2}>
                    <Alert severity="info">
                      The advisor is for follow-up questions. The main recommendation comes from the structured form plus sample evidence.
                    </Alert>
                    {chatResult?.stale ? <Alert severity="warning">Metric context has changed. Reevaluate analyzers to refresh the recommendation.</Alert> : null}
                    {chatResult ? (
                      <Box sx={{ p: 2, borderRadius: 2, bgcolor: 'rgba(15,118,110,0.10)' }}>
                        <Typography variant="h6">{chatResult.assistant_message.headline}</Typography>
                        <Typography variant="body2" sx={{ mt: 1 }}>{chatResult.assistant_message.summary}</Typography>
                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
                          {chatResult.assistant_message.next_action}
                        </Typography>
                      </Box>
                    ) : null}
                  </Stack>
                </Collapse>
              </Stack>
            </Paper>

            {chatMutation.isError ? <ErrorState message="Failed to evaluate analyzer recommendations" /> : null}

            <Paper sx={{ p: 3 }}>
              <Stack spacing={1.5}>
                <Stack direction="row" alignItems="center" justifyContent="space-between">
                  <Typography variant="h6">Copyable YAML Snippet</Typography>
                  <Button size="small" variant="text" onClick={() => setResultsOpen((current) => !current)}>
                    {resultsOpen ? 'Collapse' : 'Expand'}
                  </Button>
                </Stack>
                <Collapse in={resultsOpen}>
                  <Stack spacing={1.5}>
                    <Typography variant="body2" color="text.secondary">
                      Copy this into `config/analyzers.yaml` to tune shared analyzer defaults. If you are changing provider mappings, paste those into `config/providers/prometheus.yaml` or `config/providers/datadog.yaml`.
                    </Typography>
                    <Box component="pre" sx={{ m: 0, p: 2, borderRadius: 2, bgcolor: 'background.default', whiteSpace: 'pre-wrap', fontSize: 13, maxHeight: 240, overflow: 'auto' }}>
                      {analyzerSnippet(chatResult?.recommendations ?? [])}
                    </Box>
                    <Button variant="outlined" onClick={() => copyText(analyzerSnippet(chatResult?.recommendations ?? []))}>
                      Copy analyzer YAML
                    </Button>
                  </Stack>
                </Collapse>
              </Stack>
            </Paper>
          </Stack>
        </Grid>
      </Grid>

      {chatResult && (
        <Paper sx={{ p: 3 }}>
          <Stack spacing={2}>
            <Typography variant="h6">Recommendation Results</Typography>
            {chatResult.recommendation_mode === 'preliminary' ? (
              <Alert severity="info">Preliminary recommendation. Upload or select a representative historical sample to verify analyzer fitness and calculate evidence-based confidence.</Alert>
            ) : null}
            <Grid container spacing={2}>
              {(['recommended', 'conditional', 'not_recommended'] as const).map((bucket) => (
                <Grid key={bucket} size={{ xs: 12, md: 4 }}>
                  <Paper sx={{ p: 1.5, bgcolor: bucket === 'recommended' ? 'rgba(34, 197, 94, 0.06)' : bucket === 'conditional' ? 'rgba(250, 204, 21, 0.08)' : 'rgba(239, 68, 68, 0.06)' }}>
                  <Typography variant="subtitle1" sx={{ mb: 1, textTransform: 'capitalize' }}>{bucket.split('_').join(' ')}</Typography>
                    <Stack spacing={1}>
                      {chatResult.recommendations.filter((item) => item.recommendation === bucket).map((item) => (
                        <Box
                          key={item.analyzer_id}
                          sx={{
                            p: 2,
                            borderRadius: 2,
                            bgcolor: bucket === 'recommended' ? 'rgba(34, 197, 94, 0.08)' : bucket === 'conditional' ? 'rgba(250, 204, 21, 0.10)' : 'rgba(239, 68, 68, 0.08)',
                            border: '1px solid rgba(0,0,0,0.08)',
                          }}
                        >
                          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }} flexWrap="wrap">
                            <Typography variant="subtitle1">{item.display_name}</Typography>
                            <Chip size="small" color={recommendationColor(item.recommendation)} label={item.recommendation} />
                            <Chip size="small" label={`Fitness ${Math.round(item.fitness_score * 100)}%`} />
                            <Chip size="small" label={`Confidence ${Math.round(item.decision_confidence * 100)}%`} />
                          </Stack>
                          <Typography variant="body2" sx={{ mb: 1 }}>{item.summary}</Typography>
                          <Typography variant="caption" color="text.secondary">Evidence</Typography>
                          <Box component="pre" sx={{ m: 0, mt: 1, whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: 13 }}>
                            {JSON.stringify(item.evidence, null, 2)}
                          </Box>
                          <Button size="small" variant="text" onClick={() => copyText(`analysis:\n  analyzers:\n    ${item.analyzer_id}:\n      enabled: true\n      # ${item.display_name}`)}>
                            Copy snippet for {item.analyzer_id}
                          </Button>
                        </Box>
                      ))}
                    </Stack>
                  </Paper>
                </Grid>
              ))}
            </Grid>
            <Box>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>Suggested follow-ups</Typography>
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                {chatResult.suggested_questions.map((question) => (
                  <Chip key={question} label={question} onClick={() => setMessage(question)} />
                ))}
              </Stack>
            </Box>
          </Stack>
        </Paper>
      )}
    </Box>
  );
}
