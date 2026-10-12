import type { ReactNode } from 'react';
import { Box, Button, Chip, Stack, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import { sourceList, useFeatureAvailability } from '../hooks/useFeatureAvailability';
import { WorkspacePanel } from '../standalone/components';
import { ui } from '../standalone/theme';
import { setNavFeatureHidden, useHiddenNavFeatures } from '../utils/hiddenNavFeatures';
import type { FeatureAvailability } from '../types';

type FeatureCopy = { title: string; body: string; points: string[] };

/** What each source-dependent feature does, said where the user meets it. */
const COPY: Record<string, FeatureCopy> = {
  autonomous_analysis: {
    title: 'Watch your services without being asked',
    body: 'Autonomous analysis picks the metrics worth watching and analyzes them on a schedule. It finds and pulls them with PromQL, so it needs a Prometheus-compatible source.',
    points: ['Choose a scope and policy, run once or on a schedule', 'Findings from every run land in Findings and Cases', 'Drill-down shows which pods a change came from'],
  },
  metric_usage: {
    title: 'Find blind spots and metrics nobody uses',
    body: 'Metric Usage compares the series you store with the dashboards and alert rules that read them. It reads series and rules from a Prometheus-compatible source, and dashboards from Grafana.',
    points: ['Metrics with recent problems that no dashboard or alert watches', 'Dashboards reading metrics that no longer exist', 'Stored series nothing uses, optionally as a monthly cost'],
  },
  alert_enrichment: {
    title: 'Get what changed with every alert',
    body: 'Alert enrichment takes each alert from Alertmanager, re-runs its query to see what changed, checks recent deploys and past cases, and posts one Slack message.',
    points: ['What happened and what changed just before it', 'Whether it has been seen before, and how it was fixed', 'Resolve follow-ups when the alert clears'],
  },
};

/** Shown in place of a feature its sources can't run yet: what it does, what it needs, where to
 * connect it. Renders `children` untouched whenever the feature is available or availability is
 * unknown. With `keepContent` (the page has history worth showing) both are shown. */
export function FeatureNeedsSource({ feature: featureId, keepContent = false, children }: { feature: string; keepContent?: boolean; children: ReactNode }) {
  const { feature } = useFeatureAvailability();
  const availability = feature(featureId);
  if (availability?.state !== 'off') return <>{children}</>;
  return (
    <>
      <NeedsSourcePanel availability={availability} compact={keepContent} />
      {keepContent ? children : null}
    </>
  );
}

function NeedsSourcePanel({ availability, compact }: { availability: FeatureAvailability; compact: boolean }) {
  const hidden = useHiddenNavFeatures().includes(availability.id);
  const copy = COPY[availability.id];
  const needs = sourceList(availability.missing);
  return (
    <WorkspacePanel sx={{ p: compact ? 2.5 : { xs: 2.5, md: 4 } }}>
      <Stack spacing={compact ? 1.2 : 2} data-testid="feature-needs-source" sx={{ maxWidth: 720 }}>
        <Chip
          label={`Needs ${needs}`}
          size="small"
          sx={{ alignSelf: 'flex-start', bgcolor: 'var(--os-tint-amber)', color: 'var(--os-ink-amber)', fontWeight: 750 }}
        />
        {copy && !compact ? (
          <Typography component="h2" sx={{ fontSize: 22, fontWeight: 800 }}>
            {copy.title}
          </Typography>
        ) : null}
        <Typography sx={{ fontSize: 15, lineHeight: 1.6, color: 'var(--os-text-2)' }}>
          {compact
            ? `${availability.label} is off until you connect ${needs}. What it found before is below.`
            : copy?.body ?? `${availability.label} needs ${needs}.`}
        </Typography>
        {copy && !compact ? (
          <Box component="ul" sx={{ m: 0, pl: 2.5, color: 'var(--os-text-2)', fontSize: 14, lineHeight: 1.9 }}>
            {copy.points.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </Box>
        ) : null}
        <Stack direction="row" spacing={1.5} useFlexGap flexWrap="wrap" alignItems="center">
          <Button component={RouterLink} to="/integrations" variant="contained" sx={{ textTransform: 'none', fontWeight: 800 }}>
            Connect on Integrations
          </Button>
          <Button onClick={() => setNavFeatureHidden(availability.id, !hidden)} sx={{ textTransform: 'none', fontWeight: 700, color: ui.muted }}>
            {hidden ? 'Show in menu' : 'Hide from menu'}
          </Button>
        </Stack>
      </Stack>
    </WorkspacePanel>
  );
}
