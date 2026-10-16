import { Alert, Box, Chip, Stack, Typography } from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { WorkspacePanel } from '../standalone/components';
import { formatDateTime, ui } from '../standalone/theme';
import type { SlackStatus } from '../types';

/** Integrations-page view of Slack finding notifications: whether messages are arriving. A message
 * Slack doesn't take is retried for about 18 minutes before it counts as failed; until this card,
 * a failure only showed in the backend log. */
export function SlackDeliveryCard() {
  const statusQuery = useQuery({ queryKey: ['slack-status'], queryFn: () => api.slackStatus(), retry: false, refetchInterval: 30_000 });
  const status = statusQuery.data;

  return (
    <WorkspacePanel sx={{ p: 2.5 }}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
        <Typography variant="h6" sx={{ fontSize: 18, fontWeight: 900 }}>Slack notifications</Typography>
        {status ? <Chip size="small" label={stateLabel(status)} color={stateColor(status)} sx={{ fontWeight: 800 }} /> : null}
      </Stack>
      <Typography sx={{ color: ui.muted, fontSize: 13, mb: 1.5 }}>
        New problems, and problems that got worse, posted to your Slack channel. Messages Slack doesn't take are retried.
      </Typography>

      {statusQuery.isError ? <Typography color="text.secondary">Slack status could not be loaded.</Typography> : null}

      {status && !status.enabled ? (
        <Typography color="text.secondary" sx={{ fontSize: 14 }}>
          Off. To turn it on, set <code>OPS_SIGNALS_SLACK_ENABLED=true</code> and <code>OPS_SIGNALS_SLACK_WEBHOOK_URL</code>, then restart the backend.
        </Typography>
      ) : null}

      {status?.enabled ? (
        <Stack spacing={1.5}>
          <Box component="dl" sx={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', columnGap: 2, rowGap: 0.5, m: 0, fontSize: 14 }}>
            <Detail label="Delivered (24 h)" value={String(status.delivered_last_24h)} />
            <Detail label="Waiting to retry" value={String(status.retrying)} />
            <Detail label="Failed (24 h)" value={String(status.failed_last_24h)} />
          </Box>
          {status.last_failure && (status.retrying > 0 || status.failed_last_24h > 0) ? (
            <Alert severity={status.last_failure.status === 'failed' ? 'error' : 'warning'}>
              <Typography sx={{ fontSize: 14, fontWeight: 800 }}>
                {status.last_failure.status === 'failed' ? 'Not delivered' : 'Retrying'}: {status.last_failure.title}
                {status.last_failure.service ? ` (${status.last_failure.service})` : ''}
              </Typography>
              <Typography sx={{ fontSize: 13 }}>
                {status.last_failure.error ?? 'Slack did not accept the message.'} · {status.last_failure.attempts} attempt{status.last_failure.attempts === 1 ? '' : 's'}
                {status.last_failure.next_retry_at ? ` · next try ${formatDateTime(status.last_failure.next_retry_at)}` : ''}
              </Typography>
            </Alert>
          ) : null}
        </Stack>
      ) : null}
    </WorkspacePanel>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <>
      <Typography component="dt" sx={{ color: ui.muted, fontSize: 14 }}>{label}</Typography>
      <Typography component="dd" sx={{ m: 0, fontSize: 14, fontWeight: 700 }}>{value}</Typography>
    </>
  );
}

function stateLabel(status: SlackStatus) {
  if (!status.enabled) return 'Off';
  if (status.failed_last_24h > 0) return 'Messages failed';
  if (status.retrying > 0) return 'Retrying';
  return 'Delivering';
}

function stateColor(status: SlackStatus): 'default' | 'success' | 'warning' | 'error' {
  if (!status.enabled) return 'default';
  if (status.failed_last_24h > 0) return 'error';
  if (status.retrying > 0) return 'warning';
  return 'success';
}
