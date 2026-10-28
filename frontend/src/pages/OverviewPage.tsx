import { Box, Button, Grid2 as Grid, Stack, Typography } from '@mui/material';
import ShowChartRoundedIcon from '@mui/icons-material/ShowChartRounded';
import { Link as RouterLink } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { GetDataInPanel, SourceStatusStrip } from '../components/GetDataInPanel';
import { AlertBadge, alertsByFinding } from '../components/AlertComponents';
import { MetricUsageStrip } from '../components/MetricUsageStrip';
import { SetupBanner } from '../components/SetupBanner';
import { ShiftHandoffButton } from '../components/ShiftHandoffButton';
import { LookFirstPanel, StatusLine, WorkList, type FocusCount } from '../components/OverviewFocus';
import { PageHeader, IconTile, WorkspacePanel } from '../standalone/components';
import { relativeTime, severityTone, titleCase, ui } from '../standalone/theme';
import { findingLevel } from '../utils/findingLevel';
import { groupRepeatedFindings } from '../utils/findingSearch';
import { needsAttention } from '../utils/findingTrust';
import { inWindow, patternParts } from '../utils/combinedPatterns';
import { buildAutonomousDashboardData, type AutonomousPolicyRun } from '../autonomous/dashboardModel';
import type { AlertItem, BehaviorFinding, Finding, OperationalCase } from '../types';

// The tiles are a glance: the same numbers lead the Look at this first block, each one a link.
function KpiCard({ value, label, delta, to, color }: { value: number | string; label: string; delta?: string; to: string; color: string }) {
  return (
    <WorkspacePanel sx={{ px: 2, py: 1.5 }}>
      <Button component={RouterLink} to={to} sx={{ display: 'block', p: 0, width: '100%', textAlign: 'left', textTransform: 'none', color: 'inherit' }}>
        <Typography sx={{ fontSize: 22, fontWeight: 900, lineHeight: 1.1, color }}>{value}</Typography>
        <Typography sx={{ color: 'var(--os-text-2)', fontWeight: 750, fontSize: 14 }}>{label}</Typography>
        {delta ? <Typography sx={{ color: ui.muted, fontSize: 12, fontWeight: 750 }}>{delta}</Typography> : null}
      </Button>
    </WorkspacePanel>
  );
}

const DAY_MS = 24 * 3600_000;

export function OverviewPage() {
  const findingsQuery = useQuery({ queryKey: ['findings-overview', '24h'], queryFn: () => api.findings(undefined, undefined, undefined, '24h') });
  const casesQuery = useQuery({ queryKey: ['cases-overview'], queryFn: () => api.cases(200) });
  const behaviorsQuery = useQuery({ queryKey: ['behavior-findings-overview'], queryFn: () => api.behaviorFindings() });
  const summaryQuery = useQuery({ queryKey: ['overview-summary', '24h'], queryFn: () => api.overviewSummary('24h') });
  const autonomousPolicyRunsQuery = useQuery({ queryKey: ['overview-autonomous-policy-runs'], queryFn: () => api.autonomousPolicyRuns(10), retry: false });
  // What to look at first and the work list, in the shift handoff's order. If this read fails the
  // page falls back to the summary sentence and the findings table it had before.
  const handoffQuery = useQuery({ queryKey: ['overview-handoff', 24, 8], queryFn: () => api.shiftHandoff(24, 8), retry: false, refetchInterval: 60_000 });
  // Deliberately outside the loading gate below: if this read is slow or fails, the Overview
  // renders exactly as it would without it.
  const ingestionStatusQuery = useQuery({ queryKey: ['ingestion-status'], queryFn: () => api.ingestionStatus(), retry: false, refetchInterval: 15_000 });
  // Same rule: alerts only add badges and a status line; without them (or if this fails) rows render as before.
  const linkedAlertsQuery = useQuery({ queryKey: ['alerts', 'recent', 100], queryFn: () => api.alerts({ limit: 100 }), retry: false, refetchInterval: 30_000 });

  const ingestionStatus = ingestionStatusQuery.data;
  const awaitingFirstData = ingestionStatus?.has_any_data === false;
  // Once shown, the panel stays for this visit (until dismissed) even after the first data lands,
  // so the result of an action taken in it - a demo run, a test alert - stays on screen.
  const [onboardingOpen, setOnboardingOpen] = useState(false);
  useEffect(() => {
    if (awaitingFirstData) setOnboardingOpen(true);
  }, [awaitingFirstData]);

  if (findingsQuery.isLoading || casesQuery.isLoading || behaviorsQuery.isLoading || summaryQuery.isLoading || autonomousPolicyRunsQuery.isLoading || handoffQuery.isLoading) return <LoadingSkeleton />;

  const findings = findingsQuery.data ?? [];
  const cases = casesQuery.data ?? [];
  const behaviors = behaviorsQuery.data ?? [];
  const summary = summaryQuery.data;
  const policyRuns = autonomousPolicyRunsQuery.data ?? [];
  const handoff = handoffQuery.data;
  const alerts = linkedAlertsQuery.data ?? [];
  // One row per problem: a problem every run sees again is listed once, at its most important.
  const prioritizedFindings = groupRepeatedFindings([...findings].sort((a, b) => (b.importance_score ?? 0) - (a.importance_score ?? 0)))
    .map((group) => group.finding)
    // Context findings stay on the Findings page, as there.
    .filter(needsAttention);
  const autonomousData = buildAutonomousDashboardData({
    findings,
    cases,
    analysisRuns: [],
    behaviorFindings: behaviors,
    policyRuns,
    findingHref: () => '/findings?window=24h',
    caseHref: (caseItem) => `/cases/${caseItem.id}`,
  });
  const latestAutonomousRun = latestPolicyRun(policyRuns);
  const failedJobs = latestAutonomousRun?.jobs_failed ?? autonomousData.summary.failed ?? 0;
  const topFinding = prioritizedFindings[0];
  const topIssue = topFinding ? `${topFinding.service} / ${topFinding.metric_name}` : 'No active top issue';
  const kpiValue = (value: number | undefined) => (summaryQuery.error ? 'Unavailable' : awaitingFirstData ? '—' : value ?? 0);
  const attention = summary?.attention_findings ?? summary?.active_findings;
  const focusCounts: FocusCount[] = summaryQuery.error || !summary
    ? [{ label: 'Counts unavailable' }]
    : [
        { label: plural(attention ?? 0, summary.attention_findings !== undefined ? 'finding needs attention' : 'active finding', summary.attention_findings !== undefined ? 'findings need attention' : 'active findings'), to: '/findings?window=24h' },
        { label: plural(summary.open_cases, 'open case'), to: '/cases' },
        { label: plural(summary.impacted_services, 'service affected', 'services affected'), to: '/findings?window=24h' },
        { label: failedJobs > 0 ? plural(failedJobs, 'failed job') : 'automation healthy', to: '/autonomous-monitoring' },
      ];
  const recentAlerts = alerts.filter((alert) => Date.now() - new Date(alert.received_at).getTime() <= DAY_MS);
  const firingAlerts = recentAlerts.filter((alert) => alert.status === 'firing').length;
  const completedAt = latestAutonomousRun?.completed_at ?? latestAutonomousRun?.updated_at ?? latestAutonomousRun?.started_at ?? null;

  return (
    <Stack spacing={2}>
      <PageHeader
        title="Overview"
        subtitle="What needs you now"
        action={
          <Stack direction="row" spacing={1.5} alignItems="center" useFlexGap flexWrap="wrap">
            {ingestionStatus ? <SourceStatusStrip status={ingestionStatus} /> : null}
            {awaitingFirstData ? null : <ShiftHandoffButton />}
          </Stack>
        }
      />

      <SetupBanner />

      {(awaitingFirstData || onboardingOpen) && ingestionStatus ? (
        <GetDataInPanel status={ingestionStatus} onDismiss={awaitingFirstData ? undefined : () => setOnboardingOpen(false)} />
      ) : null}

      {handoff && !awaitingFirstData ? (
        <LookFirstPanel handoff={handoff} counts={focusCounts} />
      ) : (
        <OperationalSummary
          activeFindings={summaryQuery.error ? null : summary?.active_findings ?? findings.length}
          attentionFindings={summaryQuery.error ? undefined : summary?.attention_findings}
          contextFindings={summary?.context_findings}
          impactedServices={summaryQuery.error ? null : summary?.impacted_services ?? 0}
          failedJobs={failedJobs}
          topIssue={topIssue}
          awaitingFirstData={awaitingFirstData}
        />
      )}

      {handoff ? (
        <WorkList handoff={handoff} alertByFinding={alertsByFinding(alerts)} />
      ) : (
        <NeedsAttentionPanel findings={prioritizedFindings} patterns={behaviors.filter((behavior) => inWindow(behavior, '24h'))} cases={cases} alertByFinding={alertsByFinding(alerts)} />
      )}

      <Grid container spacing={1.5}>
        <Grid size={{ xs: 6, lg: 3 }}>{summary?.attention_findings !== undefined ? (
          // Problems that need attention; context findings are one click away, as on the Findings page.
          <KpiCard value={kpiValue(summary.attention_findings)} label="Need Attention" delta={summary.context_findings ? `+${summary.context_findings} in context` : undefined} to="/findings?window=24h" color={ui.red} />
        ) : (
          <KpiCard value={kpiValue(summary?.active_findings)} label="Active Findings" to="/findings?window=24h" color={ui.red} />
        )}</Grid>
        <Grid size={{ xs: 6, lg: 3 }}><KpiCard value={kpiValue(summary?.open_cases)} label="Open Cases" to="/cases" color={ui.orange} /></Grid>
        <Grid size={{ xs: 6, lg: 3 }}><KpiCard value={kpiValue(summary?.impacted_services)} label="Impacted Services" to="/findings?window=24h" color="#3b82f6" /></Grid>
        <Grid size={{ xs: 6, lg: 3 }}><KpiCard value={awaitingFirstData ? '—' : failedJobs > 0 ? 'Needs attention' : 'Healthy'} label="Automation" to="/autonomous-monitoring" color={failedJobs > 0 ? ui.red : ui.green} /></Grid>
      </Grid>

      <MetricUsageStrip />

      <StatusLine
        tone={autonomousPolicyRunsQuery.error ? ui.muted : failedJobs > 0 ? ui.red : latestAutonomousRun ? ui.green : ui.muted}
        title="Autonomous Analysis"
        detail={
          autonomousPolicyRunsQuery.error
            ? 'run status unavailable'
            : latestAutonomousRun
              ? `last run ${latestAutonomousRun.status} ${relativeTime(completedAt)} · ${plural(latestAutonomousRun.findings_created ?? autonomousData.summary.findingsGenerated, 'finding')} · ${plural(failedJobs, 'failed job')}`
              : 'no runs yet'
        }
        to="/autonomous-monitoring"
        linkLabel="Details"
      />
      <StatusLine
        tone={firingAlerts > 0 ? ui.red : ui.muted}
        title="Alerts"
        detail={
          linkedAlertsQuery.error
            ? 'unavailable'
            : recentAlerts.length
              ? `${plural(recentAlerts.length, 'alert')} in the last 24 hours${firingAlerts ? `, ${firingAlerts} still firing` : ''}`
              : 'none in the last 24 hours'
        }
        to="/alerts"
        linkLabel="Alerts"
      />
    </Stack>
  );
}

function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}

function latestPolicyRun(policyRuns: AutonomousPolicyRun[]) {
  return [...policyRuns].sort((a, b) => {
    const aTime = new Date(a.completed_at ?? a.started_at ?? a.created_at ?? 0).getTime();
    const bTime = new Date(b.completed_at ?? b.started_at ?? b.created_at ?? 0).getTime();
    return bTime - aTime;
  })[0] ?? null;
}

// Without the handoff (its read failed): the summary sentence and findings table the page had before.
function OperationalSummary({ activeFindings, attentionFindings, contextFindings, impactedServices, failedJobs, topIssue, awaitingFirstData = false }: { activeFindings: number | null; attentionFindings?: number; contextFindings?: number; impactedServices: number | null; failedJobs: number; topIssue: string; awaitingFirstData?: boolean }) {
  const findingText =
    activeFindings === null
      ? 'Findings unavailable.'
      : attentionFindings !== undefined
        ? `${attentionFindings} ${attentionFindings === 1 ? 'finding needs' : 'findings need'} attention${contextFindings ? `, ${contextFindings} more in context` : ''}.`
        : `${activeFindings} active ${activeFindings === 1 ? 'finding' : 'findings'}.`;
  const serviceText = impactedServices === null ? 'Service impact unavailable.' : `${impactedServices} ${impactedServices === 1 ? 'service' : 'services'} impacted.`;
  const automationText = failedJobs > 0 ? `Automation needs attention with ${failedJobs} failed ${failedJobs === 1 ? 'job' : 'jobs'}.` : 'Automation healthy.';
  return (
    <WorkspacePanel sx={{ p: 2.5 }}>
      <Stack direction={{ xs: 'column', md: 'row' }} alignItems={{ xs: 'flex-start', md: 'center' }} spacing={2}>
        <IconTile bg="var(--os-tint-blue)" color={ui.blue}><ShowChartRoundedIcon /></IconTile>
        <Box>
          <Typography sx={{ fontWeight: 900, fontSize: 20 }}>Operational Summary</Typography>
          <Typography sx={{ color: ui.text, mt: 0.8, fontSize: 16 }}>
            {awaitingFirstData ? 'Waiting for the first metrics or alerts. Connect a source above to start analysis.' : `${findingText} ${serviceText} ${automationText} Top issue: ${topIssue}.`}
          </Typography>
        </Box>
      </Stack>
    </WorkspacePanel>
  );
}

function NeedsAttentionPanel({ findings, patterns, cases, alertByFinding }: { findings: Finding[]; patterns: BehaviorFinding[]; cases: OperationalCase[]; alertByFinding: Map<number, AlertItem> }) {
  // Combined patterns lead: several metrics agreeing is stronger evidence than any one of them.
  const patternRows = patterns.slice(0, 5);
  const rows = findings.slice(0, 5 - patternRows.length);
  return (
    <WorkspacePanel sx={{ p: 2.5 }}>
      <Typography sx={{ fontWeight: 900, fontSize: 20, mb: 2 }}>Needs Attention</Typography>
      <Box sx={{ overflowX: 'auto' }}>
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '90px 220px 150px 210px 120px 110px', lg: '0.7fr 1.8fr 1fr 1.5fr 1fr 0.8fr' },
            minWidth: 840,
            border: `1px solid ${ui.border}`,
            borderRadius: '8px',
            overflow: 'hidden',
          }}
        >
          {['Priority', 'Service / Metric', 'Issue', 'Impact', 'Status', 'Action'].map((header) => (
            <Typography key={header} sx={{ px: 1.5, py: 1.2, bgcolor: 'var(--os-surface-alt)', borderBottom: `1px solid ${ui.border}`, fontWeight: 850, fontSize: 13 }}>
              {header}
            </Typography>
          ))}
          {patternRows.map((behavior) => {
            const tone = severityTone(behavior.severity);
            return (
              <NeedsAttentionRow
                key={`pattern-${behavior.id}`}
                priority={titleCase(behavior.severity)}
                priorityColor={tone.color}
                priorityBg={tone.bg}
                serviceMetric={`${behavior.service ?? 'unknown'} / ${patternParts(behavior).length} metrics`}
                issue="Combined pattern"
                impact={behavior.title}
                status={behavior.case_id ? `Case #${behavior.case_id}` : 'No case'}
                action={behavior.case_id ? 'Review' : 'Watch'}
                to={behavior.case_id ? `/cases/${behavior.case_id}` : '/findings?window=24h'}
              />
            );
          })}
          {rows.map((finding, index) => {
            // Matching on finding_id only: a case is only ever created by explicitly promoting
            // one specific finding (backend/app/api/cases.py), so finding_id is the sole reliable
            // link. A prior fallback matched on metric_name alone, which mislabeled every
            // un-cased finding as belonging to any other case that happened to share a metric
            // name - even from a completely unrelated service.
            const matchingCase = cases.find((caseItem) => caseItem.finding_id === finding.id);
            const level = findingLevel(finding.health_status);
            const status = matchingCase ? `Case #${matchingCase.id}` : 'No case';
            return (
              <NeedsAttentionRow
                key={`${finding.id ?? finding.metric_name}-${index}`}
                priority={level.label}
                priorityColor={level.tone.color}
                priorityBg={level.tone.bg}
                serviceMetric={`${finding.service ?? 'unknown'} / ${finding.metric_name}`}
                issue={titleCase(finding.category)}
                impact={finding.title}
                status={status}
                action={matchingCase ? 'Review' : 'Watch'}
                to={matchingCase ? `/cases/${matchingCase.id}` : '/findings?window=24h'}
                alert={finding.id !== undefined && finding.id !== null ? alertByFinding.get(finding.id) : undefined}
              />
            );
          })}
        </Box>
      </Box>
      {rows.length + patternRows.length === 0 ? <Typography sx={{ color: ui.muted, mt: 2 }}>No findings need attention in this window.</Typography> : null}
    </WorkspacePanel>
  );
}

function NeedsAttentionRow({ priority, priorityColor, priorityBg, serviceMetric, issue, impact, status, action, to, alert }: { priority: string; priorityColor: string; priorityBg: string; serviceMetric: string; issue: string; impact: string; status: string; action: string; to: string; alert?: AlertItem }) {
  const cellSx = { px: 1.5, py: 1.25, borderBottom: `1px solid ${ui.border}`, minWidth: 0 };
  return (
    <>
      <Box sx={cellSx}>
        <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', minHeight: 24, px: 1, borderRadius: '8px', color: priorityColor, bgcolor: priorityBg, border: `1px solid ${priorityColor}`, fontWeight: 850, fontSize: 12 }}>
          {priority}
        </Box>
      </Box>
      <Box sx={cellSx}>
        <Typography sx={{ fontWeight: 850, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{serviceMetric}</Typography>
        {alert ? <Box sx={{ mt: 0.5 }}><AlertBadge alert={alert} /></Box> : null}
      </Box>
      <Typography sx={cellSx}>{issue}</Typography>
      <Typography sx={{ ...cellSx, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{impact}</Typography>
      <Typography sx={{ ...cellSx, color: status.startsWith('Case') ? ui.blue : ui.muted, fontWeight: 800 }}>{status}</Typography>
      <Button component={RouterLink} to={to} sx={{ ...cellSx, justifyContent: 'flex-start', textTransform: 'none', fontWeight: 850 }}>{action}</Button>
    </>
  );
}
