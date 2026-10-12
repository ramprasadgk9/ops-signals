import React from 'react';
import { Alert, Box, Button, Chip, CircularProgress, Collapse, Grid2 as Grid, Link, Stack, TextField, Tooltip, Typography } from '@mui/material';
import KeyboardArrowDownRoundedIcon from '@mui/icons-material/KeyboardArrowDownRounded';
import KeyboardArrowRightRoundedIcon from '@mui/icons-material/KeyboardArrowRightRounded';
import SpaceDashboardOutlinedIcon from '@mui/icons-material/SpaceDashboardOutlined';
import NotificationsNoneRoundedIcon from '@mui/icons-material/NotificationsNoneRounded';
import FunctionsRoundedIcon from '@mui/icons-material/FunctionsRounded';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/queries';
import { FeatureNeedsSource } from '../components/FeatureNeedsSource';
import { MetricUsageValuePanel } from '../components/MetricUsageValuePanel';
import { PageHeader, WorkspacePanel } from '../standalone/components';
import { formatDateTime, relativeTime, ui } from '../standalone/theme';
import type { GrafanaStatus, MetricUsageItem, MetricUsageResponse, MetricUsageSnapshot, MetricUsageStatus } from '../types';
import { METRIC_USAGE_STATUSES, watcherLabel } from '../utils/metricUsage';

const SHOWN_STATUSES: MetricUsageStatus[] = ['blind_spot', 'missing', 'watched'];
const UNWATCHED_LIMIT = 200;
const WATCHED_PREVIEW = 20;
const SECTION_TITLES: Record<MetricUsageStatus, string> = {
  blind_spot: 'Blind spots',
  missing: 'Missing metrics',
  watched: 'Watched',
  unwatched: 'Not watched, no problems',
};

/** Which metrics Grafana dashboards and alerts watch, and which problems nobody would see. */
export function MetricUsagePage() {
  const queryClient = useQueryClient();
  const usageQuery = useQuery({ queryKey: ['metric-usage'], queryFn: () => api.metricUsage(SHOWN_STATUSES, 5000) });
  const grafanaQuery = useQuery({ queryKey: ['grafana-status'], queryFn: () => api.grafanaStatus(), retry: false });
  const historyQuery = useQuery({ queryKey: ['metric-usage-history'], queryFn: () => api.metricUsageHistory(), retry: false });
  const runMutation = useMutation({
    mutationFn: () => api.runMetricUsageCheck(),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['metric-usage'] });
      queryClient.invalidateQueries({ queryKey: ['metric-usage-unwatched'] });
      queryClient.invalidateQueries({ queryKey: ['metric-usage-history'] });
    },
  });

  const data = usageQuery.data;
  const snapshot = data?.snapshot ?? null;
  const items = data?.items ?? [];
  const byStatus = (status: MetricUsageStatus) => items.filter((item) => item.status === status);

  return (
    <Stack spacing={3}>
      <PageHeader
        title="Metric Usage"
        subtitle="Which metrics your Grafana dashboards and alerts watch, and which problems nobody would see"
        action={
          <Stack direction="row" spacing={1.5} alignItems="center">
            {snapshot ? (
              <Tooltip title={formatDateTime(snapshot.created_at)}>
                <Typography sx={{ fontSize: 13, color: ui.muted }}>
                  Last check {relativeTime(snapshot.created_at)}{data ? ` · every ${data.interval_hours}h` : ''}
                </Typography>
              </Tooltip>
            ) : null}
            <Button variant="contained" onClick={() => runMutation.mutate()} disabled={runMutation.isPending} sx={{ textTransform: 'none', fontWeight: 800 }}>
              {runMutation.isPending ? 'Checking…' : 'Run now'}
            </Button>
          </Stack>
        }
      />

      <FeatureNeedsSource feature="metric_usage" keepContent={Boolean(snapshot)}>
        <GrafanaLine status={grafanaQuery.data} snapshot={snapshot} />

        {runMutation.isError ? <Alert severity="error">{(runMutation.error as Error).message}</Alert> : null}
        {data?.last_failure ? (
          <Alert severity="warning" data-testid="metric-usage-failure">
            The latest check {relativeTime(data.last_failure.created_at)} failed: {data.last_failure.error}
            {snapshot ? ' Showing the last good check.' : ''}
          </Alert>
        ) : null}

        {usageQuery.isLoading ? <CircularProgress size={22} /> : null}
        {usageQuery.isError ? <Alert severity="error">Metric usage could not be loaded: {(usageQuery.error as Error).message}</Alert> : null}
        {data && !snapshot ? <NoCheckYet data={data} /> : null}

        {snapshot ? (
          <>
            <MetricUsageValuePanel snapshot={snapshot} cost={data?.cost ?? null} blindSpots={byStatus('blind_spot')} history={historyQuery.data ?? []} />
            <SummaryTiles snapshot={snapshot} />
            <StatusSection status="blind_spot" items={byStatus('blind_spot')} total={snapshot.blind_spots} defaultOpen
              empty="No blind spots: every metric with a recent problem is on a dashboard or in an alert." />
            {snapshot.missing ? <StatusSection status="missing" items={byStatus('missing')} total={snapshot.missing} defaultOpen /> : null}
            <StatusSection status="watched" items={byStatus('watched')} total={snapshot.watched} defaultOpen preview={WATCHED_PREVIEW}
              empty="No dashboard or alert reads any metric yet." />
            <UnwatchedSection total={snapshot.unwatched} snapshotId={snapshot.id} />
            <SourcesNote snapshot={snapshot} />
          </>
        ) : null}
      </FeatureNeedsSource>
    </Stack>
  );
}

function GrafanaLine({ status, snapshot }: { status?: GrafanaStatus; snapshot: MetricUsageSnapshot | null }) {
  if (!status) return null;
  const grafana = snapshot?.sources.grafana;
  if (!status.configured) {
    return (
      <Alert severity="info" data-testid="grafana-line">
        Grafana is not connected, so only Prometheus alert and recording rules count as watching a metric. To connect it: in Grafana,
        Administration → Service accounts → add one with the Viewer role and create a token; then set <code>OPS_SIGNALS_GRAFANA_URL</code> and{' '}
        <code>OPS_SIGNALS_GRAFANA_TOKEN</code> and restart the backend.
      </Alert>
    );
  }
  return (
    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap data-testid="grafana-line" sx={{ fontSize: 13, color: ui.muted }}>
      <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: status.reachable ? ui.green : ui.red }} />
      <Typography sx={{ fontSize: 13, color: ui.text, fontWeight: 700 }}>
        Grafana {status.reachable ? 'connected' : 'unreachable'}
      </Typography>
      <Typography sx={{ fontSize: 13, color: ui.muted }}>
        {[
          status.url,
          status.version ? `v${status.version}` : null,
          !status.reachable ? status.message : null,
          grafana?.dashboards_read !== undefined ? `${grafana.dashboards_read} dashboards and ${grafana.alert_rules_read ?? 0} alert rules read` : null,
          grafana?.dashboards_excluded?.length ? `${grafana.dashboards_excluded.length} skipped` : null,
        ].filter(Boolean).join(' · ')}
      </Typography>
    </Stack>
  );
}

function NoCheckYet({ data }: { data: MetricUsageResponse }) {
  return (
    <WorkspacePanel sx={{ p: 3 }}>
      <Typography sx={{ fontWeight: 800, mb: 0.5 }}>No check has run yet</Typography>
      <Typography sx={{ fontSize: 14, color: ui.muted }}>
        {data.enabled
          ? `The first check runs within a minute of the backend starting, then every ${data.interval_hours} hours. Or click Run now.`
          : 'Scheduled checks start once Grafana is connected. You can still click Run now to check against Prometheus rules only.'}
      </Typography>
    </WorkspacePanel>
  );
}

function SummaryTiles({ snapshot }: { snapshot: MetricUsageSnapshot }) {
  const tiles = [
    { key: 'metrics', value: snapshot.metrics_total, label: 'Metrics in Prometheus', detail: (snapshot.sources.prometheus ?? []).map((item) => item.name).join(', ') },
    { key: 'watched', value: snapshot.watched, label: 'Watched', detail: snapshot.watched_percent !== null ? `${snapshot.watched_percent}% on a dashboard or alert` : '', color: METRIC_USAGE_STATUSES.watched.color },
    { key: 'blind_spot', value: snapshot.blind_spots, label: 'Blind spots', detail: 'problems nobody would see', color: METRIC_USAGE_STATUSES.blind_spot.color, alarm: snapshot.blind_spots > 0 },
    { key: 'missing', value: snapshot.missing, label: 'Missing', detail: 'read by a panel that finds nothing', color: METRIC_USAGE_STATUSES.missing.color },
  ];
  return (
    <Grid container spacing={1.5} data-testid="metric-usage-tiles">
      {tiles.map((tile) => (
        <Grid key={tile.key} size={{ xs: 6, md: 3 }}>
          <WorkspacePanel sx={{ p: 2, height: '100%', ...(tile.alarm ? { borderColor: tile.color, bgcolor: 'var(--os-tint-rose)' } : {}) }}>
            <Typography sx={{ fontSize: 28, fontWeight: 800, lineHeight: 1.1, color: tile.alarm ? tile.color : ui.text }}>{tile.value}</Typography>
            <Stack direction="row" spacing={0.75} alignItems="center">
              {tile.color ? <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: tile.color, flexShrink: 0 }} /> : null}
              <Typography sx={{ fontSize: 13, fontWeight: 700, color: ui.text }}>{tile.label}</Typography>
            </Stack>
            <Typography sx={{ fontSize: 12, color: ui.muted }}>{tile.detail}</Typography>
          </WorkspacePanel>
        </Grid>
      ))}
    </Grid>
  );
}

function SectionShell({ status, total, open, onToggle, children }: { status: MetricUsageStatus; total: number; open: boolean; onToggle: () => void; children: React.ReactNode }) {
  const meta = METRIC_USAGE_STATUSES[status];
  return (
    <WorkspacePanel sx={{ p: 0 }}>
      <Button
        onClick={onToggle}
        fullWidth
        aria-expanded={open}
        sx={{ justifyContent: 'flex-start', textTransform: 'none', color: ui.text, px: 2, py: 1.5, gap: 1, borderRadius: 0 }}
      >
        {open ? <KeyboardArrowDownRoundedIcon sx={{ color: ui.muted }} /> : <KeyboardArrowRightRoundedIcon sx={{ color: ui.muted }} />}
        <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: meta.color }} />
        <Typography sx={{ fontWeight: 800, fontSize: 16 }}>{SECTION_TITLES[status]}</Typography>
        <Chip size="small" label={total} sx={{ fontWeight: 800 }} />
        <Typography sx={{ fontSize: 13, color: ui.muted, textAlign: 'left', display: { xs: 'none', md: 'block' } }}>{meta.hint}</Typography>
      </Button>
      <Collapse in={open} unmountOnExit>
        <Box sx={{ borderTop: `1px solid ${ui.border}` }}>{children}</Box>
      </Collapse>
    </WorkspacePanel>
  );
}

function StatusSection({ status, items, total, defaultOpen = false, preview, empty }: {
  status: MetricUsageStatus; items: MetricUsageItem[]; total: number; defaultOpen?: boolean; preview?: number; empty?: string;
}) {
  const [open, setOpen] = React.useState(defaultOpen);
  const [showAll, setShowAll] = React.useState(false);
  const shown = preview && !showAll ? items.slice(0, preview) : items;
  return (
    <Box data-testid={`metric-usage-section-${status}`}>
      <SectionShell status={status} total={total} open={open} onToggle={() => setOpen(!open)}>
        {items.length ? shown.map((item) => <MetricRow key={item.metric} item={item} />) : (
          <Typography sx={{ px: 2, py: 1.5, fontSize: 14, color: ui.muted }}>{empty}</Typography>
        )}
        {preview && items.length > preview ? (
          <Button size="small" onClick={() => setShowAll(!showAll)} sx={{ m: 1, textTransform: 'none', fontWeight: 700 }}>
            {showAll ? 'Show fewer' : `Show all ${items.length}`}
          </Button>
        ) : null}
      </SectionShell>
    </Box>
  );
}

function UnwatchedSection({ total, snapshotId }: { total: number; snapshotId: string }) {
  const [open, setOpen] = React.useState(false);
  const [filter, setFilter] = React.useState('');
  const query = useQuery({
    queryKey: ['metric-usage-unwatched', snapshotId],
    queryFn: () => api.metricUsage(['unwatched'], UNWATCHED_LIMIT),
    enabled: open,
  });
  const items = (query.data?.items ?? []).filter((item) => item.metric.toLowerCase().includes(filter.trim().toLowerCase()));
  return (
    <Box data-testid="metric-usage-section-unwatched">
      <SectionShell status="unwatched" total={total} open={open} onToggle={() => setOpen(!open)}>
        <Box sx={{ px: 2, pt: 1.5 }}>
          <TextField size="small" placeholder="Filter metric names" value={filter} onChange={(event) => setFilter(event.target.value)} sx={{ width: { xs: '100%', sm: 320 } }} />
        </Box>
        {query.isLoading ? <CircularProgress size={18} sx={{ m: 2 }} /> : null}
        {items.map((item) => <MetricRow key={item.metric} item={item} />)}
        {query.data && query.data.items_total > query.data.items.length ? (
          <Typography sx={{ px: 2, py: 1.5, fontSize: 12, color: ui.muted }}>
            Showing the first {query.data.items.length} of {query.data.items_total}. Ignore metrics you never want to see with OPS_SIGNALS_METRIC_USAGE_IGNORE_METRICS (e.g. go_*,prometheus_*).
          </Typography>
        ) : null}
      </SectionShell>
    </Box>
  );
}

function MetricRow({ item }: { item: MetricUsageItem }) {
  const navigate = useNavigate();
  const [open, setOpen] = React.useState(false);
  const createCase = useMutation({
    mutationFn: (findingId: number) => api.createCase(findingId),
    onSuccess: (result) => navigate(`/cases/${result.case_id}`),
  });
  const watchers = item.usages.filter((usage) => usage.kind !== 'recording_rule');
  const problem = item.status === 'blind_spot';

  return (
    <Box data-testid="metric-usage-row" sx={{ borderBottom: `1px solid ${ui.border}`, '&:last-of-type': { borderBottom: 0 } }}>
      <Stack
        direction={{ xs: 'column', md: 'row' }}
        spacing={1}
        justifyContent="space-between"
        alignItems={{ xs: 'flex-start', md: 'center' }}
        sx={{ px: 2, py: 1.25, cursor: 'pointer', '&:hover': { bgcolor: 'var(--os-surface-alt)' } }}
        onClick={() => setOpen(!open)}
      >
        <Box sx={{ minWidth: 0 }}>
          <Typography sx={{ fontFamily: 'IBM Plex Mono, monospace', fontSize: 13.5, fontWeight: 600, overflowWrap: 'anywhere' }}>{item.metric}</Typography>
          <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap sx={{ mt: 0.25 }}>
            {watchers.length ? watchers.slice(0, 3).map((usage) => <WatcherText key={`${usage.kind}-${usage.location}`} kind={usage.kind} text={watcherLabel(usage)} />) : (
              <Typography sx={{ fontSize: 12.5, color: ui.muted }}>
                {item.via_recording_rules.length ? `Through recording rule ${item.via_recording_rules.join(', ')}` : 'No dashboard · no alert'}
              </Typography>
            )}
            {watchers.length > 3 ? <Typography sx={{ fontSize: 12.5, color: ui.muted }}>+{watchers.length - 3} more</Typography> : null}
          </Stack>
        </Box>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap onClick={(event) => event.stopPropagation()}>
          {item.series !== null ? (
            <Typography sx={{ fontSize: 12.5, color: ui.muted, whiteSpace: 'nowrap' }}>{item.series.toLocaleString()} series</Typography>
          ) : null}
          {item.problem_findings ? (
            <Chip
              size="small"
              label={`${item.problem_findings} ${item.problem_findings === 1 ? 'problem' : 'problems'} · 24h`}
              sx={{ fontWeight: 700, bgcolor: problem ? '#fdecea' : 'var(--os-surface-alt)', color: problem ? METRIC_USAGE_STATUSES.blind_spot.color : ui.muted }}
            />
          ) : null}
          {item.latest_finding_id ? (
            <Button size="small" component={RouterLink} to={`/findings?finding=${item.latest_finding_id}`} sx={{ textTransform: 'none', fontWeight: 700 }}>
              View finding
            </Button>
          ) : null}
          {problem && item.latest_finding_id ? (
            <Button size="small" variant="contained" disabled={createCase.isPending} onClick={() => createCase.mutate(item.latest_finding_id!)} sx={{ textTransform: 'none', fontWeight: 800 }}>
              {createCase.isPending ? 'Creating…' : 'Create case'}
            </Button>
          ) : null}
        </Stack>
      </Stack>
      <Collapse in={open} unmountOnExit>
        <MetricDetails item={item} />
      </Collapse>
      {createCase.isError ? <Alert severity="error" sx={{ mx: 2, mb: 1 }}>{(createCase.error as Error).message}</Alert> : null}
    </Box>
  );
}

function WatcherText({ kind, text }: { kind: string; text: string }) {
  const Icon = kind === 'alert_rule' ? NotificationsNoneRoundedIcon : kind === 'recording_rule' ? FunctionsRoundedIcon : SpaceDashboardOutlinedIcon;
  return (
    <Stack direction="row" spacing={0.5} alignItems="center">
      <Icon sx={{ fontSize: 15, color: ui.muted }} />
      <Typography sx={{ fontSize: 12.5, color: ui.muted }}>{text}</Typography>
    </Stack>
  );
}

function MetricDetails({ item }: { item: MetricUsageItem }) {
  const meta = METRIC_USAGE_STATUSES[item.status];
  return (
    <Box sx={{ px: 2, pb: 1.5, pt: 0.5, bgcolor: '#fafbfc' }} data-testid="metric-usage-details">
      <Typography sx={{ fontSize: 13, color: ui.text, mb: 0.75 }}>
        <b>{meta.label}:</b> {item.status === 'blind_spot'
          ? `${item.problem_findings} problem findings in the last 24h, and nothing shows this metric. If Ops Signals didn't flag it, nobody would see it. Add a panel or an alert for it in Grafana, or track it as a case.`
          : meta.hint}
      </Typography>
      {item.usages.length ? (
        <Stack spacing={0.5} sx={{ mb: 0.75 }}>
          {item.usages.map((usage) => <WatcherText key={`${usage.kind}-${usage.location}`} kind={usage.kind} text={watcherLabel(usage)} />)}
        </Stack>
      ) : null}
      <Typography sx={{ fontSize: 12, color: ui.muted }}>
        {[
          !item.connections.length
            ? 'Not in any Prometheus connection'
            : item.status === 'missing'
              ? `Only in ${item.connections.join(', ')}, not in what its panels and alerts read`
              : `In ${item.connections.join(', ')}`,
          item.via_recording_rules.length ? `Feeds ${item.via_recording_rules.join(', ')}` : null,
          item.analyzed ? 'Analyzed by Ops Signals in the last 7 days' : 'Not analyzed by Ops Signals in the last 7 days',
        ].filter(Boolean).join(' · ')}
      </Typography>
    </Box>
  );
}

function SourcesNote({ snapshot }: { snapshot: MetricUsageSnapshot }) {
  const { grafana, prometheus = [], unresolved_queries: unresolved = [], warnings = [] } = snapshot.sources;
  const rules = prometheus.reduce((sum, item) => sum + item.rule_groups, 0);
  return (
    <Stack spacing={0.5}>
      <Typography sx={{ fontSize: 12, color: ui.muted }}>
        {[
          grafana?.configured ? `Read from Grafana: ${grafana.dashboards_read ?? 0} dashboards, ${grafana.alert_rules_read ?? 0} alert rules` : 'Grafana not connected',
          grafana?.dashboards_excluded?.length ? `skipped ${grafana.dashboards_excluded.join(', ')}` : null,
          `Prometheus rule groups: ${rules}`,
          snapshot.duration_ms !== null ? `took ${snapshot.duration_ms} ms` : null,
        ].filter(Boolean).join(' · ')}
      </Typography>
      {unresolved.length ? (
        <Typography sx={{ fontSize: 12, color: ui.muted }}>
          {unresolved.length} {unresolved.length === 1 ? 'panel uses' : 'panels use'} a dashboard variable for the metric name with no saved options, so its metric is unknown:{' '}
          {unresolved.slice(0, 3).map((item) => item.location).join('; ')}{unresolved.length > 3 ? '…' : ''}
        </Typography>
      ) : null}
      {warnings.map((warning) => <Typography key={warning} sx={{ fontSize: 12, color: ui.orange }}>{warning}</Typography>)}
      <Typography sx={{ fontSize: 12, color: ui.muted }}>
        "Problems" are significant or critical findings in the last 24 hours. Watched means on a Grafana dashboard panel or used by an alert, directly or through recording rules.{' '}
        <Link component={RouterLink} to="/findings">Findings</Link> show the same tag.
      </Typography>
    </Stack>
  );
}
