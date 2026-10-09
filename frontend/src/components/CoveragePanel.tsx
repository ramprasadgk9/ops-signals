import React from 'react';
import { Box, Button, Chip, CircularProgress, Grid2 as Grid, Link, Stack, Tooltip, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { WorkspacePanel } from '../standalone/components';
import { formatDateTime, ui } from '../standalone/theme';
import type { CoverageReport, CoverageStatus } from '../types';

type Incident = CoverageReport['incidents'][number];

// Status job: what monitoring did about each incident. Colours from the reserved status palette
// plus a neutral, validated for colour-blind separation; grey and yellow sit below 3:1 on white,
// so every status is also named in text (tiles, legend, chips) and the incident list is the table.
export const COVERAGE_STATUSES: Record<Exclude<CoverageStatus, 'unknown'>, { label: string; color: string; hint: string }> = {
  detected: { label: 'Detected', color: '#0ca30c', hint: 'A finding that reads like it was raised while it happened' },
  flagged_other: { label: 'Flagged something else', color: 'var(--os-muted)', hint: 'Something was flagged then, but nothing like this incident' },
  missed: { label: 'Missed', color: '#d03b3b', hint: 'The service was analysed and nothing was flagged: a detection gap' },
  not_watched: { label: 'Not watched', color: '#fab219', hint: 'Nothing analysed the service then: a coverage gap' },
};
const BAR_ORDER = ['detected', 'flagged_other', 'missed', 'not_watched'] as const;
const GAPS = new Set<CoverageStatus>(['missed', 'not_watched', 'flagged_other', 'unknown']);
const WINDOWS = [
  { days: 90, label: '90 days' },
  { days: 365, label: '1 year' },
  { days: 3650, label: 'All' },
];

/** What your monitoring caught of your real past incidents, and what it missed. Built from
 * imported postmortems, so it only appears once some are imported. */
export function CoveragePanel() {
  const [days, setDays] = React.useState(365);
  const query = useQuery({ queryKey: ['monitoring-coverage', days], queryFn: () => api.monitoringCoverage(days), retry: false });
  const data = query.data;
  const [showDetected, setShowDetected] = React.useState(false);
  const gaps = data?.incidents.filter((incident) => GAPS.has(incident.status)) ?? [];
  const detected = data?.incidents.filter((incident) => incident.status === 'detected') ?? [];

  return (
    <WorkspacePanel sx={{ p: 2.5 }}>
      <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', md: 'center' }} spacing={2} sx={{ mb: 2 }}>
        <Box>
          <Typography variant="h6" sx={{ fontSize: 18, fontWeight: 900 }}>Monitoring coverage</Typography>
          <Typography sx={{ color: ui.muted, fontSize: 13 }}>
            Your imported past incidents, checked against what Ops Signals analysed and flagged while each one happened.
          </Typography>
        </Box>
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          {WINDOWS.map((window) => (
            <Chip
              key={window.days}
              label={window.label}
              onClick={() => setDays(window.days)}
              color={days === window.days ? 'primary' : 'default'}
              variant={days === window.days ? 'filled' : 'outlined'}
              sx={{ fontWeight: 800 }}
            />
          ))}
        </Stack>
      </Stack>

      {query.isLoading ? <CircularProgress size={20} /> : null}
      {query.isError ? <Typography sx={{ color: ui.muted, fontSize: 14 }}>Coverage could not be loaded.</Typography> : null}
      {data && (!data.available || !data.incidents.length) ? <Typography sx={{ color: ui.muted, fontSize: 14 }}>{data.reason}</Typography> : null}
      {data?.available && data.incidents.length ? (
        <Stack spacing={2.5}>
          <Grid container spacing={1.5} data-testid="coverage-tiles">
            {BAR_ORDER.map((status) => (
              <Grid key={status} size={{ xs: 6, md: 3 }}>
                <Tooltip describeChild title={COVERAGE_STATUSES[status].hint}>
                  <Box sx={{ p: 1.5, border: `1px solid ${ui.border}`, borderRadius: '8px' }}>
                    <Typography sx={{ fontSize: 28, fontWeight: 700, lineHeight: 1.1, color: ui.text }}>{data.counts[status] ?? 0}</Typography>
                    <Stack direction="row" spacing={0.75} alignItems="center">
                      <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: COVERAGE_STATUSES[status].color, flexShrink: 0 }} />
                      <Typography sx={{ fontSize: 13, color: ui.muted }}>{COVERAGE_STATUSES[status].label}</Typography>
                    </Stack>
                  </Box>
                </Tooltip>
              </Grid>
            ))}
          </Grid>
          {data.counts.unknown ? (
            <Typography sx={{ fontSize: 12, color: ui.muted, mt: -1.5 }}>
              {data.counts.unknown} more can't be checked: the postmortem has no service or start time.
            </Typography>
          ) : null}

          <ServiceBars services={data.services} />

          {gaps.length ? (
            <Box>
              <Typography sx={{ fontWeight: 800, mb: 1 }}>What monitoring missed</Typography>
              <Stack spacing={1}>{gaps.map((incident) => <IncidentRow key={incident.case_id} incident={incident} />)}</Stack>
            </Box>
          ) : (
            <Typography sx={{ fontSize: 14, color: ui.muted }}>Every checkable incident in this window was detected while it happened.</Typography>
          )}
          {detected.length ? (
            <Box>
              <Button size="small" onClick={() => setShowDetected(!showDetected)} sx={{ textTransform: 'none', px: 0, fontWeight: 700 }}>
                {showDetected ? 'Hide' : 'Show'} {detected.length} detected {detected.length === 1 ? 'incident' : 'incidents'}
              </Button>
              {showDetected ? <Stack spacing={1} sx={{ mt: 1 }}>{detected.map((incident) => <IncidentRow key={incident.case_id} incident={incident} />)}</Stack> : null}
            </Box>
          ) : null}
          <Typography sx={{ fontSize: 12, color: ui.muted }}>
            {data.incidents_considered} imported {data.incidents_considered === 1 ? 'incident' : 'incidents'} checked. "Detected" means a finding on the same service, raised while
            the incident happened, reads at least 60% like the postmortem's symptom; anything less is shown as flagged something else.
          </Typography>
        </Stack>
      ) : null}
    </WorkspacePanel>
  );
}

/** One stacked bar per service, length = incidents checked, segments = what monitoring did. Only
 * drawn for two or more services; a single service is already the tiles. */
function ServiceBars({ services }: { services: CoverageReport['services'] }) {
  const rows = services
    .map((row) => ({ ...row, total: BAR_ORDER.reduce((sum, status) => sum + (row.counts[status] ?? 0), 0) }))
    .filter((row) => row.total > 0);
  if (rows.length < 2) return null;
  const most = Math.max(...rows.map((row) => row.total));
  return (
    <Box data-testid="coverage-by-service">
      <Typography sx={{ fontSize: 12, color: ui.muted, mb: 0.75 }}>Incidents per service, by what monitoring did</Typography>
      <Stack spacing={0.75}>
        {rows.map((row) => (
          <Box key={row.service} sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'minmax(110px, 26%) 1fr' }, alignItems: 'center', columnGap: 1.5, rowGap: 0.25 }}>
            <Typography sx={{ fontSize: 13, color: ui.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{row.service}</Typography>
            <Stack direction="row" alignItems="center" spacing={0.75} sx={{ minWidth: 0 }}>
              <Stack direction="row" sx={{ width: `${(row.total / most) * 100}%`, minWidth: 8, gap: '2px' }}>
                {BAR_ORDER.filter((status) => row.counts[status]).map((status, index, present) => (
                  <Tooltip key={status} describeChild followCursor title={`${row.service} · ${COVERAGE_STATUSES[status].label}: ${row.counts[status]}`}>
                    <Box
                      role="img"
                      aria-label={`${row.service}: ${row.counts[status]} ${COVERAGE_STATUSES[status].label.toLowerCase()}`}
                      sx={{
                        flex: row.counts[status], height: 14, minWidth: 4, bgcolor: COVERAGE_STATUSES[status].color,
                        borderRadius: index === present.length - 1 ? '0 4px 4px 0' : 0,
                      }}
                    />
                  </Tooltip>
                ))}
              </Stack>
              <Typography sx={{ fontSize: 13, fontWeight: 700, color: ui.text, flexShrink: 0 }}>{row.total}</Typography>
            </Stack>
          </Box>
        ))}
      </Stack>
      <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap sx={{ mt: 0.75 }}>
        {BAR_ORDER.map((status) => (
          <Stack key={status} direction="row" spacing={0.5} alignItems="center">
            <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: COVERAGE_STATUSES[status].color }} />
            <Typography sx={{ fontSize: 12, color: ui.muted }}>{COVERAGE_STATUSES[status].label}</Typography>
          </Stack>
        ))}
      </Stack>
    </Box>
  );
}

function IncidentRow({ incident }: { incident: Incident }) {
  const status = incident.status === 'unknown' ? null : COVERAGE_STATUSES[incident.status];
  return (
    <Box sx={{ p: 1.5, border: `1px solid ${ui.border}`, borderRadius: '8px' }} data-testid="coverage-incident">
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
        <Chip
          size="small"
          variant="outlined"
          label={incident.label}
          icon={status ? <Box component="span" sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: status.color, ml: '8px !important' }} /> : undefined}
          sx={{ fontWeight: 700 }}
        />
        <Link component={RouterLink} to={`/cases/${incident.case_id}`} underline="hover" sx={{ fontWeight: 800, color: ui.text }}>{incident.title}</Link>
      </Stack>
      <Typography sx={{ fontSize: 12, color: ui.muted, mt: 0.25 }}>
        {[incident.service, incident.started_at ? formatDateTime(incident.started_at) : null].filter(Boolean).join(' · ')}
      </Typography>
      <Typography sx={{ fontSize: 13, mt: 0.75 }}>{incident.explanation}</Typography>
      {incident.evidence.length && incident.status !== 'detected' ? (
        <Typography sx={{ fontSize: 13, color: ui.muted, mt: 0.25 }}>
          Flagged then: {incident.evidence.map((item) => `${item.title} (${Math.round(item.similarity * 100)}%)`).join('; ')}
        </Typography>
      ) : null}
      {incident.seen_elsewhere_case_id ? (
        <Typography sx={{ fontSize: 13, mt: 0.25 }}>
          <Link component={RouterLink} to={`/cases/${incident.seen_elsewhere_case_id}`} underline="hover">Open the latest detected case like it</Link>
        </Typography>
      ) : null}
    </Box>
  );
}
