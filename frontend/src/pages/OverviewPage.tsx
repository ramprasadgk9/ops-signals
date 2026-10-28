import { Box, Button, Collapse, Grid2 as Grid, Stack, Typography } from '@mui/material';
import WarningAmberRoundedIcon from '@mui/icons-material/WarningAmberRounded';
import WorkOutlineRoundedIcon from '@mui/icons-material/WorkOutlineRounded';
import DnsRoundedIcon from '@mui/icons-material/DnsRounded';
import ShowChartRoundedIcon from '@mui/icons-material/ShowChartRounded';
import AutoModeRoundedIcon from '@mui/icons-material/AutoModeRounded';
import KeyboardArrowDownRoundedIcon from '@mui/icons-material/KeyboardArrowDownRounded';
import KeyboardArrowUpRoundedIcon from '@mui/icons-material/KeyboardArrowUpRounded';
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded';
import { Link as RouterLink } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { GetDataInPanel, SourceStatusStrip } from '../components/GetDataInPanel';
import { AlertBadge, alertsByFinding } from '../components/AlertComponents';
import { AlertsOverviewPanel } from '../components/AlertTimeline';
import { MetricUsageStrip } from '../components/MetricUsageStrip';
import { SetupBanner } from '../components/SetupBanner';
import { ShiftHandoffCard } from '../components/ShiftHandoffCard';
import { PageHeader, IconTile, Pill, WorkspacePanel } from '../standalone/components';
import { relativeTime, severityTone, titleCase, ui } from '../standalone/theme';
import { findingLevel } from '../utils/findingLevel';
import { groupRepeatedFindings } from '../utils/findingSearch';
import { needsAttention } from '../utils/findingTrust';
import { inWindow, patternParts } from '../utils/combinedPatterns';
import { toCaseRows } from '../standalone/casesService';
import { buildAutonomousDashboardData, type AutonomousDashboardData, type AutonomousPolicyRun } from '../autonomous/dashboardModel';
import type { AlertItem, BehaviorFinding, Finding, OperationalCase } from '../types';

function KpiCard({ icon, value, label, delta, to, bg, color }: { icon: React.ReactNode; value: number | string; label: string; delta: string; to: string; bg: string; color: string }) {
  return (
    <WorkspacePanel sx={{ p: 2.5 }}>
      <Button component={RouterLink} to={to} sx={{ display: 'flex', justifyContent: 'flex-start', gap: 2, p: 0, width: '100%', textTransform: 'none', color: 'inherit' }}>
        <IconTile bg={bg} color={color}>{icon}</IconTile>
        <Box sx={{ textAlign: 'left' }}>
          <Typography sx={{ fontSize: 28, fontWeight: 900, lineHeight: 1 }}>{value}</Typography>
          <Typography sx={{ color: 'var(--os-text-2)', fontWeight: 750 }}>{label}</Typography>
          <Typography sx={{ mt: 1.4, color, fontSize: 13, fontWeight: 800 }}>{delta}</Typography>
        </Box>
      </Button>
    </WorkspacePanel>
  );
}

export function OverviewPage() {
  const [autonomousDetailsOpen, setAutonomousDetailsOpen] = useState(false);
  const findingsQuery = useQuery({ queryKey: ['findings-overview', '24h'], queryFn: () => api.findings(undefined, undefined, undefined, '24h') });
  const casesQuery = useQuery({ queryKey: ['cases-overview'], queryFn: () => api.cases(200) });
  const behaviorsQuery = useQuery({ queryKey: ['behavior-findings-overview'], queryFn: () => api.behaviorFindings() });
  const summaryQuery = useQuery({ queryKey: ['overview-summary', '24h'], queryFn: () => api.overviewSummary('24h') });
  const autonomousPolicyRunsQuery = useQuery({ queryKey: ['overview-autonomous-policy-runs'], queryFn: () => api.autonomousPolicyRuns(10), retry: false });
  // Deliberately outside the loading gate below: if this read is slow or fails, the Overview
  // renders exactly as it would without it.
  const ingestionStatusQuery = useQuery({ queryKey: ['ingestion-status'], queryFn: () => api.ingestionStatus(), retry: false, refetchInterval: 15_000 });
  // Same rule: alerts only add badges; without them (or if this fails) rows render as before.
  const linkedAlertsQuery = useQuery({ queryKey: ['alerts', 'recent', 100], queryFn: () => api.alerts({ limit: 100 }), retry: false, refetchInterval: 30_000 });

  const ingestionStatus = ingestionStatusQuery.data;
  const awaitingFirstData = ingestionStatus?.has_any_data === false;
  // Once shown, the panel stays for this visit (until dismissed) even after the first data lands,
  // so the result of an action taken in it - a demo run, a test alert - stays on screen.
  const [onboardingOpen, setOnboardingOpen] = useState(false);
  useEffect(() => {
    if (awaitingFirstData) setOnboardingOpen(true);
  }, [awaitingFirstData]);

  if (findingsQuery.isLoading || casesQuery.isLoading || behaviorsQuery.isLoading || summaryQuery.isLoading || autonomousPolicyRunsQuery.isLoading) return <LoadingSkeleton />;

  const findings = findingsQuery.data ?? [];
  const cases = casesQuery.data ?? [];
  const behaviors = behaviorsQuery.data ?? [];
  const summary = summaryQuery.data;
  const policyRuns = autonomousPolicyRunsQuery.data ?? [];
  const caseRows = toCaseRows(cases);
  const openCases = caseRows.filter((item) => item.isOpen);
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

  return (
    <Stack spacing={3}>
      <PageHeader title="Overview" subtitle="Operational intelligence at a glance" action={ingestionStatus ? <SourceStatusStrip status={ingestionStatus} /> : undefined} />

      <SetupBanner />

      {(awaitingFirstData || onboardingOpen) && ingestionStatus ? (
        <GetDataInPanel status={ingestionStatus} onDismiss={awaitingFirstData ? undefined : () => setOnboardingOpen(false)} />
      ) : null}

      {awaitingFirstData ? null : <ShiftHandoffCard />}

      <OperationalSummary
        activeFindings={summaryQuery.error ? null : summary?.active_findings ?? findings.length}
        attentionFindings={summaryQuery.error ? undefined : summary?.attention_findings}
        contextFindings={summary?.context_findings}
        impactedServices={summaryQuery.error ? null : summary?.impacted_services ?? 0}
        failedJobs={failedJobs}
        topIssue={topIssue}
        awaitingFirstData={awaitingFirstData}
      />

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>{summary?.attention_findings !== undefined ? (
          // Problems that need attention; context findings are one click away, as on the Findings page.
          <KpiCard icon={<WarningAmberRoundedIcon />} value={kpiValue(summary.attention_findings)} label="Need Attention" delta={summary.context_findings ? `+${summary.context_findings} in context` : 'Needs review'} to="/findings?window=24h" bg="var(--os-tint-rose)" color={ui.red} />
        ) : (
          <KpiCard icon={<WarningAmberRoundedIcon />} value={kpiValue(summary?.active_findings)} label="Active Findings" delta="Needs review" to="/findings?window=24h" bg="var(--os-tint-rose)" color={ui.red} />
        )}</Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}><KpiCard icon={<WorkOutlineRoundedIcon />} value={kpiValue(summary?.open_cases)} label="Open Cases" delta="Investigation backlog" to="/cases" bg="var(--os-tint-orange)" color={ui.orange} /></Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}><KpiCard icon={<DnsRoundedIcon />} value={kpiValue(summary?.impacted_services)} label="Impacted Services" delta={topFinding?.service ?? 'No service impacted'} to="/findings?window=24h" bg="var(--os-tint-blue)" color="#3b82f6" /></Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}><KpiCard icon={<CheckCircleRoundedIcon />} value={awaitingFirstData ? '—' : failedJobs > 0 ? 'Needs attention' : 'Healthy'} label="Automation" delta={awaitingFirstData ? 'Waiting for first data' : `${failedJobs} failed jobs`} to="/autonomous-monitoring" bg="var(--os-tint-green)" color={failedJobs > 0 ? ui.red : ui.green} /></Grid>
      </Grid>

      <MetricUsageStrip />

      <NeedsAttentionPanel findings={prioritizedFindings} patterns={behaviors.filter((behavior) => inWindow(behavior, '24h'))} cases={cases} alertByFinding={alertsByFinding(linkedAlertsQuery.data ?? [])} />

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 7 }}>
          <AutonomousSummaryPanel data={autonomousData} latestRun={latestAutonomousRun} error={Boolean(autonomousPolicyRunsQuery.error)} detailsOpen={autonomousDetailsOpen} onToggleDetails={() => setAutonomousDetailsOpen((open) => !open)} />
        </Grid>
        <Grid size={{ xs: 12, lg: 5 }}>
          <OpenInvestigationsPanel openCases={openCases} />
        </Grid>
      </Grid>

      <AlertsOverviewPanel title="Incoming Alerts" variant="compact" hideWhenEmpty viewAllTo="/alerts" />
    </Stack>
  );
}

function latestPolicyRun(policyRuns: AutonomousPolicyRun[]) {
  return [...policyRuns].sort((a, b) => {
    const aTime = new Date(a.completed_at ?? a.started_at ?? a.created_at ?? 0).getTime();
    const bTime = new Date(b.completed_at ?? b.started_at ?? b.created_at ?? 0).getTime();
    return bTime - aTime;
  })[0] ?? null;
}

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

function AutonomousSummaryPanel({ data, latestRun, error, detailsOpen, onToggleDetails }: { data: AutonomousDashboardData; latestRun: AutonomousPolicyRun | null; error: boolean; detailsOpen: boolean; onToggleDetails: () => void }) {
  const topFinding = data.topFindings[0];
  const completedAt = latestRun?.completed_at ?? latestRun?.updated_at ?? latestRun?.started_at ?? null;
  const findingsByRun = buildFindingsByObserved(data.topFindings);
  const priorityBreakdown = buildPriorityBreakdown(data.topFindings);
  return (
    <WorkspacePanel sx={{ p: 0, overflow: 'hidden' }}>
      <Stack direction={{ xs: 'column', md: 'row' }} alignItems={{ xs: 'stretch', md: 'center' }} justifyContent="space-between" spacing={1.5} sx={{ px: 2.5, py: 1.8, borderBottom: `1px solid ${ui.border}` }}>
        <Stack direction="row" alignItems="center" spacing={1.4}>
          <IconTile bg="var(--os-tint-blue)" color={ui.blue}><AutoModeRoundedIcon /></IconTile>
          <Box>
            <Typography sx={{ fontWeight: 900, fontSize: 18 }}>Autonomous Analysis</Typography>
            <Typography sx={{ color: ui.muted, fontSize: 13 }}>
              {error ? 'Autonomous run status unavailable.' : latestRun ? `Last run ${latestRun.status} • ${relativeTime(completedAt)}` : 'No autonomous runs completed yet.'}
            </Typography>
          </Box>
        </Stack>
        <Stack direction="row" spacing={1}>
          <Button onClick={onToggleDetails} endIcon={detailsOpen ? <KeyboardArrowUpRoundedIcon /> : <KeyboardArrowDownRoundedIcon />} variant="outlined" sx={{ textTransform: 'none', fontWeight: 800 }}>
            {detailsOpen ? 'Hide details' : 'View details'}
          </Button>
        </Stack>
      </Stack>
      <Box sx={{ px: 2.5, py: 2 }}>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr 1fr', lg: 'repeat(4, 1fr)' }, gap: 1.5 }}>
          <AutonomousStatusTile label="Last Run" value={latestRun?.status ?? 'Unavailable'} detail={latestRun ? relativeTime(completedAt) : 'No run yet'} tone={latestRun?.status === 'completed' ? ui.green : ui.orange} />
          <AutonomousStatusTile label="Findings" value={data.summary.findingsGenerated} detail="Generated" tone={ui.orange} />
          <AutonomousStatusTile label="Failed Jobs" value={data.summary.failed ?? 0} detail="Execution errors" tone={(data.summary.failed ?? 0) > 0 ? ui.red : ui.green} />
          <AutonomousStatusTile label="Top Metric" value={topFinding?.metric ?? 'None'} detail={topFinding?.service ?? 'No service'} tone={ui.blue} />
        </Box>
      </Box>
      <Collapse in={detailsOpen} unmountOnExit>
        <Box sx={{ borderTop: `1px solid ${ui.border}`, px: 2.5, py: 2.5 }}>
          <Typography sx={{ fontWeight: 900, fontSize: 18, mb: 0.5 }}>Autonomous Analysis Details</Typography>
          <Typography sx={{ color: ui.muted, mb: 2 }}>Run health, finding trend, priority mix, and the investigation queue for this overview window.</Typography>
          <Grid container spacing={2}>
            <Grid size={{ xs: 12, lg: 6 }}>
              <DetailPanel title="Findings by Run">
                {findingsByRun.some((item) => item.value > 0) ? (
                  <MiniBarChart items={findingsByRun} />
                ) : (
                  <Typography color="text.secondary">No finding trend points returned yet.</Typography>
                )}
              </DetailPanel>
            </Grid>
            <Grid size={{ xs: 12, lg: 6 }}>
              <DetailPanel title="Priority Breakdown">
                {priorityBreakdown.length ? (
                  <HorizontalBars items={priorityBreakdown} />
                ) : (
                  <Typography color="text.secondary">No priority breakdown available.</Typography>
                )}
              </DetailPanel>
            </Grid>
            <Grid size={{ xs: 12, lg: 7 }}>
              <DetailPanel title="Top Autonomous Findings">
                {data.topFindings.length ? data.topFindings.slice(0, 3).map((finding) => (
                  <DetailRow
                    key={`${finding.rank}-${finding.service}-${finding.metric}`}
                    title={`${finding.service} / ${finding.metric}`}
                    meta={`${finding.behavior} • importance ${finding.importance.toFixed(2)} • ${relativeTime(finding.firstObserved)}`}
                    to={finding.href}
                  />
                )) : <Typography color="text.secondary">No autonomous findings returned for this window.</Typography>}
              </DetailPanel>
            </Grid>
            <Grid size={{ xs: 12, lg: 5 }}>
              <DetailPanel title="Behavior Distribution">
                {data.behaviorDistribution.length ? <HorizontalBars items={data.behaviorDistribution.map((item) => ({ ...item, color: ui.blue }))} /> : <Typography color="text.secondary">No behavior distribution available.</Typography>}
              </DetailPanel>
            </Grid>
            <Grid size={{ xs: 12, lg: 6 }}>
              <DetailPanel title="Execution Timeline">
                {data.executionRows.length ? data.executionRows.slice(0, 5).map((row) => (
                  <TimelineRow key={row.id} title={row.scope} meta={`${row.metrics} • ${relativeTime(row.completed)}`} status={row.status} failed={row.status.toLowerCase().includes('fail')} />
                )) : <Typography color="text.secondary">No autonomous execution history is available.</Typography>}
              </DetailPanel>
            </Grid>
            <Grid size={{ xs: 12, lg: 6 }}>
              <DetailPanel title="Recent Autonomous Cases">
                {data.recentCases.length ? data.recentCases.slice(0, 5).map((caseItem) => (
                  <DetailRow key={caseItem.id} title={caseItem.title} meta={`${caseItem.status} • ${caseItem.meta} • ${relativeTime(caseItem.updatedAt)}`} to={caseItem.href} />
                )) : <Typography color="text.secondary">No related cases returned.</Typography>}
              </DetailPanel>
            </Grid>
          </Grid>
        </Box>
      </Collapse>
    </WorkspacePanel>
  );
}

function OpenInvestigationsPanel({ openCases }: { openCases: ReturnType<typeof toCaseRows> }) {
  return (
    <WorkspacePanel sx={{ p: 2.5, height: '100%' }}>
      <Typography sx={{ fontWeight: 900, fontSize: 20 }}>Open Investigations</Typography>
      <Typography sx={{ color: ui.muted, mb: 1.5 }}>Top 3 cases</Typography>
      <Stack spacing={1.4}>
        {openCases.slice(0, 3).map((item) => <CaseMiniRow key={item.id} id={item.id} title={`${item.caseId} - ${item.title}`} meta={`Updated ${relativeTime(item.updatedAt)}`} status={item.status} />)}
        {!openCases.length ? <Typography color="text.secondary">No open cases returned by the API.</Typography> : null}
      </Stack>
    </WorkspacePanel>
  );
}

function AutonomousStatusTile({ label, value, detail, tone }: { label: string; value: number | string; detail: string; tone: string }) {
  return (
    <Box sx={{ border: `1px solid ${ui.border}`, borderRadius: '8px', p: 1.5, bgcolor: 'var(--os-surface)', minWidth: 0 }}>
      <Typography sx={{ color: ui.muted, fontSize: 12, fontWeight: 800 }}>{label}</Typography>
      <Typography sx={{ color: ui.text, fontSize: 20, fontWeight: 900, mt: 0.4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</Typography>
      <Typography sx={{ color: tone, fontSize: 12, fontWeight: 800, mt: 0.8 }}>{detail}</Typography>
    </Box>
  );
}

function MiniBarChart({ items }: { items: Array<{ label: string; value: number }> }) {
  const max = Math.max(...items.map((item) => item.value), 1);
  return (
    <Stack direction="row" alignItems="flex-end" spacing={1.2} sx={{ height: 150, pt: 1 }}>
      {items.map((item, index) => {
        const height = Math.max(8, (item.value / max) * 104);
        return (
          <Box key={`${item.label}-${index}`} sx={{ flex: 1, minWidth: 0, textAlign: 'center' }}>
            <Typography sx={{ fontSize: 12, fontWeight: 850, color: ui.text, mb: 0.8 }}>{item.value}</Typography>
            <Box sx={{ height, borderRadius: '6px 6px 2px 2px', bgcolor: item.value > 0 ? ui.blue : 'var(--os-border)', transition: 'height 160ms ease' }} />
            <Typography sx={{ color: ui.muted, fontSize: 11, mt: 0.8, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{item.label}</Typography>
          </Box>
        );
      })}
    </Stack>
  );
}

function HorizontalBars({ items }: { items: Array<{ label: string; count: number; color?: string }> }) {
  const max = Math.max(...items.map((item) => item.count), 1);
  return (
    <Stack spacing={1.2}>
      {items.map((item) => (
        <Box key={item.label}>
          <Stack direction="row" justifyContent="space-between" spacing={1}>
            <Typography sx={{ fontWeight: 850 }}>{item.label}</Typography>
            <Typography sx={{ color: ui.muted, fontWeight: 800 }}>{item.count}</Typography>
          </Stack>
          <Box sx={{ mt: 0.7, height: 8, borderRadius: '999px', bgcolor: 'var(--os-border)', overflow: 'hidden' }}>
            <Box sx={{ width: `${Math.max(4, (item.count / max) * 100)}%`, height: '100%', bgcolor: item.color ?? priorityColor(item.label), borderRadius: '999px' }} />
          </Box>
        </Box>
      ))}
    </Stack>
  );
}

function TimelineRow({ title, meta, status, failed }: { title: string; meta: string; status: string; failed?: boolean }) {
  return (
    <Stack direction="row" spacing={1.2} alignItems="flex-start">
      <Box sx={{ width: 22, height: 22, borderRadius: '999px', bgcolor: failed ? 'var(--os-tint-rose)' : 'var(--os-tint-green)', color: failed ? ui.red : ui.green, display: 'grid', placeItems: 'center', fontSize: 13, fontWeight: 900 }}>
        {failed ? '!' : <CheckCircleRoundedIcon sx={{ fontSize: 15 }} />}
      </Box>
      <Box sx={{ minWidth: 0 }}>
        <Typography sx={{ fontWeight: 850, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{title}</Typography>
        <Typography sx={{ color: ui.muted, fontSize: 13 }}>{status} • {meta}</Typography>
      </Box>
    </Stack>
  );
}

function DetailPanel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Box sx={{ border: `1px solid ${ui.border}`, borderRadius: '8px', p: 2, minHeight: 180 }}>
      <Typography sx={{ fontWeight: 900, mb: 1.5 }}>{title}</Typography>
      <Stack spacing={1}>{children}</Stack>
    </Box>
  );
}

function buildPriorityBreakdown(findings: AutonomousDashboardData['topFindings']) {
  const counts = findings.reduce<Record<string, number>>((acc, finding) => {
    const label = titleCase(finding.severity || 'normal');
    acc[label] = (acc[label] ?? 0) + 1;
    return acc;
  }, {});
  return Object.entries(counts)
    .map(([label, count]) => ({ label, count, color: priorityColor(label) }))
    .sort((left, right) => right.count - left.count);
}

function buildFindingsByObserved(findings: AutonomousDashboardData['topFindings']) {
  const counts = findings.reduce<Record<string, number>>((acc, finding) => {
    const date = finding.firstObserved ? new Date(finding.firstObserved) : null;
    const label = date && !Number.isNaN(date.getTime()) ? date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : 'Unknown';
    acc[label] = (acc[label] ?? 0) + 1;
    return acc;
  }, {});
  return Object.entries(counts)
    .map(([label, value]) => ({ label, value }))
    .slice(-5);
}

function priorityColor(label: string) {
  const normalized = label.toLowerCase();
  if (normalized.includes('critical') || normalized.includes('significant')) return ui.red;
  if (normalized.includes('high')) return ui.orange;
  if (normalized.includes('medium')) return '#f59e0b';
  if (normalized.includes('low') || normalized.includes('normal')) return ui.green;
  return ui.blue;
}

function DetailRow({ title, meta, to }: { title: string; meta: string; to?: string }) {
  const content = (
    <Box sx={{ minWidth: 0, textAlign: 'left' }}>
      <Typography sx={{ fontWeight: 850, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{title}</Typography>
      <Typography sx={{ color: ui.muted, fontSize: 13 }}>{meta}</Typography>
    </Box>
  );
  if (to) {
    return (
      <Button component={RouterLink} to={to} sx={{ justifyContent: 'flex-start', p: 0, color: 'inherit', textTransform: 'none' }}>
        {content}
      </Button>
    );
  }
  return content;
}

function CaseMiniRow({ id, title, meta, status, severity = false }: { id: number; title: string; meta: string; status: string; severity?: boolean }) {
  return (
    <Button component={RouterLink} to={id ? `/cases/${id}` : '/behavior-intelligence'} sx={{ justifyContent: 'flex-start', gap: 1.3, p: 0, color: 'inherit', textTransform: 'none' }}>
      <IconTile bg={severity ? 'var(--os-tint-orange)' : 'var(--os-tint-rose)'} color={severity ? ui.orange : ui.red}><ShowChartRoundedIcon fontSize="small" /></IconTile>
      <Box sx={{ minWidth: 0, flex: 1, textAlign: 'left' }}>
        <Typography sx={{ fontWeight: 800, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{title}</Typography>
        <Typography sx={{ color: ui.muted, fontSize: 13 }}>{meta}</Typography>
      </Box>
      <Pill label={status} tone={severity ? 'severity' : 'status'} />
    </Button>
  );
}
