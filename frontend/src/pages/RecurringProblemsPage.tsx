import { Alert, Box, Button, Chip, CircularProgress, Collapse, Grid2 as Grid, IconButton, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography } from '@mui/material';
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded';
import ExpandMoreRoundedIcon from '@mui/icons-material/ExpandMoreRounded';
import WarningAmberRoundedIcon from '@mui/icons-material/WarningAmberRounded';
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded';
import OpenInNewRoundedIcon from '@mui/icons-material/OpenInNewRounded';
import ContentCopyRoundedIcon from '@mui/icons-material/ContentCopyRounded';
import SearchRoundedIcon from '@mui/icons-material/SearchRounded';
import UploadFileRoundedIcon from '@mui/icons-material/UploadFileRounded';
import React from 'react';
import { Link as RouterLink, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { ImportIncidentsDialog } from '../components/ImportIncidentsDialog';
import { RecurringProblemsPanel } from '../components/RecurringProblemsPanel';
import { CoveragePanel } from '../components/CoveragePanel';
import { CaseOriginBadge } from '../components/CaseOriginBadge';
import { PageHeader, Pill, WorkspacePanel } from '../standalone/components';
import { formatDateTime, relativeTime, ui } from '../standalone/theme';
import { toCaseRows } from '../standalone/casesService';
import { buildMemorySummaryFromStats } from '../standalone/memoryService';
import type { AlertContextResponse, MemoryStatsResponse } from '../types';

const filters = [
  { id: 'indexed', label: 'Indexed' },
  { id: 'stale', label: 'Stale' },
  { id: 'failed', label: 'Failed' },
  { id: 'not_indexed', label: 'Not Indexed' },
  { id: 'all', label: 'All' },
];

/** Recurring problems: past cases grouped into the problems that keep coming back, whether your
 * monitoring caught imported past incidents, and - folded away - the memory those come from. */
export function RecurringProblemsPage() {
  const casesQuery = useQuery({ queryKey: ['operational-memory-cases'], queryFn: () => api.cases(200) });
  const memoryStatsQuery = useQuery({ queryKey: ['memory-stats'], queryFn: api.memoryStats });
  const [searchParams] = useSearchParams();
  // A case page's "See the pattern" link names the group's central case.
  const highlightId = Number(searchParams.get('problem')) || null;
  const [activeFilter, setActiveFilter] = React.useState('indexed');
  const [importOpen, setImportOpen] = React.useState(false);
  const [detailsOpen, setDetailsOpen] = React.useState(false);

  if (casesQuery.isLoading || memoryStatsQuery.isLoading) return <LoadingSkeleton />;

  const cases = casesQuery.data ?? [];
  const rows = toCaseRows(cases).map((row) => ({
    ...row,
    memoryStatus: cases.find((item) => item.id === row.id)?.memory_status ?? 'unknown',
  }));
  const memorySummary = buildMemorySummaryFromStats(memoryStatsQuery.data);
  const memoryUnavailable = Boolean(memoryStatsQuery.error || memorySummary?.availability === 'unavailable');
  const stats = memoryStatsQuery.data;
  const visibleRows = rows
    .filter((row) => activeFilter === 'all' || row.memoryStatus === activeFilter)
    .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());
  const retry = () => {
    void casesQuery.refetch();
    void memoryStatsQuery.refetch();
  };
  const showDetails = () => {
    setDetailsOpen(true);
    window.setTimeout(() => document.getElementById(INDEXING_DETAILS_ID)?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }), 0);
  };

  return (
    <Stack spacing={3}>
      <PageHeader
        title="Recurring problems"
        subtitle="Problems that keep coming back. Fix these for good instead of firefighting them again."
        action={
          <Button
            onClick={() => setImportOpen(true)}
            startIcon={<UploadFileRoundedIcon />}
            variant="contained"
            sx={{ textTransform: 'none', fontWeight: 800 }}
          >
            Import past incidents
          </Button>
        }
      />
      <ImportIncidentsDialog open={importOpen} onClose={() => setImportOpen(false)} />

      {memoryUnavailable ? (
        <WorkspacePanel sx={{ p: 2.5, borderColor: '#fecaca', bgcolor: '#fff7f7' }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={2}>
            <Box>
              <Typography sx={{ fontWeight: 900, color: ui.red }}>Memory unavailable</Typography>
              <Typography sx={{ mt: 0.75, color: ui.muted }}>
                The memory statistics endpoint did not return an authoritative status, so counts are not replaced with zero.
              </Typography>
            </Box>
            <RetryButton onClick={retry} />
          </Stack>
        </WorkspacePanel>
      ) : stats ? (
        <MemoryStatusLine stats={stats} onRetry={retry} onShowDetails={showDetails} />
      ) : null}

      {!memoryUnavailable && !casesQuery.error && !rows.length ? (
        <Box sx={{ py: 5, textAlign: 'center', border: `1px dashed ${ui.border}`, borderRadius: '8px', bgcolor: 'var(--os-surface-alt)' }}>
          <Typography sx={{ fontWeight: 900 }}>Memory is empty, so "have we seen this before?" has nothing to search yet.</Typography>
          <Typography sx={{ mt: 0.75, color: ui.muted, maxWidth: 560, mx: 'auto' }}>
            Import postmortems or incidents from Jira, PagerDuty, incident.io or a folder of CSV and Markdown files. They become resolved cases that similar-case search can match from day one.
          </Typography>
          <Button onClick={() => setImportOpen(true)} startIcon={<UploadFileRoundedIcon />} variant="contained" sx={{ mt: 2, textTransform: 'none', fontWeight: 800 }}>
            Import past incidents
          </Button>
        </Box>
      ) : null}

      {memoryUnavailable ? null : <RecurringProblemsPanel highlightId={highlightId} />}
      {/* With memory empty, the prompt above already asks for imports. */}
      {memoryUnavailable || !rows.length ? null : <CoveragePanel onImport={() => setImportOpen(true)} />}

      <Box id={INDEXING_DETAILS_ID}>
        <FoldedSection
          title="Indexing details"
          summary={
            stats && !memoryUnavailable
              ? `${stats.indexed_cases} indexed · ${stats.stale_cases} changed since indexing · ${stats.error_cases} failed · for admins`
              : 'Which cases are in memory, for admins'
          }
          open={detailsOpen}
          onToggle={() => setDetailsOpen(!detailsOpen)}
        >
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 2 }}>
            {filters.map((filter) => (
              <Chip
                key={filter.id}
                label={filter.label}
                onClick={() => setActiveFilter(filter.id)}
                color={activeFilter === filter.id ? 'primary' : 'default'}
                variant={activeFilter === filter.id ? 'filled' : 'outlined'}
                sx={{ fontWeight: 800 }}
              />
            ))}
          </Stack>

          {casesQuery.error ? (
            <Typography color="error">Cases unavailable. Memory inventory could not be loaded.</Typography>
          ) : !visibleRows.length ? (
            <Box sx={{ py: 5, textAlign: 'center', border: `1px dashed ${ui.border}`, borderRadius: '8px', bgcolor: 'var(--os-surface-alt)' }}>
              <Typography sx={{ fontWeight: 900 }}>No {filters.find((filter) => filter.id === activeFilter)?.label.toLowerCase()} cases returned.</Typography>
              <Typography sx={{ mt: 0.75, color: ui.muted }}>This is an empty backend result, not sample data.</Typography>
            </Box>
          ) : (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Case</TableCell>
                  <TableCell>Service</TableCell>
                  <TableCell>Metric</TableCell>
                  <TableCell>Memory Status</TableCell>
                  <TableCell>Updated</TableCell>
                  <TableCell align="right">Action</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {visibleRows.map((row) => (
                  <TableRow key={row.id} hover>
                    <TableCell>
                      <Typography sx={{ fontWeight: 850 }}>{row.title}</Typography>
                      <Typography sx={{ color: ui.muted, fontSize: 12 }}>{row.caseId} • {row.summary}</Typography>
                    </TableCell>
                    <TableCell>{row.service}</TableCell>
                    <TableCell>{row.imported ? <CaseOriginBadge source={row.source} sourceId={row.sourceId} sourceUrl={row.sourceUrl} /> : row.metric}</TableCell>
                    <TableCell><Pill label={row.memoryStatus} /></TableCell>
                    <TableCell>
                      <Typography sx={{ fontWeight: 750 }}>{relativeTime(row.updatedAt)}</Typography>
                      <Typography sx={{ color: ui.muted, fontSize: 12 }}>{formatDateTime(row.updatedAt)}</Typography>
                    </TableCell>
                    <TableCell align="right">
                      <Button component={RouterLink} to={`/cases/${row.id}`} endIcon={<OpenInNewRoundedIcon />} size="small" sx={{ textTransform: 'none', fontWeight: 800 }}>
                        Open Case
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </FoldedSection>
      </Box>

      <AlertContextPanel />
    </Stack>
  );
}

const INDEXING_DETAILS_ID = 'indexing-details';

function RetryButton({ onClick }: { onClick: () => void }) {
  return (
    <Button onClick={onClick} startIcon={<RefreshRoundedIcon />} variant="outlined" size="small" sx={{ textTransform: 'none', fontWeight: 800, flexShrink: 0 }}>
      Retry
    </Button>
  );
}

/** One line in place of four count cards: how many past cases can be searched, and only the
 * counts that need attention. Retry shows only when something is stale or failed. */
function MemoryStatusLine({ stats, onRetry, onShowDetails }: { stats: MemoryStatsResponse; onRetry: () => void; onShowDetails: () => void }) {
  const trouble = stats.stale_cases + stats.error_cases;
  const parts = [
    `${stats.indexed_cases} past ${stats.indexed_cases === 1 ? 'case' : 'cases'} searchable`,
    stats.not_indexed_cases ? `${stats.not_indexed_cases} not indexed yet` : null,
    stats.stale_cases ? `${stats.stale_cases} changed since indexing` : null,
    stats.error_cases ? `${stats.error_cases} failed to index` : null,
    trouble ? null : 'all up to date',
  ].filter(Boolean);
  return (
    <Box data-testid="memory-status-line">
    <WorkspacePanel sx={{ px: 2, py: 1.25 }}>
      <Stack direction="row" spacing={1.25} alignItems="center" flexWrap="wrap" useFlexGap>
        {trouble ? <WarningAmberRoundedIcon fontSize="small" sx={{ color: ui.yellow }} /> : <CheckCircleRoundedIcon fontSize="small" sx={{ color: ui.green }} />}
        <Typography sx={{ fontSize: 13.5 }}>{parts.join(' · ')}</Typography>
        {trouble ? <RetryButton onClick={onRetry} /> : null}
        <Button onClick={onShowDetails} size="small" sx={{ ml: 'auto', textTransform: 'none', fontWeight: 800 }}>
          Indexing details
        </Button>
      </Stack>
    </WorkspacePanel>
    </Box>
  );
}

/** A section kept to one line until opened: for admins and integrators, not the everyday reader. */
function FoldedSection({ title, summary, open, onToggle, children }: { title: string; summary: string; open: boolean; onToggle: () => void; children: React.ReactNode }) {
  return (
    <WorkspacePanel sx={{ p: 0, borderStyle: open ? 'solid' : 'dashed' }}>
      <Box
        component="button"
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%', px: 2.5, py: 1.5, border: 0, background: 'none', cursor: 'pointer', textAlign: 'left', color: 'inherit', font: 'inherit' }}
      >
        <Typography sx={{ fontWeight: 900 }}>{title}</Typography>
        <Typography sx={{ color: ui.muted, fontSize: 13, flex: 1 }}>{summary}</Typography>
        <ExpandMoreRoundedIcon sx={{ color: ui.muted, transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 150ms' }} />
      </Box>
      <Collapse in={open} unmountOnExit>
        <Box sx={{ px: 2.5, pb: 2.5 }}>{children}</Box>
      </Collapse>
    </WorkspacePanel>
  );
}

function recommendationTone(recommendation: AlertContextResponse['recommendation'], similarCount = 0) {
  if (recommendation === 'likely_real') return { color: '#059669', bg: 'var(--os-tint-green)', border: 'var(--os-tint-green-border)', label: 'Likely real' };
  if (recommendation === 'likely_noise') return { color: 'var(--os-muted)', bg: 'var(--os-surface-alt)', border: 'var(--os-border)', label: 'Likely noise' };
  // No real-vs-noise verdict yet, but it has happened before: say that, not "insufficient".
  if (similarCount > 0) return { color: '#2563eb', bg: 'var(--os-tint-blue)', border: 'var(--os-tint-blue-border)', label: 'Seen before' };
  return { color: '#d97706', bg: 'var(--os-tint-amber)', border: 'var(--os-tint-amber-border)', label: 'Insufficient history' };
}

export const ALERT_CONTEXT_PANEL_ID = 'alert-context-preview';

function AlertContextPanel() {
  // The import wizard links here with ?service=&message= so a new import can be checked right away.
  const [searchParams] = useSearchParams();
  const [metricName, setMetricName] = React.useState('cpu_usage');
  const [service, setService] = React.useState(searchParams.get('service') ?? '');
  const [message, setMessage] = React.useState(searchParams.get('message') ?? '');
  const prefilled = Boolean(searchParams.get('service') || searchParams.get('message'));
  React.useEffect(() => {
    if (prefilled) document.getElementById(ALERT_CONTEXT_PANEL_ID)?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  }, [prefilled]);

  const mutation = useMutation({
    mutationFn: () => api.alertContext(metricName.trim(), service.trim() || undefined, message.trim() || undefined),
  });

  const curlCommand = React.useMemo(() => {
    const params = new URLSearchParams({ metric_name: metricName.trim() || 'cpu_usage' });
    if (service.trim()) params.append('service', service.trim());
    if (message.trim()) params.append('message', message.trim());
    return `curl "http://localhost:8000/api/alert-context?${params.toString()}"`;
  }, [metricName, service, message]);

  const result = mutation.data;
  const tone = result ? recommendationTone(result.recommendation, result.similar_cases.length) : null;
  // Folded for the everyday reader; opened when the import wizard links here to check an import.
  const [open, setOpen] = React.useState(prefilled);

  return (
    <Box id={ALERT_CONTEXT_PANEL_ID}>
    <FoldedSection
      title="Alert context preview"
      summary="What an external alert manager sees before firing an alert, for integrators"
      open={open}
      onToggle={() => setOpen(!open)}
    >
      {prefilled ? (
        <Alert severity="info" sx={{ mb: 2 }}>
          Filled in from your import. Click <b>Check Alert Context</b>: imported incidents on this service should appear under similar cases.
        </Alert>
      ) : null}
      <Box sx={{ mb: 2 }}>
        <Typography sx={{ color: ui.muted, fontSize: 13 }}>
          This is the same lookup an external alert manager can call before firing a Prometheus alert: has this
          service/metric fired before, was it real, and what did we do about it last time. Backed by{' '}
          <code>GET /api/alert-context</code> — combines learning-outcome history from Postgres with a free-text
          semantic search over resolved cases in Qdrant.
        </Typography>
      </Box>

      <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} sx={{ mb: 1.5 }}>
        <TextField
          label="Metric name"
          size="small"
          fullWidth
          value={metricName}
          onChange={(event) => setMetricName(event.target.value)}
        />
        <TextField
          label="Service (optional)"
          size="small"
          fullWidth
          value={service}
          onChange={(event) => setService(event.target.value)}
        />
      </Stack>
      <TextField
        label="Alert message (optional, enables similar-case search)"
        placeholder="e.g. CPU usage spike on payments-service, threshold 85% breached"
        size="small"
        fullWidth
        multiline
        minRows={2}
        value={message}
        onChange={(event) => setMessage(event.target.value)}
        sx={{ mb: 1.5 }}
      />

      <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 2 }}>
        <Button
          variant="contained"
          startIcon={mutation.isPending ? <CircularProgress size={16} color="inherit" /> : <SearchRoundedIcon />}
          disabled={!metricName.trim() || mutation.isPending}
          onClick={() => mutation.mutate()}
          sx={{ textTransform: 'none', fontWeight: 800 }}
        >
          Check Alert Context
        </Button>
        <Stack direction="row" spacing={0.5} alignItems="center" sx={{ flex: 1, minWidth: 0 }}>
          <Typography sx={{ color: ui.muted, fontSize: 12, fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {curlCommand}
          </Typography>
          <IconButton size="small" onClick={() => navigator.clipboard?.writeText(curlCommand)} title="Copy curl command">
            <ContentCopyRoundedIcon fontSize="small" />
          </IconButton>
        </Stack>
      </Stack>

      {mutation.isError ? <Alert severity="error">Alert-context lookup failed. Is the backend running?</Alert> : null}

      {result ? (
        <Stack spacing={2}>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems={{ sm: 'center' }}>
            <Chip
              label={tone?.label}
              sx={{ bgcolor: tone?.bg, color: tone?.color, border: `1px solid ${tone?.border}`, fontWeight: 800 }}
            />
            <Typography sx={{ color: ui.muted, fontSize: 13 }}>{result.recommendation_basis}</Typography>
          </Stack>

          <Grid container spacing={1.5}>
            {[
              { label: 'Prior occurrences', value: result.history.total_prior_occurrences },
              { label: 'Confirmed', value: result.history.confirmed },
              { label: 'Rejected', value: result.history.rejected },
              {
                label: 'Confirmed rate',
                value: result.history.confirmed_rate != null ? `${Math.round(result.history.confirmed_rate * 100)}%` : '—',
              },
            ].map((stat) => (
              <Grid key={stat.label} size={{ xs: 6, sm: 3 }}>
                <Box sx={{ p: 1.5, border: `1px solid ${ui.border}`, borderRadius: '8px', bgcolor: 'var(--os-surface-alt)' }}>
                  <Typography sx={{ fontSize: 20, fontWeight: 900, lineHeight: 1 }}>{stat.value}</Typography>
                  <Typography sx={{ color: ui.muted, fontSize: 12, fontWeight: 700 }}>{stat.label}</Typography>
                </Box>
              </Grid>
            ))}
          </Grid>

          {result.exact_match_outcomes.length > 0 ? (
            <Box>
              <Typography sx={{ fontWeight: 850, fontSize: 13, mb: 0.75 }}>Prior learning outcomes (exact service + metric match)</Typography>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Outcome</TableCell>
                    <TableCell>Root cause</TableCell>
                    <TableCell>Resolution</TableCell>
                    <TableCell align="right">Case</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {result.exact_match_outcomes.map((outcome, index) => (
                    <TableRow key={`${outcome.case_id}-${index}`} hover>
                      <TableCell><Pill label={outcome.outcome_status} /></TableCell>
                      <TableCell>{outcome.root_cause_category ?? '—'}</TableCell>
                      <TableCell sx={{ maxWidth: 320 }}>{outcome.resolution_summary ?? '—'}</TableCell>
                      <TableCell align="right">
                        <Button component={RouterLink} to={`/cases/${outcome.case_id}`} size="small" sx={{ textTransform: 'none', fontWeight: 800 }}>
                          #{outcome.case_id}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
          ) : (
            <Alert severity="info">No exact-match learning outcomes recorded yet for this service/metric.</Alert>
          )}

          {message.trim() ? (
            result.similar_cases.length > 0 ? (
              <Box>
                <Typography sx={{ fontWeight: 850, fontSize: 13, mb: 0.75 }}>Similar resolved cases (free-text semantic search)</Typography>
                <Stack spacing={1}>
                  {result.similar_cases.map((match) => (
                    <Box key={match.case_id} sx={{ p: 1.5, border: `1px solid ${ui.border}`, borderRadius: '8px' }}>
                      <Stack direction="row" justifyContent="space-between" alignItems="center">
                        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                          <Typography sx={{ fontWeight: 800 }}>{match.title}</Typography>
                          <CaseOriginBadge source={match.source} sourceId={match.source_id} />
                        </Stack>
                        <Chip label={`score ${match.similarity_score.toFixed(2)}`} size="small" />
                      </Stack>
                      {match.root_cause_summary ? (
                        <Typography sx={{ color: ui.muted, fontSize: 13, mt: 0.5 }}><b>Cause:</b> {match.root_cause_summary}</Typography>
                      ) : null}
                      {match.corrective_action || match.outcome_summary ? (
                        <Typography sx={{ color: ui.muted, fontSize: 13, mt: 0.25 }}><b>Fix:</b> {match.corrective_action || match.outcome_summary}</Typography>
                      ) : null}
                      <Button component={RouterLink} to={match.reference} size="small" sx={{ mt: 0.5, textTransform: 'none', fontWeight: 800, pl: 0 }}>
                        Open case #{match.case_id}
                      </Button>
                    </Box>
                  ))}
                </Stack>
              </Box>
            ) : (
              <Alert severity="info">No semantically similar cases found above the similarity threshold.</Alert>
            )
          ) : (
            <Alert severity="info">Add an alert message above to also search for semantically similar resolved cases.</Alert>
          )}

          <Box>
            <Typography sx={{ fontWeight: 850, fontSize: 13, mb: 0.75 }}>
              Raw activity (Findings/Behaviors, cased or not)
            </Typography>
            {result.raw_activity.total_occurrences > 0 ? (
              <Box sx={{ p: 1.5, border: `1px solid ${ui.border}`, borderRadius: '8px', bgcolor: 'var(--os-surface-alt)' }}>
                <Stack direction="row" spacing={0.75} alignItems="flex-start">
                  {result.raw_activity.ai_summary ? (
                    <Chip label="AI" size="small" variant="outlined" color="info" sx={{ height: 18, fontSize: '0.65rem', mt: 0.25 }} />
                  ) : null}
                  <Typography sx={{ fontSize: 13 }}>
                    {result.raw_activity.ai_summary ?? (
                      <>
                        This exact service/metric occurred <strong>{result.raw_activity.total_occurrences}</strong> time(s) recently
                        ({result.raw_activity.finding_count} finding(s), {result.raw_activity.behavior_count} behavior(s)) -
                        whether or not anyone ever filed a case for it. This is recurrence only, not a confirmed outcome.
                      </>
                    )}
                  </Typography>
                </Stack>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1 }}>
                  {result.raw_activity.recent_titles.map((title, index) => (
                    <Chip key={`${title}-${index}`} label={title} size="small" />
                  ))}
                </Stack>
              </Box>
            ) : (
              <Alert severity="info">No finding or behavior activity recorded for this service/metric, cased or not.</Alert>
            )}
          </Box>
        </Stack>
      ) : null}
    </FoldedSection>
    </Box>
  );
}
