import { Box, Button, Stack, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import { WorkspacePanel } from '../standalone/components';
import { ui } from '../standalone/theme';
import { findingLevel } from '../utils/findingLevel';
import { openLabel, watchHref, watchLabel } from '../utils/shiftHandoff';
import { AlertBadge } from './AlertComponents';
import type { AlertItem, HandoffWatchItem, ShiftHandoff } from '../types';

// The Overview's top: one answer to "what needs me now?" and one work list, both in the shift
// handoff's order (backend/app/services/shift_handoff.py), so the page never names two different
// top problems.

/** Findings store critical / significant / normal; combined patterns and some cases use the alert
 * words. Both read as High / Medium / Low, as on the Findings page. */
const ALERT_WORDS: Record<string, string> = { high: 'critical', medium: 'significant', low: 'normal' };

export function itemLevel(severity?: string | null) {
  const key = (severity ?? '').toLowerCase();
  return findingLevel(ALERT_WORDS[key] ?? key);
}

export type FocusCount = { label: string; to?: string };

export function LookFirstPanel({ handoff, counts }: { handoff: ShiftHandoff; counts: FocusCount[] }) {
  const first = handoff.watch[0];
  const live = first?.live ? first : null;
  return (
    <WorkspacePanel sx={{ p: 2.5, borderLeft: `4px solid ${live ? ui.orange : ui.green}` }}>
      <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', md: 'center' }} spacing={2} data-testid="look-first">
        <Box sx={{ minWidth: 0 }}>
          <Typography sx={{ color: live ? ui.orange : ui.green, fontSize: 12, fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            {live ? 'Look at this first' : 'Nothing new needs you'}
          </Typography>
          {live ? (
            <>
              <Typography sx={{ fontWeight: 900, fontSize: 19, mt: 0.25 }}>{watchLabel(live)}</Typography>
              <Typography sx={{ mt: 0.25 }}>{live.title}: {live.reason}.</Typography>
            </>
          ) : (
            <Typography sx={{ fontWeight: 800, fontSize: 17, mt: 0.25 }}>
              No problem changed in the last {handoff.hours} hours.{handoff.older_open_cases ? ` ${handoff.older_open_cases} open ${handoff.older_open_cases === 1 ? 'case is' : 'cases are'} from earlier.` : ''}
            </Typography>
          )}
          <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap" sx={{ mt: 1.25, color: ui.muted, fontWeight: 750, fontSize: 14 }} data-testid="look-first-counts">
            {counts.map((count, index) => (
              <Box key={count.label} component="span">
                {count.to ? (
                  <Box component={RouterLink} to={count.to} sx={{ color: ui.text, textDecoration: 'none', borderBottom: `1px dashed ${ui.muted}` }}>{count.label}</Box>
                ) : count.label}
                {index < counts.length - 1 ? ' ·' : ''}
              </Box>
            ))}
          </Stack>
        </Box>
        {live ? (
          <Button component={RouterLink} to={watchHref(live)} variant="contained" sx={{ textTransform: 'none', fontWeight: 800, flexShrink: 0 }}>{openLabel(live.kind)}</Button>
        ) : null}
      </Stack>
    </WorkspacePanel>
  );
}

export function WorkList({ handoff, alertByFinding }: { handoff: ShiftHandoff; alertByFinding: Map<number, AlertItem> }) {
  const rows = handoff.watch.filter((item) => item.live);
  return (
    <WorkspacePanel sx={{ p: 0, overflow: 'hidden' }}>
      <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', sm: 'center' }} spacing={0.5} sx={{ px: 2.5, py: 2 }}>
        <Typography sx={{ fontWeight: 900, fontSize: 20 }}>Needs Attention</Typography>
        <Typography sx={{ color: ui.muted, fontSize: 13 }}>Open cases and new problems from the last {handoff.hours} hours, most important first</Typography>
      </Stack>
      <Box sx={{ overflowX: 'auto' }}>
        <Box component="table" sx={{ width: '100%', minWidth: 760, borderCollapse: 'collapse', '& th, & td': { textAlign: 'left', px: 1.5, py: 1.2, borderBottom: `1px solid ${ui.border}` }, '& th': { bgcolor: 'var(--os-surface-alt)', fontSize: 13, fontWeight: 850 } }}>
          <thead>
            <tr><th>Level</th><th>Service / Metric</th><th>What happened</th><th>Since</th><th>Status</th><th>Action</th></tr>
          </thead>
          <tbody>
            {rows.map((item, index) => <WorkRow key={`${item.kind}-${item.case_id ?? item.pattern_id ?? item.finding_id}`} item={item} first={index === 0} alert={item.kind === 'finding' && item.finding_id ? alertByFinding.get(item.finding_id) : undefined} />)}
          </tbody>
        </Box>
      </Box>
      {!rows.length ? <Typography sx={{ color: ui.muted, px: 2.5, py: 2 }}>No findings need attention in this window.</Typography> : null}
      {handoff.older_open_cases ? (
        <Typography sx={{ color: ui.muted, fontSize: 13, px: 2.5, py: 1.5 }} data-testid="older-open-cases">
          {handoff.older_open_cases} older open {handoff.older_open_cases === 1 ? 'case' : 'cases'} with no change in the last {handoff.hours} hours ·{' '}
          <Box component={RouterLink} to="/cases" sx={{ color: ui.blue, fontWeight: 800, textDecoration: 'none' }}>Show</Box>
        </Typography>
      ) : null}
    </WorkspacePanel>
  );
}

function WorkRow({ item, first, alert }: { item: HandoffWatchItem; first: boolean; alert?: AlertItem }) {
  const level = itemLevel(item.severity);
  const status = item.case_id ? `Case #${item.case_id}` : item.kind === 'pattern' ? 'Combined pattern' : 'No case';
  return (
    <Box component="tr" sx={first ? { bgcolor: 'var(--os-tint-orange)' } : undefined}>
      <td>
        <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', minHeight: 24, px: 1, borderRadius: '8px', color: level.tone.color, bgcolor: level.tone.bg, border: `1px solid ${level.tone.color}`, fontWeight: 850, fontSize: 12 }}>{level.label}</Box>
      </td>
      <td>
        <Typography sx={{ fontWeight: 850 }}>{[item.service, item.metric_name].filter(Boolean).join(' / ') || '—'}</Typography>
        {alert ? <Box sx={{ mt: 0.5 }}><AlertBadge alert={alert} /></Box> : null}
      </td>
      <td><Typography sx={{ maxWidth: 380, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={item.title}>{item.title}</Typography></td>
      <td><Typography sx={{ color: ui.muted, whiteSpace: 'nowrap' }}>{sinceText(item.since)}</Typography></td>
      <td><Typography sx={{ color: item.case_id ? ui.blue : ui.muted, fontWeight: 800, whiteSpace: 'nowrap' }}>{status}</Typography></td>
      <td>
        <Button component={RouterLink} to={watchHref(item)} sx={{ p: 0, minWidth: 0, textTransform: 'none', fontWeight: 850 }}>{item.case_id ? 'Review' : 'Watch'}</Button>
      </td>
    </Box>
  );
}

export function StatusLine({ tone, title, detail, to, linkLabel }: { tone: string; title: string; detail: string; to: string; linkLabel: string }) {
  return (
    <WorkspacePanel sx={{ px: 2.5, py: 1.4 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1.5} useFlexGap flexWrap="wrap">
        <Typography sx={{ minWidth: 0 }}>
          <Box component="span" sx={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', bgcolor: tone, mr: 1, verticalAlign: 'middle' }} />
          <Box component="span" sx={{ fontWeight: 850 }}>{title}</Box>{' '}
          <Box component="span" sx={{ color: ui.muted, fontSize: 13 }}>{detail}</Box>
        </Typography>
        <Button component={RouterLink} to={to} sx={{ textTransform: 'none', fontWeight: 800 }}>{linkLabel} →</Button>
      </Stack>
    </WorkspacePanel>
  );
}

function sinceText(value?: string | null): string {
  if (!value) return '—';
  const time = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`).getTime();
  if (!Number.isFinite(time)) return '—';
  // Rounded down, as the backend's reasons are ("open 2 hours"), so both say the same.
  const minutes = Math.max(1, Math.floor((Date.now() - time) / 60_000));
  if (minutes < 60) return `${minutes} min`;
  if (minutes < 48 * 60) return `${Math.floor(minutes / 60)} h`;
  return `${Math.floor(minutes / (24 * 60))} d`;
}
