import { useMemo, useState } from 'react';
import { Link as RouterLink, useSearchParams } from 'react-router-dom';
import { Alert, Autocomplete, Box, Button, Chip, Collapse, Stack, TextField, Tooltip, Typography, createFilterOptions } from '@mui/material';
import ContentCopyRoundedIcon from '@mui/icons-material/ContentCopyRounded';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { ErrorState } from '../components/ErrorState';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { AiLabel } from '../demo/AiLabel';
import { PageHeader, WorkspacePanel } from '../standalone/components';
import { formatDateTime, ui } from '../standalone/theme';
import type { AnalyzerRecommendation, MetricAnalyzerRecommendation } from '../types';
import { LAB_FOR } from '../utils/analyzerSettings';
import {
  FIT_GROUPS,
  LAST_RUN_LABEL,
  discoveredMetrics,
  fitGroup,
  ranButNotAFit,
  turnOffSnippet,
  type DiscoveredMetric,
  type FitGroup,
} from '../utils/analyzerFit';

// The search box matches the metric name or its service.
const filterMetrics = createFilterOptions<DiscoveredMetric>({ stringify: (option) => `${option.metric_name} ${option.service}` });

const GROUP_ACCENT: Record<FitGroup, string> = { good: ui.green, can_help: ui.yellow, not_a_fit: ui.muted };

function settingsLink(service: string, metric: string, analyzerId?: string) {
  const params = new URLSearchParams({ service, metric });
  if (analyzerId) params.set('analyzer', analyzerId);
  return `/analyzer-settings?${params.toString()}`;
}

function PickCard({ item, group, service, metric }: { item: AnalyzerRecommendation; group: FitGroup; service: string; metric: string }) {
  const [whyOpen, setWhyOpen] = useState(false);
  const lab = LAB_FOR[item.analyzer_id];
  const reasons = Array.isArray(item.evidence?.reasons) ? (item.evidence.reasons as string[]) : [];
  return (
    <Box data-testid={`fit-${item.analyzer_id}`} sx={{ p: 1.5, borderRadius: '8px', border: `1px solid ${ui.border}`, borderLeft: `4px solid ${GROUP_ACCENT[group]}` }}>
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
        <Typography sx={{ fontWeight: 800, fontSize: 15 }}>{item.display_name}</Typography>
        {item.last_run ? (
          <Tooltip title={item.last_run_reason ?? ''} describeChild>
            <Chip size="small" label={LAST_RUN_LABEL[item.last_run]} color={item.last_run === 'ran' ? 'success' : item.last_run === 'failed' ? 'error' : 'default'} variant="outlined" />
          </Tooltip>
        ) : null}
      </Stack>
      <Typography sx={{ fontSize: 13.5, mt: 0.5 }}>{item.description ?? item.summary}</Typography>
      <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
        <Tooltip title={`Fit score ${Math.round(item.fitness_score * 100)}% · confidence ${Math.round(item.decision_confidence * 100)}%`}>
          <Typography component="span" sx={{ fontSize: 12.5, color: ui.muted, borderBottom: `1px dotted ${ui.muted}`, cursor: 'help' }}>How sure?</Typography>
        </Tooltip>
        <Button size="small" onClick={() => setWhyOpen((open) => !open)} sx={{ textTransform: 'none', minWidth: 0, p: 0 }} aria-expanded={whyOpen}>
          Why?
        </Button>
        {lab ? (
          <Button size="small" component={RouterLink} to={lab} sx={{ textTransform: 'none', minWidth: 0, p: 0 }}>
            Try in Labs
          </Button>
        ) : null}
        <Button size="small" component={RouterLink} to={settingsLink(service, metric, item.analyzer_id)} sx={{ textTransform: 'none', minWidth: 0, p: 0 }}>
          Its settings
        </Button>
      </Stack>
      <Collapse in={whyOpen}>
        <Box sx={{ mt: 1, fontSize: 13 }}>
          {item.description ? <Typography sx={{ fontSize: 13, mb: 0.5 }}>{item.summary}</Typography> : null}
          {reasons.length > 0 ? (
            <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
              {reasons.map((reason) => <li key={reason}>{reason}</li>)}
            </Box>
          ) : null}
          {item.warnings.length > 0 ? (
            <Box component="ul" sx={{ m: 0, pl: 2.5, color: 'var(--os-ink-amber, #92400e)' }}>
              {item.warnings.map((warning) => <li key={warning}>{warning}</li>)}
            </Box>
          ) : null}
        </Box>
      </Collapse>
    </Box>
  );
}

function Results({ result, metric }: { result: MetricAnalyzerRecommendation; metric: DiscoveredMetric }) {
  const [copied, setCopied] = useState(false);
  const runnable = result.recommendations.filter((item) => item.available !== false);
  const notBuiltIn = result.recommendations.filter((item) => item.available === false);
  const notScored = result.not_scored ?? [];
  const turnOff = ranButNotAFit(result.recommendations);
  const snippet = turnOffSnippet(metric.service, metric.metric_name, turnOff.map((item) => item.analyzer_id));
  const names = new Map(result.recommendations.map((item) => [item.analyzer_id, item.display_name]));
  const opinion = result.ai_opinion;

  return (
    <Stack spacing={2}>
      <Box>
        <Typography variant="h6" sx={{ fontSize: 18, fontWeight: 800 }}>
          {metric.metric_name}
        </Typography>
        <Typography sx={{ fontSize: 13, color: ui.muted }}>
          {result.sample.service} · {result.sample.sample_count} readings from {formatDateTime(result.sample.start_time)} to {formatDateTime(result.sample.end_time)}
        </Typography>
      </Box>

      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(3, 1fr)' }, gap: 2 }}>
        {FIT_GROUPS.map((group) => {
          const items = runnable.filter((item) => fitGroup(item.recommendation) === group.id);
          return (
            <Box key={group.id} component="section" aria-label={group.title}>
              <Typography component="h3" sx={{ fontSize: 12, fontWeight: 850, letterSpacing: '.05em', textTransform: 'uppercase', color: ui.muted, mb: 1 }}>
                {group.title} ({items.length})
              </Typography>
              <Stack spacing={1}>
                {items.length ? (
                  items.map((item) => <PickCard key={item.analyzer_id} item={item} group={group.id} service={metric.service} metric={metric.metric_name} />)
                ) : (
                  <Typography sx={{ fontSize: 13, color: ui.muted }}>{group.empty}</Typography>
                )}
              </Stack>
            </Box>
          );
        })}
      </Box>

      {notBuiltIn.length > 0 ? (
        <Typography sx={{ fontSize: 12.5, color: ui.muted }}>
          The router also scored tools that aren't built into Ops Signals, so they can't run here:{' '}
          {notBuiltIn.map((item, index) => (
            <span key={item.analyzer_id} data-testid={`not-built-in-${item.analyzer_id}`} data-fit={fitGroup(item.recommendation)}>
              {index > 0 ? ', ' : ''}
              {item.display_name} ({FIT_GROUPS.find((group) => group.id === fitGroup(item.recommendation))?.title.toLowerCase()})
            </span>
          ))}
          .
        </Typography>
      ) : null}

      {notScored.length > 0 ? (
        <Typography sx={{ fontSize: 12.5, color: ui.muted }} data-testid="not-scored">
          Not scored by the router, so they run only when analysis is set to run every analyzer:{' '}
          {notScored.map((item, index) => (
            <span key={item.analyzer_id}>
              {index > 0 ? ', ' : ''}
              <Tooltip title={item.description ?? ''} describeChild>
                <RouterLink to={settingsLink(metric.service, metric.metric_name, item.analyzer_id)}>{item.display_name}</RouterLink>
              </Tooltip>
            </span>
          ))}
          .
        </Typography>
      ) : null}

      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        <Button variant="outlined" component={RouterLink} to={settingsLink(metric.service, metric.metric_name)} sx={{ textTransform: 'none', fontWeight: 750 }}>
          See what runs on {metric.service}
        </Button>
      </Stack>

      {turnOff.length > 0 ? (
        <Alert severity="info" sx={{ alignItems: 'flex-start' }}>
          <Typography sx={{ fontSize: 14, fontWeight: 750 }}>
            {turnOff.map((item) => item.display_name).join(', ')} ran on this metric but {turnOff.length === 1 ? "doesn't" : "don't"} suit it.
          </Typography>
          <Typography sx={{ fontSize: 13, mb: 1 }}>
            To stop {turnOff.length === 1 ? 'it' : 'them'} here only, save this per-service setting. Settings can turn analyzers off or tune them; the router still decides what runs.
          </Typography>
          <Box component="pre" sx={{ m: 0, p: 1.5, borderRadius: '6px', bgcolor: 'rgba(15,23,42,0.06)', fontSize: 12, overflowX: 'auto' }}>{snippet}</Box>
          <Button
            size="small"
            startIcon={<ContentCopyRoundedIcon />}
            sx={{ mt: 1, textTransform: 'none' }}
            onClick={() => {
              void navigator.clipboard?.writeText(snippet);
              setCopied(true);
            }}
          >
            {copied ? 'Copied' : 'Copy setting'}
          </Button>
        </Alert>
      ) : null}

      {opinion.available ? (
        <WorkspacePanel sx={{ p: 2 }}>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
            <AiLabel><Chip size="small" color="info" variant="outlined" label="AI" /></AiLabel>
            <Typography sx={{ fontWeight: 800 }}>Second opinion</Typography>
          </Stack>
          <Typography sx={{ fontSize: 13, color: ui.muted, mb: 1 }}>
            An AI model's own read of the same data. It never changes the columns above or what runs.
          </Typography>
          {opinion.diverges_from_router ? (
            <Alert severity="warning" sx={{ mb: 1 }}>
              It disagrees with the top pick above
              {opinion.router_top_analyzer_id ? ` (${names.get(opinion.router_top_analyzer_id) ?? opinion.router_top_analyzer_id})` : ''}. Worth a second look.
            </Alert>
          ) : (
            <Alert severity="success" sx={{ mb: 1 }}>It agrees with the top pick above.</Alert>
          )}
          <Typography sx={{ fontWeight: 750 }}>
            Best pick: {opinion.best_analyzer_id ? names.get(opinion.best_analyzer_id) ?? opinion.best_analyzer_id : 'none'}
          </Typography>
          {opinion.rationale ? <Typography sx={{ fontSize: 13.5, mt: 0.5 }}>{opinion.rationale}</Typography> : null}
          {opinion.caveats.length > 0 ? (
            <Box component="ul" sx={{ m: 0, mt: 1, pl: 2.5, fontSize: 13 }}>
              {opinion.caveats.map((caveat) => <li key={caveat}>{caveat}</li>)}
            </Box>
          ) : null}
        </WorkspacePanel>
      ) : null}
    </Stack>
  );
}

export function AnalyzerRecommendationPage() {
  const [params] = useSearchParams();
  const samplesQuery = useQuery({ queryKey: ['metric-analyzer-samples'], queryFn: api.metricAnalyzerSamples });
  const metrics = useMemo(() => discoveredMetrics(samplesQuery.data ?? []), [samplesQuery.data]);
  const [pickedKey, setPickedKey] = useState<string | null>(null);
  // A link like ?service=checkout&metric=memory_usage picks that metric.
  const linkedKey = params.get('service') && params.get('metric') ? `${params.get('service')}::${params.get('metric')}` : null;
  const picked = metrics.find((metric) => metric.key === (pickedKey ?? linkedKey)) ?? null;

  const evaluate = useMutation({
    mutationFn: (metric: DiscoveredMetric) => api.metricAnalyzerEvaluate(metric.service, metric.metric_name, metric.analysis_run_id),
  });
  const result = evaluate.data && evaluate.variables?.key === picked?.key ? evaluate.data : null;

  if (samplesQuery.isLoading) return <LoadingSkeleton />;
  if (samplesQuery.error) return <ErrorState message="Couldn't load the analyzed metrics" />;

  return (
    <Stack spacing={3}>
      <PageHeader
        title="Which analyzer fits my metric?"
        subtitle="Pick a metric. Ops Signals scores every analyzer against its stored data, the same way analysis does, and says which ones suit it and whether they already run on it. Nothing changes until you edit a settings file."
      />

      <WorkspacePanel sx={{ p: 2.5, maxWidth: 820 }}>
        <Stack spacing={2}>
          <Autocomplete
            options={metrics}
            value={picked}
            onChange={(_, value) => setPickedKey(value?.key ?? null)}
            getOptionLabel={(option) => option.metric_name}
            filterOptions={filterMetrics}
            isOptionEqualToValue={(option, value) => option.key === value.key}
            groupBy={(option) => option.service}
            renderOption={(props, option) => {
              const { key, ...rest } = props as typeof props & { key: string };
              return (
                <li key={key} {...rest}>
                  <Stack direction="row" justifyContent="space-between" sx={{ width: '100%', gap: 2 }}>
                    <span>{option.metric_name}</span>
                    <Typography component="span" sx={{ fontSize: 12, color: ui.muted }}>{option.service} · {option.sample_count} readings</Typography>
                  </Stack>
                </li>
              );
            }}
            noOptionsText="No analyzed metric has that name."
            renderInput={(inputProps) => <TextField {...inputProps} label="Metric" placeholder="Search by metric or service" />}
          />
          {picked ? (
            <Typography sx={{ fontSize: 13, color: ui.muted }}>
              Uses the latest analysis of {picked.metric_name} on {picked.service}: {picked.sample_count} readings, {formatDateTime(picked.start_time)} to {formatDateTime(picked.end_time)}.
            </Typography>
          ) : null}
          {metrics.length === 0 ? (
            <Alert severity="info">
              No metric has been analyzed yet. This page judges a metric by its data, so run an analysis first.{' '}
              <Button component={RouterLink} to="/validate-data" size="small" sx={{ textTransform: 'none' }}>New Analysis</Button>
            </Alert>
          ) : (
            <Typography sx={{ fontSize: 12.5, color: ui.muted }}>
              Metric not in the list? It needs data first: analyze it from{' '}
              <RouterLink to="/validate-data">New Analysis</RouterLink> (a data source or a CSV file), then pick it here.
            </Typography>
          )}
          <Box>
            <Button variant="contained" disabled={!picked || evaluate.isPending} onClick={() => picked && evaluate.mutate(picked)} sx={{ textTransform: 'none', fontWeight: 800 }}>
              {evaluate.isPending ? 'Checking…' : 'Find the right analyzer'}
            </Button>
          </Box>
        </Stack>
      </WorkspacePanel>

      {evaluate.isError && evaluate.variables?.key === picked?.key ? (
        <ErrorState message={`Couldn't check this metric: ${(evaluate.error as Error).message}`} />
      ) : null}
      {result && picked ? (
        <WorkspacePanel sx={{ p: 2.5 }}>
          <Results key={picked.key} result={result} metric={picked} />
        </WorkspacePanel>
      ) : null}
    </Stack>
  );
}
