import React from 'react';
import { Alert, Box, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, Grid2 as Grid, Link, Stack, Typography } from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { ui } from '../standalone/theme';
import type { MetricUsageItem, MetricUsageSnapshot, MetricUsageUnreadRule } from '../types';
import { jobNames, watchQuery } from '../utils/metricUsage';

const codeSx = {
  m: 0, p: 1.25, pr: 9, borderRadius: 1, border: `1px solid ${ui.border}`, bgcolor: 'var(--os-surface-alt)',
  fontFamily: 'IBM Plex Mono, ui-monospace, monospace', fontSize: 12.5, lineHeight: 1.5, overflowX: 'auto', whiteSpace: 'pre',
} as const;

/** A block of text to paste somewhere, with a Copy button on it. */
function CopyBlock({ text, label, testId }: { text: string; label: string; testId?: string }) {
  const [state, setState] = React.useState<'idle' | 'copied' | 'failed'>('idle');
  const pre = React.useRef<HTMLPreElement>(null);
  const copy = async () => {
    try {
      // Undefined outside a secure context (plain http on another host).
      if (!navigator.clipboard) throw new Error('no clipboard');
      await navigator.clipboard.writeText(text);
      setState('copied');
      window.setTimeout(() => setState('idle'), 1500);
    } catch {
      setState('failed');
      // Select it, so Cmd/Ctrl+C copies what's shown.
      const selection = window.getSelection();
      if (pre.current && selection) {
        const range = document.createRange();
        range.selectNodeContents(pre.current);
        selection.removeAllRanges();
        selection.addRange(range);
      }
    }
  };
  return (
    <Box sx={{ position: 'relative' }}>
      <Box component="pre" ref={pre} data-testid={testId} sx={codeSx}>{text}</Box>
      <Button size="small" variant="outlined" onClick={() => void copy()} aria-label={`Copy ${label}`} sx={{ position: 'absolute', top: 6, right: 6, textTransform: 'none', fontWeight: 700, bgcolor: ui.surface }}>
        {state === 'copied' ? 'Copied' : 'Copy'}
      </Button>
      {state === 'failed' ? (
        <Typography role="alert" sx={{ fontSize: 12.5, color: ui.orange, mt: 0.5 }}>
          The browser didn't allow copying. The text is selected: press Cmd+C or Ctrl+C.
        </Typography>
      ) : null}
    </Box>
  );
}

/** What "not used" was judged on, and what it can't see - shown next to every Drop and remove. */
export function CheckedNote({ snapshot, grafanaUrl, what }: { snapshot: MetricUsageSnapshot; grafanaUrl?: string | null; what: 'metrics' | 'rule' }) {
  const { grafana, prometheus = [] } = snapshot.sources;
  const promNames = prometheus.map((item) => item.name).join(', ') || 'Prometheus';
  const checked = grafana?.configured
    ? `${grafana.dashboards_read ?? 0} dashboards and ${grafana.alert_rules_read ?? 0} alert rules in Grafana${grafanaUrl ? ` (${grafanaUrl})` : ''}, and alert and recording rules in ${promNames}.`
    : `Alert and recording rules in ${promNames}. Grafana isn't connected, so dashboards were not checked.`;
  return (
    <Alert severity="warning" icon={false} data-testid="metric-usage-checked-note" sx={{ fontSize: 13.5 }}>
      <Typography sx={{ fontWeight: 800, fontSize: 13.5 }}>Check before you apply.</Typography>
      “Not used” means not used by what Ops Signals can see:
      <Box component="ul" sx={{ my: 0.5, pl: 2.5 }}>
        <li><b>Checked:</b> {checked}</li>
        <li><b>Not checked:</b> queries people run by hand (Explore), scripts and autoscalers that call the Prometheus API, other Grafana instances and other tools.</li>
        {what === 'metrics' ? (
          <>
            <li>This works for metrics Prometheus scrapes. Metrics sent by remote write or OTLP have to be dropped where they're sent from.</li>
            <li>Data already stored stays until retention ends. Removing the rule brings back new data only; the gap stays.</li>
          </>
        ) : (
          <li>Its stored data stays until retention ends. Adding the rule back starts it again from then; the gap stays.</li>
        )}
      </Box>
    </Alert>
  );
}

/** The scrape config that stops storing the chosen metrics, built by the backend. */
export function DropDialog({ metrics, snapshot, grafanaUrl, onClose }: {
  metrics: string[]; snapshot: MetricUsageSnapshot; grafanaUrl?: string | null; onClose: () => void;
}) {
  const query = useQuery({
    queryKey: ['metric-usage-drop-config', snapshot.id, metrics],
    queryFn: () => api.metricUsageDropConfig(metrics),
    enabled: metrics.length > 0,
  });
  const config = query.data;
  const count = config?.metrics.length ?? metrics.length;
  const several = (config?.blocks.length ?? 0) > 1;
  const download = (yaml: string, name: string) => {
    const url = URL.createObjectURL(new Blob([yaml], { type: 'text/yaml' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = several ? `ops-signals-drop-rules-${name.replace(/[^A-Za-z0-9_.-]+/g, '-')}.yml` : 'ops-signals-drop-rules.yml';
    link.click();
    URL.revokeObjectURL(url);
  };
  return (
    <Dialog open onClose={onClose} maxWidth="md" fullWidth aria-labelledby="drop-dialog-title">
      <DialogTitle id="drop-dialog-title" sx={{ fontWeight: 900, pb: 0.5 }}>
        Drop {count} {count === 1 ? 'metric' : 'metrics'}
        {config?.series !== null && config?.series !== undefined ? (
          <Typography sx={{ fontSize: 13, color: ui.muted }}>{config.series.toLocaleString()} series stop being stored</Typography>
        ) : null}
      </DialogTitle>
      <DialogContent>
        <Stack spacing={1.5} sx={{ pt: 1 }}>
          <CheckedNote snapshot={snapshot} grafanaUrl={grafanaUrl} what="metrics" />
          {query.isLoading ? <CircularProgress size={20} /> : null}
          {query.isError ? <Alert severity="error">The config could not be built: {(query.error as Error).message}</Alert> : null}
          {config?.warnings.map((warning) => <Alert key={warning} severity="warning" sx={{ py: 0 }}>{warning}</Alert>)}
          {config?.skipped.length ? (
            <Box data-testid="drop-skipped">
              <Typography sx={{ fontSize: 13, fontWeight: 700 }}>Not included</Typography>
              {config.skipped.map((item) => (
                <Typography key={item.metric} sx={{ fontSize: 13, color: ui.muted }}>
                  <Box component="span" sx={{ fontFamily: 'IBM Plex Mono, monospace' }}>{item.metric}</Box>: {item.reason}
                </Typography>
              ))}
            </Box>
          ) : null}
          {config?.blocks.length ? (
            <Box>
              <Typography sx={{ fontSize: 13, fontWeight: 700 }}>Prometheus scrape config</Typography>
              <Typography sx={{ fontSize: 13, color: ui.muted, mb: 0.75 }}>
                Add each rule under the scrape job that collects the metric, in <code>prometheus.yml</code>. Jobs are named by the series' <code>job</code> label,
                which is usually the job_name; with relabeling or prometheus-operator, use the job (or ServiceMonitor) that sets that label.
                If the job already has <code>metric_relabel_configs</code>, add only the rule to that list.
                {several ? ' The metrics come from several Prometheus servers: each block goes into its own server.' : ''}
              </Typography>
              <Stack spacing={1.25}>
                {config.blocks.map((block) => (
                  <Box key={block.connection} data-testid="drop-config-block">
                    {several ? <Typography sx={{ fontSize: 13, fontWeight: 700, mb: 0.5 }}>{block.name}</Typography> : null}
                    <CopyBlock text={block.yaml} label={several ? `drop config for ${block.name}` : 'drop config'} testId="drop-config-yaml" />
                    <Button size="small" onClick={() => download(block.yaml, block.name)} sx={{ textTransform: 'none', fontWeight: 700, px: 0 }}>
                      Download .yml{several ? ` for ${block.name}` : ''}
                    </Button>
                  </Box>
                ))}
              </Stack>
              <Box component="ol" sx={{ fontSize: 13.5, pl: 2.5, mb: 0 }}>
                <li>Paste the rules, then reload Prometheus (<code>POST /-/reload</code>) or restart it.</li>
                <li>After the next check, these metrics no longer appear in Metric Usage, and the unused series total goes down.</li>
                <li>To undo: remove the rule and reload. New data starts again from the next scrape.</li>
              </Box>
            </Box>
          ) : null}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} variant="outlined" sx={{ textTransform: 'none', fontWeight: 700 }}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}

/** A query for the metric and where to put it in Grafana. Nothing is created in Grafana. */
export function AddToGrafanaDialog({ item, grafanaUrl, onClose }: { item: MetricUsageItem; grafanaUrl?: string | null; onClose: () => void }) {
  const { query, meaning } = watchQuery(item);
  const jobs = jobNames(item);
  const facts = [
    item.metric_type ? item.metric_type[0].toUpperCase() + item.metric_type.slice(1) : null,
    jobs.length ? `${jobs.length === 1 ? 'job' : 'jobs'} ${jobs.join(', ')}` : null,
    item.series !== null ? `${item.series.toLocaleString()} series` : null,
  ].filter(Boolean).join(' · ');
  const link = (path: string, label: string) => grafanaUrl ? (
    <Button size="small" variant="outlined" component={Link} href={`${grafanaUrl}${path}`} target="_blank" rel="noreferrer" sx={{ textTransform: 'none', fontWeight: 700, mt: 0.5 }}>
      {label} ↗
    </Button>
  ) : null;
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth aria-labelledby="add-dialog-title">
      <DialogTitle id="add-dialog-title" sx={{ fontWeight: 900, pb: 0.5, overflowWrap: 'anywhere' }}>
        Add {item.metric} to Grafana
        {facts ? <Typography sx={{ fontSize: 13, color: ui.muted }}>{facts}</Typography> : null}
      </DialogTitle>
      <DialogContent>
        <Stack spacing={1.5} sx={{ pt: 1 }}>
          <Box>
            <Typography sx={{ fontSize: 13, mb: 0.5 }}><b>Query</b>: {meaning}</Typography>
            <CopyBlock text={query} label="query" testId="watch-query" />
          </Box>
          <Grid container spacing={2}>
            <Grid size={{ xs: 12, sm: 6 }}>
              <Typography sx={{ fontSize: 13, fontWeight: 700 }}>Add to a dashboard</Typography>
              <Box component="ol" sx={{ fontSize: 13.5, pl: 2.5, my: 0.5 }}>
                <li>Open a dashboard → Add → Visualization.</li>
                <li>Paste the query, then save.</li>
              </Box>
              {link('/dashboard/new', 'New dashboard')}
            </Grid>
            <Grid size={{ xs: 12, sm: 6 }}>
              <Typography sx={{ fontSize: 13, fontWeight: 700 }}>Alert on it</Typography>
              <Box component="ol" sx={{ fontSize: 13.5, pl: 2.5, my: 0.5 }}>
                <li>Alerting → Alert rules → New alert rule.</li>
                <li>Paste the query and set the threshold that means trouble.</li>
              </Box>
              {link('/alerting/new', 'New alert rule')}
            </Grid>
          </Grid>
          <Typography sx={{ fontSize: 13, color: ui.muted }}>The next check moves it to Watched.</Typography>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} variant="outlined" sx={{ textTransform: 'none', fontWeight: 700 }}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}

/** How to remove a recording rule nobody reads. */
export function RemoveRuleDialog({ rule, snapshot, grafanaUrl, onClose }: {
  rule: MetricUsageUnreadRule; snapshot: MetricUsageSnapshot; grafanaUrl?: string | null; onClose: () => void;
}) {
  const groups = rule.groups.length ? rule.groups.join(', ') : 'its group';
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth aria-labelledby="rule-dialog-title">
      <DialogTitle id="rule-dialog-title" sx={{ fontWeight: 900, pb: 0.5, overflowWrap: 'anywhere' }}>
        Remove recording rule {rule.name}
        {rule.series !== null ? <Typography sx={{ fontSize: 13, color: ui.muted }}>{rule.series.toLocaleString()} series stop being stored</Typography> : null}
      </DialogTitle>
      <DialogContent>
        <Stack spacing={1.5} sx={{ pt: 1 }}>
          <CheckedNote snapshot={snapshot} grafanaUrl={grafanaUrl} what="rule" />
          {rule.warnings?.map((warning) => <Alert key={warning} severity="warning" sx={{ py: 0 }}>{warning}</Alert>)}
          <Box component="ol" sx={{ fontSize: 13.5, pl: 2.5, my: 0 }}>
            <li>In your Prometheus rules file, delete the rule <code>record: {rule.name}</code> from group <code>{groups}</code>.</li>
            {rule.feeds.length ? <li>It only feeds {rule.feeds.join(', ')}, which nothing reads either. Remove {rule.feeds.length === 1 ? 'that one' : 'those'} too.</li> : null}
            <li>Reload Prometheus (<code>POST /-/reload</code>) or restart it.</li>
          </Box>
          <Typography sx={{ fontSize: 13, color: ui.muted }}>
            The metrics it reads ({rule.reads.join(', ') || 'none'}) are not affected.
          </Typography>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} variant="outlined" sx={{ textTransform: 'none', fontWeight: 700 }}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
