import { Box, Chip, Stack, Tooltip, Typography } from '@mui/material';
import NotificationsActiveOutlinedIcon from '@mui/icons-material/NotificationsActiveOutlined';
import { Link as RouterLink } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { relativeTime, ui } from '../standalone/theme';
import type { AlertItem } from '../types';

const FIRING = '#ea580c';

function isFiring(alert: AlertItem) {
  return alert.status === 'firing';
}

function AlertStatusDot({ alert }: { alert: AlertItem }) {
  return (
    <Box
      component="span"
      aria-hidden="true"
      sx={{ width: 8, height: 8, mt: '7px', borderRadius: '50%', flex: '0 0 auto', boxSizing: 'border-box', bgcolor: isFiring(alert) ? FIRING : 'transparent', border: isFiring(alert) ? 'none' : `1.5px solid ${ui.green}` }}
    />
  );
}

function linkedTo(alert: AlertItem) {
  if (alert.case_id !== null) return { text: `Case #${alert.case_id}`, to: `/cases/${alert.case_id}` };
  if (alert.finding_id !== null) return { text: `Finding #${alert.finding_id}`, to: `/findings?finding=${alert.finding_id}` };
  return null;
}

export function AlertRow({ alert }: { alert: AlertItem }) {
  const link = linkedTo(alert);
  const statusText = `${alert.source === 'test' ? 'Test alert · ' : ''}${isFiring(alert) ? 'Firing' : 'Resolved'}`;
  return (
    <Stack direction="row" spacing={1.5} sx={{ py: 1.5, borderTop: `1px solid ${ui.border}` }}>
      <AlertStatusDot alert={alert} />
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Stack direction="row" justifyContent="space-between" spacing={1}>
          <Typography sx={{ fontWeight: 800, fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{alert.alert_name}</Typography>
          <Typography sx={{ color: ui.muted, fontSize: 12, whiteSpace: 'nowrap' }}>{relativeTime(alert.received_at)}</Typography>
        </Stack>
        <Typography sx={{ color: '#475569', fontSize: 13, mt: 0.25 }}>
          {statusText}
          {alert.service ? ` · ${alert.service}` : ''}
          {alert.severity ? ` · ${alert.severity}` : ''}
          {' · '}
          {link ? (
            <Box component={RouterLink} to={link.to} sx={{ color: ui.blue, fontWeight: 700 }}>
              linked to {link.text}
            </Box>
          ) : (
            'no matching finding yet'
          )}
        </Typography>
        {alert.summary !== alert.alert_name ? (
          <Typography sx={{ color: ui.muted, fontSize: 13, mt: 0.25, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{alert.summary}</Typography>
        ) : null}
      </Box>
    </Stack>
  );
}

export function AlertBadge({ alert }: { alert: AlertItem }) {
  const firing = isFiring(alert);
  return (
    <Tooltip title={`${alert.summary} · received ${relativeTime(alert.received_at)}`}>
      <Chip
        size="small"
        icon={<NotificationsActiveOutlinedIcon sx={{ fontSize: 14 }} />}
        label={`Alert: ${alert.alert_name}${firing ? '' : ' (resolved)'}`}
        sx={{ height: 24, fontWeight: 750, fontSize: 12, bgcolor: firing ? '#ffedd5' : '#f1f5f9', color: firing ? '#9a3412' : '#475569', '& .MuiChip-icon': { color: 'inherit' } }}
      />
    </Tooltip>
  );
}

/** Alerts that were linked to this finding. Renders nothing when there are none or the lookup fails,
 * so pages that show it look exactly as before for findings no alert pointed at. */
export function LinkedAlerts({ findingId }: { findingId: number | null | undefined }) {
  const alertsQuery = useQuery({
    queryKey: ['alerts', 'finding', findingId],
    queryFn: () => api.alerts({ finding_id: findingId!, limit: 10 }),
    enabled: typeof findingId === 'number',
    retry: false,
  });
  const alerts = alertsQuery.data ?? [];
  if (!alerts.length) return null;
  return (
    <Stack direction="row" spacing={1} aria-label="Linked alerts" sx={{ flexWrap: 'wrap', gap: 1, my: 1 }}>
      {alerts.map((alert) => <AlertBadge key={alert.id} alert={alert} />)}
    </Stack>
  );
}

export function alertsByFinding(alerts: AlertItem[]): Map<number, AlertItem> {
  const byFinding = new Map<number, AlertItem>();
  for (const alert of alerts) {
    if (alert.finding_id !== null && !byFinding.has(alert.finding_id)) byFinding.set(alert.finding_id, alert);
  }
  return byFinding;
}
