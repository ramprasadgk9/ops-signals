import { Box, Button, Chip, Grid2 as Grid, IconButton, Stack, Tooltip, Typography } from '@mui/material';
import ContentCopyRoundedIcon from '@mui/icons-material/ContentCopyRounded';
import ShowChartRoundedIcon from '@mui/icons-material/ShowChartRounded';
import NotificationsActiveOutlinedIcon from '@mui/icons-material/NotificationsActiveOutlined';
import StorageRoundedIcon from '@mui/icons-material/StorageRounded';
import UploadFileRoundedIcon from '@mui/icons-material/UploadFileRounded';
import { Link as RouterLink } from 'react-router-dom';
import type { ReactNode } from 'react';
import { WorkspacePanel } from '../standalone/components';
import { LoadDemoDataButton, SendTestAlertButton } from './IntegrationActions';
import { relativeTime, ui } from '../standalone/theme';
import type { IngestionStatus } from '../types';

type SourceState = 'receiving' | 'waiting' | 'disabled' | 'configured' | 'not_configured';

const stateStyles: Record<SourceState, { bg: string; color: string; border: string; dot: string; filled: boolean }> = {
  receiving: { bg: '#dcfce7', color: '#166534', border: '#bbf7d0', dot: ui.green, filled: true },
  configured: { bg: '#dcfce7', color: '#166534', border: '#bbf7d0', dot: ui.green, filled: true },
  waiting: { bg: '#ffffff', color: '#475569', border: '#cbd5e1', dot: '#94a3b8', filled: false },
  not_configured: { bg: '#ffffff', color: '#475569', border: '#cbd5e1', dot: '#94a3b8', filled: false },
  disabled: { bg: '#f1f5f9', color: '#475569', border: '#e2e8f0', dot: '#94a3b8', filled: false },
};

export function otlpState(status: IngestionStatus): SourceState {
  return status.sources.otlp.last_received_at ? 'receiving' : 'waiting';
}

export function alertmanagerState(status: IngestionStatus): SourceState {
  const alertmanager = status.sources.alertmanager;
  if (alertmanager.last_received_at) return 'receiving';
  return alertmanager.enabled ? 'waiting' : 'disabled';
}

export function prometheusState(status: IngestionStatus): SourceState {
  return status.sources.prometheus.configured ? 'configured' : 'not_configured';
}

function endpointUrl(path: string) {
  return `${window.location.origin}${path}`;
}

function copyText(text: string) {
  void navigator.clipboard?.writeText(text);
}

function StatusDot({ state }: { state: SourceState }) {
  const style = stateStyles[state];
  return (
    <Box
      component="span"
      aria-hidden="true"
      sx={{ width: 8, height: 8, borderRadius: '50%', flex: '0 0 auto', boxSizing: 'border-box', bgcolor: style.filled ? style.dot : 'transparent', border: style.filled ? 'none' : `1.5px solid ${style.dot}` }}
    />
  );
}

function StateChip({ state, label }: { state: SourceState; label: string }) {
  const style = stateStyles[state];
  return (
    <Chip
      size="small"
      icon={<StatusDot state={state} />}
      label={label}
      sx={{ height: 24, bgcolor: style.bg, color: style.color, border: `1px solid ${style.border}`, fontWeight: 700, fontSize: 12, '& .MuiChip-icon': { ml: 1 } }}
    />
  );
}

function CopyableEndpoint({ url, label }: { url: string; label: string }) {
  return (
    <Stack direction="row" alignItems="center" spacing={1}>
      <Typography variant="body2" sx={{ flex: 1, minWidth: 0, fontFamily: 'monospace', fontSize: 13, bgcolor: '#f1f5f9', px: 1.5, py: 0.9, borderRadius: '6px', wordBreak: 'break-all' }}>
        {url}
      </Typography>
      <Tooltip title="Copy">
        <IconButton size="small" onClick={() => copyText(url)} aria-label={label}>
          <ContentCopyRoundedIcon fontSize="small" />
        </IconButton>
      </Tooltip>
    </Stack>
  );
}

function Snippet({ children }: { children: string }) {
  return (
    <Box component="pre" sx={{ m: 0, p: 1.5, borderRadius: '6px', bgcolor: '#0f172a', color: '#e2e8f0', fontSize: 12, lineHeight: 1.6, overflowX: 'auto' }}>
      {children}
    </Box>
  );
}

function SourceTile({ icon, title, chip, children }: { icon: ReactNode; title: string; chip?: ReactNode; children: ReactNode }) {
  return (
    <Box sx={{ border: `1px solid ${ui.border}`, borderRadius: '8px', p: 2.5, height: '100%', boxSizing: 'border-box' }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={1} sx={{ mb: 1.5 }}>
        <Stack direction="row" alignItems="center" spacing={1.2} sx={{ minWidth: 0 }}>
          <Box sx={{ color: ui.blue, display: 'grid' }}>{icon}</Box>
          <Typography component="h3" sx={{ fontWeight: 800, fontSize: 16 }}>{title}</Typography>
        </Stack>
        {chip}
      </Stack>
      <Stack spacing={1.5}>{children}</Stack>
    </Box>
  );
}

export function IntegrationTiles({ status }: { status: IngestionStatus }) {
  const otlpUrl = endpointUrl(status.sources.otlp.endpoint_path);
  const alertmanager = status.sources.alertmanager;
  const alertUrl = endpointUrl(alertmanager.endpoint_path);
  const alertState = alertmanagerState(status);
  const promState = prometheusState(status);

  const alertmanagerYaml = [
    'receivers:',
    '  - name: ops-signals',
    '    webhook_configs:',
    `      - url: ${alertUrl}`,
    '        send_resolved: true',
    ...(alertmanager.token_required ? ['        http_config:', '          authorization:', '            credentials: <receiver token>'] : []),
  ].join('\n');

  return (
    <Grid container spacing={2}>
      <Grid size={{ xs: 12, lg: 6 }}>
        <SourceTile icon={<ShowChartRoundedIcon />} title="Send metrics via OTLP" chip={<StateChip state={otlpState(status)} label={status.sources.otlp.last_received_at ? `Receiving · ${relativeTime(status.sources.otlp.last_received_at)}` : 'Waiting for data'} />}>
          <Typography variant="body2" color="text.secondary">
            Point an OTel Collector’s <code>otlphttp</code> exporter, or an OTel SDK, at this endpoint. Gauge and Sum metrics are analyzed automatically.
          </Typography>
          <CopyableEndpoint url={otlpUrl} label="Copy OTLP endpoint URL" />
          <Snippet>{['exporters:', '  otlphttp/ops-signals:', `    metrics_endpoint: ${otlpUrl}`].join('\n')}</Snippet>
        </SourceTile>
      </Grid>

      <Grid size={{ xs: 12, lg: 6 }}>
        <SourceTile
          icon={<NotificationsActiveOutlinedIcon />}
          title="Connect Alertmanager"
          chip={<StateChip state={alertState} label={alertState === 'receiving' ? `Receiving · ${relativeTime(alertmanager.last_received_at)}` : alertState === 'waiting' ? 'Waiting for alerts' : 'Disabled'} />}
        >
          <Typography variant="body2" color="text.secondary">
            Add Ops Signals as a webhook receiver. Incoming alerts are enriched with related findings and recent changes.
          </Typography>
          {alertmanager.enabled ? null : (
            <Typography variant="body2" sx={{ bgcolor: '#fff7ed', color: '#7c2d12', px: 1.5, py: 1, borderRadius: '6px' }}>
              Alert enrichment is off. Set <code>OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED=true</code> on the backend to accept alerts.
            </Typography>
          )}
          {alertmanager.received_24h > 0 ? (
            <Typography variant="body2" sx={{ fontWeight: 700 }}>
              {alertmanager.received_24h} {alertmanager.received_24h === 1 ? 'alert' : 'alerts'} received in the last 24h
            </Typography>
          ) : null}
          <CopyableEndpoint url={alertUrl} label="Copy Alertmanager webhook URL" />
          <Snippet>{alertmanagerYaml}</Snippet>
          {alertmanager.enabled ? <SendTestAlertButton /> : null}
        </SourceTile>
      </Grid>

      <Grid size={{ xs: 12, lg: 6 }}>
        <SourceTile icon={<StorageRoundedIcon />} title="Pull from Prometheus" chip={<StateChip state={promState} label={promState === 'configured' ? 'Configured' : 'Not configured'} />}>
          <Typography variant="body2" color="text.secondary">
            Ops Signals can query an existing Prometheus on a schedule. Set <code>OPS_SIGNALS_PROMETHEUS_URL</code>, then choose what to watch.
          </Typography>
          {promState === 'configured' ? (
            <Box>
              <Button component={RouterLink} to="/autonomous-monitoring" size="small" sx={{ textTransform: 'none', fontWeight: 750, px: 0 }}>
                Set up autonomous analysis →
              </Button>
            </Box>
          ) : null}
        </SourceTile>
      </Grid>

      <Grid size={{ xs: 12, lg: 6 }}>
        <SourceTile icon={<UploadFileRoundedIcon />} title="Just exploring?">
          <Typography variant="body2" color="text.secondary">
            Load a demo checkout series to see a finding in seconds, or upload your own CSV. Generic, Prometheus and Datadog CSV exports are supported.
          </Typography>
          <LoadDemoDataButton />
        </SourceTile>
      </Grid>
    </Grid>
  );
}

export function GetDataInPanel({ status, onDismiss }: { status: IngestionStatus; onDismiss?: () => void }) {
  const receiving = status.has_any_data;
  return (
    <WorkspacePanel sx={{ p: 3 }}>
      <Box component="section" aria-labelledby="get-data-in-title">
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={2}>
          <Box>
            <Typography sx={{ fontSize: 12, fontWeight: 800, letterSpacing: '0.08em', textTransform: 'uppercase', color: ui.blue }}>Get data in</Typography>
            <Typography id="get-data-in-title" component="h2" sx={{ fontSize: 22, fontWeight: 900, mt: 0.5 }}>
              {receiving ? 'Data is arriving' : 'Ops Signals hasn’t received any data yet'}
            </Typography>
            <Typography sx={{ color: '#475569', mt: 0.5, mb: 2.5, maxWidth: 720 }}>
              {receiving
                ? 'Analysis has started. You can close this panel; every source stays available on the Integrations page.'
                : 'Findings, cases and behavior analysis start once metrics or alerts arrive. Connect any source below. Its status turns green when the first data lands.'}
            </Typography>
          </Box>
          {onDismiss ? (
            <Button onClick={onDismiss} variant="outlined" size="small" sx={{ textTransform: 'none', fontWeight: 750, flex: '0 0 auto' }}>
              Close
            </Button>
          ) : null}
        </Stack>

        <IntegrationTiles status={status} />
      </Box>
    </WorkspacePanel>
  );
}

export function SourceStatusStrip({ status }: { status: IngestionStatus }) {
  const items: Array<{ label: string; state: SourceState; detail?: string }> = [
    { label: 'OTLP', state: otlpState(status), detail: status.sources.otlp.last_received_at ? relativeTime(status.sources.otlp.last_received_at) : undefined },
    { label: 'Alertmanager', state: alertmanagerState(status), detail: status.sources.alertmanager.last_received_at ? relativeTime(status.sources.alertmanager.last_received_at) : alertmanagerState(status) === 'disabled' ? 'off' : undefined },
    { label: 'Prometheus', state: prometheusState(status) },
  ];
  return (
    <Stack
      role="status"
      aria-label="Data sources"
      direction="row"
      alignItems="center"
      spacing={1.75}
      sx={{ px: 1.75, py: 0.9, bgcolor: '#ffffff', border: `1px solid ${ui.border}`, borderRadius: '999px', fontSize: 13, color: '#334155', flexWrap: 'wrap', rowGap: 0.5 }}
    >
      {items.map((item) => (
        <Stack key={item.label} direction="row" alignItems="center" spacing={0.75}>
          <StatusDot state={item.state} />
          <Typography component="span" sx={{ fontSize: 13 }}>
            {item.label}
            {item.detail ? ` · ${item.detail}` : ''}
          </Typography>
        </Stack>
      ))}
    </Stack>
  );
}
