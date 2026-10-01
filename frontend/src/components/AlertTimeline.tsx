import { Box, Button, Collapse, Stack, Tooltip, Typography } from '@mui/material';
import KeyboardArrowDownRoundedIcon from '@mui/icons-material/KeyboardArrowDownRounded';
import KeyboardArrowUpRoundedIcon from '@mui/icons-material/KeyboardArrowUpRounded';
import { Link as RouterLink } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { api } from '../api/queries';
import { WorkspacePanel } from '../standalone/components';
import { relativeTime, ui } from '../standalone/theme';
import type { AlertChange, AlertItem } from '../types';
import { changeLabel, whatChanged } from '../utils/alertChanges';
import { AlertInsight, AlertRow } from './AlertComponents';

const WINDOW_HOURS = 24;
const HOUR_MS = 3_600_000;

// Fixed status colors (never reused for anything else), always shown next to a text label.
// Three alert levels map onto the status scale: critical -> critical, warning -> serious, anything
// else (info, none) -> a neutral slate, so only the levels that need attention carry a hue.
const SEVERITY_STYLES = {
  critical: { label: 'Critical', color: '#d03b3b', rank: 0 },
  warning: { label: 'Warning', color: '#ec835a', rank: 1 },
  other: { label: 'Info', color: '#94a3b8', rank: 2 },
} as const;
type SeverityKey = keyof typeof SEVERITY_STYLES;

export function severityKey(severity: string | null | undefined): SeverityKey {
  const value = (severity ?? '').toLowerCase();
  if (value === 'critical' || value === 'page' || value === 'high') return 'critical';
  if (value === 'warning' || value === 'warn' || value === 'medium') return 'warning';
  return 'other';
}

export type AlertGroup = {
  key: string;
  alertName: string;
  service: string | null;
  severity: SeverityKey;
  firing: boolean;
  isTest: boolean;
  /** Newest first. */
  occurrences: AlertItem[];
  lastReceivedAt: string;
  link: { text: string; to: string } | null;
};

function linkFor(alert: AlertItem) {
  if (alert.case_id !== null) return { text: `Case #${alert.case_id}`, to: `/cases/${alert.case_id}` };
  if (alert.finding_id !== null) return { text: `Finding #${alert.finding_id}`, to: `/findings?finding=${alert.finding_id}` };
  return null;
}

/** One group per alert rule (name + service): the list shows a rule once, not every occurrence.
 * Firing groups first, then linked ones, then the most recent. */
export function groupAlerts(alerts: AlertItem[]): AlertGroup[] {
  const groups = new Map<string, AlertItem[]>();
  for (const alert of alerts) {
    const key = `${alert.alert_name}\u0000${alert.service ?? ''}`;
    groups.set(key, [...(groups.get(key) ?? []), alert]);
  }
  return [...groups.entries()]
    .map(([key, items]) => {
      const occurrences = [...items].sort((a, b) => Date.parse(b.received_at) - Date.parse(a.received_at));
      const latest = occurrences[0];
      const linked = occurrences.find((item) => item.case_id !== null || item.finding_id !== null);
      const worst = occurrences.map((item) => severityKey(item.severity)).sort((a, b) => SEVERITY_STYLES[a].rank - SEVERITY_STYLES[b].rank)[0];
      return {
        key,
        alertName: latest.alert_name,
        service: latest.service,
        severity: worst,
        firing: occurrences.some((item) => item.status === 'firing'),
        isTest: latest.source === 'test',
        occurrences,
        lastReceivedAt: latest.received_at,
        link: linked ? linkFor(linked) : null,
      };
    })
    .sort((a, b) => Number(b.firing) - Number(a.firing) || Number(Boolean(b.link)) - Number(Boolean(a.link)) || Date.parse(b.lastReceivedAt) - Date.parse(a.lastReceivedAt));
}

export function summarizeAlerts(alerts: AlertItem[]) {
  return {
    firing: alerts.filter((alert) => alert.status === 'firing').length,
    linked: alerts.filter((alert) => alert.finding_id !== null).length,
    resolved: alerts.filter((alert) => alert.status !== 'firing').length,
  };
}

function formatTime(value: string | number) {
  return new Date(value).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function formatDuration(ms: number) {
  const minutes = Math.max(1, Math.round(ms / 60_000));
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return minutes % 60 ? `${hours}h ${minutes % 60}m` : `${hours}h`;
}

function SeverityLabel({ severity }: { severity: SeverityKey }) {
  const style = SEVERITY_STYLES[severity];
  return (
    <Stack direction="row" alignItems="center" spacing={0.6} component="span">
      <Box component="span" aria-hidden="true" sx={{ width: 8, height: 8, borderRadius: '2px', bgcolor: style.color }} />
      <Typography component="span" sx={{ fontSize: 12, color: '#475569' }}>{style.label}</Typography>
    </Stack>
  );
}

function SummaryLine({ alerts }: { alerts: AlertItem[] }) {
  const summary = summarizeAlerts(alerts);
  const item = (value: number, label: string, color: string) => (
    <Stack direction="row" alignItems="baseline" spacing={0.6}>
      <Typography component="span" sx={{ fontSize: 22, fontWeight: 900, color: value ? color : ui.muted, lineHeight: 1 }}>{value}</Typography>
      <Typography component="span" sx={{ fontSize: 13, color: '#475569' }}>{label}</Typography>
    </Stack>
  );
  return (
    <Stack direction="row" spacing={3} sx={{ flexWrap: 'wrap', rowGap: 1 }} aria-label="Alert summary">
      {item(summary.firing, 'firing now', '#b42318')}
      {item(summary.linked, 'linked to a finding', ui.blue)}
      {item(summary.resolved, `resolved (${WINDOW_HOURS}h)`, ui.text)}
    </Stack>
  );
}

function TimelineBar({ alert, windowStart, now }: { alert: AlertItem; windowStart: number; now: number }) {
  const span = now - windowStart;
  const start = Math.max(Date.parse(alert.starts_at), windowStart);
  const firing = alert.status === 'firing';
  const end = firing || !alert.ends_at ? now : Math.min(Date.parse(alert.ends_at), now);
  if (end < windowStart) return null;
  const left = ((start - windowStart) / span) * 100;
  const width = Math.max(((end - start) / span) * 100, 0.6);
  const color = SEVERITY_STYLES[severityKey(alert.severity)].color;
  const link = linkFor(alert);
  const changed = whatChanged(alert);
  const title = (
    <Box sx={{ fontSize: 12, lineHeight: 1.5 }}>
      <strong>{alert.alert_name}</strong>
      <br />
      {firing ? 'Firing' : 'Resolved'} · {SEVERITY_STYLES[severityKey(alert.severity)].label}
      {alert.service ? ` · ${alert.service}` : ''}
      <br />
      {formatTime(Date.parse(alert.starts_at))} → {firing ? 'now' : alert.ends_at ? formatTime(alert.ends_at) : 'unknown'} ({formatDuration(end - Date.parse(alert.starts_at))})
      {link ? <><br />Linked to {link.text}</> : null}
      {changed ? <><br />{changed.lines[0]}</> : null}
    </Box>
  );
  return (
    <>
      <Tooltip title={title} placement="top" arrow>
        {/* Hit target taller than the drawn bar. */}
        <Box
          tabIndex={0}
          aria-label={`${alert.alert_name}, ${firing ? 'firing' : 'resolved'}, ${formatTime(start)}`}
          sx={{ position: 'absolute', left: `${left}%`, width: `${width}%`, minWidth: 6, top: 0, bottom: 0, display: 'flex', alignItems: 'center', cursor: 'default', outline: 'none', '&:focus-visible > span': { boxShadow: `0 0 0 2px ${ui.blue}` } }}
        >
          <Box
            component="span"
            sx={{
              display: 'block',
              width: '100%',
              height: 12,
              bgcolor: color,
              opacity: firing ? 1 : 0.4,
              borderRadius: firing ? '4px 0 0 4px' : '4px',
            }}
          />
        </Box>
      </Tooltip>
      {link ? (
        <Tooltip title={`Linked to ${link.text}`} placement="top" arrow>
          <Box
            component={RouterLink}
            to={link.to}
            aria-label={`${alert.alert_name} linked to ${link.text}`}
            sx={{ position: 'absolute', left: `calc(${left}% - 7px)`, top: '50%', width: 14, height: 14, transform: 'translateY(-50%)', display: 'grid', placeItems: 'center', zIndex: 1 }}
          >
            <Box component="span" sx={{ width: 10, height: 10, bgcolor: ui.blue, transform: 'rotate(45deg)', boxShadow: '0 0 0 2px #ffffff', borderRadius: '1px' }} />
          </Box>
        </Tooltip>
      ) : null}
    </>
  );
}

/** The change events matched to any of the group's alerts, once each. */
export function groupChanges(group: AlertGroup): AlertChange[] {
  const seen = new Map<string, AlertChange>();
  for (const alert of group.occurrences) {
    for (const change of alert.changes ?? []) {
      const key = change.id !== null ? String(change.id) : `${change.version}|${change.timestamp}`;
      if (change.timestamp && !seen.has(key)) seen.set(key, change);
    }
  }
  return [...seen.values()];
}

function ChangeMarker({ change, windowStart, now }: { change: AlertChange; windowStart: number; now: number }) {
  const at = Date.parse(change.timestamp ?? '');
  if (Number.isNaN(at) || at < windowStart || at > now) return null;
  const label = `${changeLabel(change)} · ${formatTime(at)}`;
  return (
    <Tooltip title={label} placement="top" arrow>
      <Box
        tabIndex={0}
        aria-label={label}
        sx={{ position: 'absolute', left: `calc(${((at - windowStart) / (now - windowStart)) * 100}% - 6px)`, top: -2, width: 12, height: 10, zIndex: 2, display: 'grid', placeItems: 'center', outline: 'none', '&:focus-visible': { boxShadow: `0 0 0 2px ${ui.blue}` } }}
      >
        <Box component="span" sx={{ width: 0, height: 0, borderLeft: '5px solid transparent', borderRight: '5px solid transparent', borderTop: '7px solid #3730a3' }} />
      </Box>
    </Tooltip>
  );
}

const TICKS = [0, 0.25, 0.5, 0.75, 1];

function tickLabel(fraction: number) {
  if (fraction === 1) return 'now';
  return `${Math.round((1 - fraction) * WINDOW_HOURS)}h ago`;
}

export function AlertTimeline({ groups, now, maxLanes = 8 }: { groups: AlertGroup[]; now: number; maxLanes?: number }) {
  const windowStart = now - WINDOW_HOURS * HOUR_MS;
  const lanes = groups.slice(0, maxLanes);
  const hidden = groups.length - lanes.length;
  const labelWidth = { xs: 140, md: 230 };

  return (
    <Box role="figure" aria-label={`Alert timeline, last ${WINDOW_HOURS} hours`}>
      <Stack spacing={0.5}>
        {lanes.map((group) => (
          <Stack key={group.key} direction="row" alignItems="center" spacing={1.5} sx={{ minHeight: 28 }}>
            <Box sx={{ width: labelWidth, flex: '0 0 auto', minWidth: 0 }}>
              <Typography sx={{ fontSize: 13, fontWeight: 800, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={group.alertName}>
                {group.alertName}
              </Typography>
              <Typography sx={{ fontSize: 11, color: ui.muted, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {group.service ?? 'no service'}
              </Typography>
            </Box>
            <Box sx={{ position: 'relative', flex: 1, height: 24, borderRadius: '4px', bgcolor: '#f8fafc' }}>
              {TICKS.slice(1, -1).map((fraction) => (
                <Box key={fraction} aria-hidden="true" sx={{ position: 'absolute', left: `${fraction * 100}%`, top: 0, bottom: 0, borderLeft: `1px dashed ${ui.border}` }} />
              ))}
              {[...group.occurrences].reverse().map((alert) => (
                <TimelineBar key={alert.id} alert={alert} windowStart={windowStart} now={now} />
              ))}
              {groupChanges(group).map((change) => (
                <ChangeMarker key={`${change.id}|${change.timestamp}`} change={change} windowStart={windowStart} now={now} />
              ))}
            </Box>
          </Stack>
        ))}
        <Stack direction="row" spacing={1.5}>
          <Box sx={{ width: labelWidth, flex: '0 0 auto' }} />
          <Box sx={{ position: 'relative', flex: 1, height: 16 }} aria-hidden="true">
            {TICKS.map((fraction) => (
              <Typography
                key={fraction}
                sx={{ position: 'absolute', left: `${fraction * 100}%`, transform: fraction === 0 ? 'none' : fraction === 1 ? 'translateX(-100%)' : 'translateX(-50%)', fontSize: 11, color: ui.muted, whiteSpace: 'nowrap' }}
              >
                {tickLabel(fraction)}
              </Typography>
            ))}
          </Box>
        </Stack>
      </Stack>
      {hidden > 0 ? <Typography sx={{ fontSize: 12, color: ui.muted, mt: 0.5 }}>+{hidden} more alert {hidden === 1 ? 'rule' : 'rules'} in the list below</Typography> : null}
      <Stack direction="row" spacing={2} sx={{ mt: 1.5, flexWrap: 'wrap', rowGap: 0.75 }} aria-label="Timeline legend">
        {(Object.keys(SEVERITY_STYLES) as SeverityKey[]).map((key) => <SeverityLabel key={key} severity={key} />)}
        <Stack direction="row" alignItems="center" spacing={0.6}>
          <Box aria-hidden="true" sx={{ width: 18, height: 8, borderRadius: '2px', bgcolor: '#64748b' }} />
          <Typography sx={{ fontSize: 12, color: '#475569' }}>firing</Typography>
          <Box aria-hidden="true" sx={{ width: 18, height: 8, borderRadius: '2px', bgcolor: '#64748b', opacity: 0.4, ml: 1 }} />
          <Typography sx={{ fontSize: 12, color: '#475569' }}>resolved</Typography>
        </Stack>
        <Stack direction="row" alignItems="center" spacing={0.6}>
          <Box aria-hidden="true" sx={{ width: 8, height: 8, bgcolor: ui.blue, transform: 'rotate(45deg)' }} />
          <Typography sx={{ fontSize: 12, color: '#475569' }}>linked to a finding</Typography>
        </Stack>
        <Stack direction="row" alignItems="center" spacing={0.6}>
          <Box aria-hidden="true" sx={{ width: 0, height: 0, borderLeft: '5px solid transparent', borderRight: '5px solid transparent', borderTop: '7px solid #3730a3' }} />
          <Typography sx={{ fontSize: 12, color: '#475569' }}>deploy or other change</Typography>
        </Stack>
      </Stack>
    </Box>
  );
}

function GroupRow({ group }: { group: AlertGroup }) {
  const [open, setOpen] = useState(false);
  const count = group.occurrences.length;
  return (
    <Box sx={{ borderTop: `1px solid ${ui.border}` }}>
      <Stack direction="row" alignItems="center" spacing={1.5} sx={{ py: 1.25 }}>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Stack direction="row" alignItems="center" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 0.5 }}>
            <Typography sx={{ fontWeight: 800, fontSize: 14 }}>{group.alertName}</Typography>
            {group.firing ? (
              <Box component="span" sx={{ fontSize: 11, fontWeight: 800, px: 0.8, py: 0.1, borderRadius: '999px', bgcolor: '#fee4e2', color: '#b42318' }}>FIRING</Box>
            ) : (
              <Box component="span" sx={{ fontSize: 11, fontWeight: 800, px: 0.8, py: 0.1, borderRadius: '999px', bgcolor: '#f1f5f9', color: '#475569' }}>RESOLVED</Box>
            )}
            {group.isTest ? <Box component="span" sx={{ fontSize: 11, fontWeight: 800, px: 0.8, py: 0.1, borderRadius: '999px', bgcolor: '#eef2ff', color: '#3730a3' }}>TEST</Box> : null}
          </Stack>
          <Stack direction="row" alignItems="center" spacing={1} sx={{ mt: 0.3, flexWrap: 'wrap', rowGap: 0.5, fontSize: 13, color: '#475569' }}>
            <SeverityLabel severity={group.severity} />
            <Typography component="span" sx={{ fontSize: 13, color: '#475569' }}>
              · {group.service ?? 'no service'} · {count}× in {WINDOW_HOURS}h · last {relativeTime(group.lastReceivedAt)} ·{' '}
            </Typography>
            {group.link ? (
              <Box component={RouterLink} to={group.link.to} sx={{ fontSize: 13, color: ui.blue, fontWeight: 700 }}>
                linked to {group.link.text}
              </Box>
            ) : (
              <Typography component="span" sx={{ fontSize: 13, color: ui.muted }}>no matching finding yet</Typography>
            )}
          </Stack>
          <AlertInsight alert={group.occurrences[0]} />
        </Box>
        {count > 1 ? (
          <Button
            size="small"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            endIcon={open ? <KeyboardArrowUpRoundedIcon /> : <KeyboardArrowDownRoundedIcon />}
            sx={{ textTransform: 'none', fontWeight: 750, whiteSpace: 'nowrap' }}
          >
            {open ? 'Hide' : `${count} occurrences`}
          </Button>
        ) : null}
      </Stack>
      {count > 1 ? (
        <Collapse in={open} unmountOnExit>
          <Box sx={{ pl: 2, pb: 1 }}>
            {group.occurrences.map((alert) => <AlertRow key={alert.id} alert={alert} />)}
          </Box>
        </Collapse>
      ) : null}
    </Box>
  );
}

type AlertsOverviewPanelProps = {
  title: string;
  /** full: summary, timeline and grouped list. compact: summary and timeline only. */
  variant?: 'full' | 'compact';
  hideWhenEmpty?: boolean;
  viewAllTo?: string;
  maxLanes?: number;
};

export function AlertsOverviewPanel({ title, variant = 'full', hideWhenEmpty = false, viewAllTo, maxLanes }: AlertsOverviewPanelProps) {
  const alertsQuery = useQuery({
    queryKey: ['alerts', 'timeline', WINDOW_HOURS],
    queryFn: () => api.alerts({ since: new Date(Date.now() - WINDOW_HOURS * HOUR_MS).toISOString(), limit: 500 }),
    retry: false,
    refetchInterval: 30_000,
  });
  const alerts = alertsQuery.data ?? [];
  if (hideWhenEmpty && !alerts.length) return null;

  const groups = groupAlerts(alerts);
  const now = alertsQuery.dataUpdatedAt || Date.now();

  return (
    <WorkspacePanel sx={{ p: 2.5, height: '100%', boxSizing: 'border-box' }}>
      <Box component="section" aria-label={title}>
        <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1.5 }}>
          <Box>
            <Typography component="h2" sx={{ fontWeight: 900, fontSize: 18 }}>{title}</Typography>
            <Typography sx={{ fontSize: 12, color: ui.muted }}>Last {WINDOW_HOURS} hours</Typography>
          </Box>
          {viewAllTo ? (
            <Button component={RouterLink} to={viewAllTo} size="small" sx={{ textTransform: 'none', fontWeight: 750 }}>
              All alerts →
            </Button>
          ) : null}
        </Stack>
        {alertsQuery.isLoading ? <Typography color="text.secondary" sx={{ py: 1.5 }}>Loading alerts…</Typography> : null}
        {alertsQuery.isError ? <Typography color="text.secondary" sx={{ py: 1.5 }}>Could not load received alerts.</Typography> : null}
        {alertsQuery.isSuccess && !alerts.length ? (
          <Typography color="text.secondary" sx={{ py: 1.5, px: 2, border: '1px dashed #cbd5e1', borderRadius: '8px', textAlign: 'center' }}>
            No alerts in the last {WINDOW_HOURS} hours. They appear here with the finding or case they were linked to.
          </Typography>
        ) : null}
        {alerts.length ? (
          <Stack spacing={2.5}>
            <SummaryLine alerts={alerts} />
            <AlertTimeline groups={groups} now={now} maxLanes={maxLanes ?? (variant === 'compact' ? 5 : 8)} />
            {variant === 'full' ? (
              <Box aria-label="Alert rules">
                {groups.map((group) => <GroupRow key={group.key} group={group} />)}
              </Box>
            ) : null}
          </Stack>
        ) : null}
      </Box>
    </WorkspacePanel>
  );
}
