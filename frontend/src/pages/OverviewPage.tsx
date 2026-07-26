import { Box, Button, Grid2 as Grid, Stack, Typography } from '@mui/material';
import WarningAmberRoundedIcon from '@mui/icons-material/WarningAmberRounded';
import WorkOutlineRoundedIcon from '@mui/icons-material/WorkOutlineRounded';
import HubRoundedIcon from '@mui/icons-material/HubRounded';
import DnsRoundedIcon from '@mui/icons-material/DnsRounded';
import StorageRoundedIcon from '@mui/icons-material/StorageRounded';
import BoltRoundedIcon from '@mui/icons-material/BoltRounded';
import ShowChartRoundedIcon from '@mui/icons-material/ShowChartRounded';
import { Link as RouterLink } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../api/queries';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { PageHeader, IconTile, Pill, SectionHeader, WorkspacePanel } from '../standalone/components';
import { relativeTime, severityTone, titleCase, ui } from '../standalone/theme';
import { toCaseRows } from '../standalone/casesService';
import { buildMemorySummaryFromStats } from '../standalone/memoryService';

const categoryColors = ['#ff3b3f', '#ff8a1f', '#3b82f6', '#7c3aed', '#64748b'];

function KpiCard({ icon, value, label, delta, to, bg, color }: { icon: React.ReactNode; value: number | string; label: string; delta: string; to: string; bg: string; color: string }) {
  return (
    <WorkspacePanel sx={{ p: 2.5 }}>
      <Button component={RouterLink} to={to} sx={{ display: 'flex', justifyContent: 'flex-start', gap: 2, p: 0, width: '100%', textTransform: 'none', color: 'inherit' }}>
        <IconTile bg={bg} color={color}>{icon}</IconTile>
        <Box sx={{ textAlign: 'left' }}>
          <Typography sx={{ fontSize: 28, fontWeight: 900, lineHeight: 1 }}>{value}</Typography>
          <Typography sx={{ color: '#334155', fontWeight: 750 }}>{label}</Typography>
          <Typography sx={{ mt: 1.4, color, fontSize: 13, fontWeight: 800 }}>↑ {delta}</Typography>
        </Box>
      </Button>
    </WorkspacePanel>
  );
}

export function OverviewPage() {
  const findingsQuery = useQuery({ queryKey: ['findings-overview', '24h'], queryFn: () => api.findings(undefined, undefined, undefined, '24h') });
  const casesQuery = useQuery({ queryKey: ['cases-overview'], queryFn: () => api.cases(200) });
  const behaviorsQuery = useQuery({ queryKey: ['behavior-findings-overview'], queryFn: () => api.behaviorFindings() });
  const summaryQuery = useQuery({ queryKey: ['overview-summary', '24h'], queryFn: () => api.overviewSummary('24h') });
  const memoryStatsQuery = useQuery({ queryKey: ['memory-stats'], queryFn: api.memoryStats });

  if (findingsQuery.isLoading || casesQuery.isLoading || behaviorsQuery.isLoading || summaryQuery.isLoading || memoryStatsQuery.isLoading) return <LoadingSkeleton />;

  const findings = findingsQuery.data ?? [];
  const cases = casesQuery.data ?? [];
  const behaviors = behaviorsQuery.data ?? [];
  const summary = summaryQuery.data;
  const caseRows = toCaseRows(cases);
  const openCases = caseRows.filter((item) => item.isOpen);
  const memorySummary = buildMemorySummaryFromStats(memoryStatsQuery.data);
  const memoryUnavailable = Boolean(memoryStatsQuery.error || memorySummary?.availability === 'unavailable');
  const recentFindings = [...findings].sort((a, b) => new Date(b.created_at ?? 0).getTime() - new Date(a.created_at ?? 0).getTime());
  const indexedCases = caseRows
    .filter((item) => cases.find((source) => source.id === item.id)?.memory_status === 'indexed')
    .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());
  const categoryCounts = (summary?.category_breakdown ?? []).map((item) => ({ name: titleCase(item.category), value: item.count }));
  const trendData = (summary?.severity_trend ?? []).map((item) => ({
    time: new Date(item.timestamp).toLocaleString(undefined, summary?.window === '7d' ? { month: 'numeric', day: 'numeric' } : { hour: '2-digit', minute: '2-digit' }),
    Critical: item.critical,
    High: item.high,
    Medium: item.medium,
    Low: item.low,
  }));

  return (
    <Stack spacing={3}>
      <PageHeader title="Overview" subtitle="Operational intelligence at a glance" />
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, sm: 6, lg: 2.4 }}><KpiCard icon={<WarningAmberRoundedIcon />} value={summaryQuery.error ? 'Unavailable' : summary?.active_findings ?? 0} label="Active Findings" delta="from overview summary" to="/findings?window=24h" bg="#fff1f2" color={ui.red} /></Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 2.4 }}><KpiCard icon={<WorkOutlineRoundedIcon />} value={summaryQuery.error ? 'Unavailable' : summary?.open_cases ?? 0} label="Open Cases" delta="from overview summary" to="/cases" bg="#fff7ed" color={ui.orange} /></Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 2.4 }}><KpiCard icon={<HubRoundedIcon />} value={summaryQuery.error ? 'Unavailable' : summary?.behavior_changes ?? 0} label="Behavior Changes" delta="from overview summary" to="/behavior-intelligence" bg="#f3f0ff" color={ui.purple} /></Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 2.4 }}><KpiCard icon={<DnsRoundedIcon />} value={summaryQuery.error ? 'Unavailable' : summary?.impacted_services ?? 0} label="Impacted Services" delta="from overview summary" to="/findings?window=24h" bg="#eff6ff" color="#3b82f6" /></Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 2.4 }}><KpiCard icon={<StorageRoundedIcon />} value={memoryUnavailable ? 'Memory unavailable' : memorySummary?.indexedItems ?? 0} label="Memory Items" delta="authoritative memory stats" to="/operational-memory" bg="#ecfdf5" color={ui.green} /></Grid>
      </Grid>

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 5 }}>
          <WorkspacePanel sx={{ p: 2.5, height: 330 }}>
            <SectionHeader title="Finding Severity Trend" to="/findings?window=24h" />
            {summaryQuery.error ? (
              <UnavailableBlock title="Historical trend unavailable." message="The overview summary endpoint could not be loaded." />
            ) : trendData.length ? (
              <ResponsiveContainer width="100%" height={235}>
                <LineChart data={trendData}>
                  <XAxis dataKey="time" tickLine={false} axisLine={false} />
                  <YAxis allowDecimals={false} tickLine={false} axisLine={false} />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="Critical" stroke="#ff3b3f" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="High" stroke="#ff8a1f" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="Medium" stroke="#facc15" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="Low" stroke="#3b82f6" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : <Typography color="text.secondary">No severity trend points returned for this window.</Typography>}
          </WorkspacePanel>
        </Grid>
        <Grid size={{ xs: 12, lg: 4 }}>
          <WorkspacePanel sx={{ p: 2.5, height: 330 }}>
            <SectionHeader title="Top Finding Categories" to="/findings?window=24h" />
            {summaryQuery.error ? <UnavailableBlock title="Finding categories unavailable." message="The overview summary endpoint failed, so this section is not replaced with zeros." /> : categoryCounts.length ? (
              <Stack direction="row" alignItems="center" spacing={2}>
                <Box sx={{ width: 190, height: 210 }}>
                  <ResponsiveContainer>
                    <PieChart>
                      <Pie data={categoryCounts} dataKey="value" innerRadius={55} outerRadius={88}>
                        {categoryCounts.map((entry, index) => <Cell key={entry.name} fill={categoryColors[index % categoryColors.length]} />)}
                      </Pie>
                      <Tooltip />
                    </PieChart>
                  </ResponsiveContainer>
                </Box>
                <Stack spacing={1.5} sx={{ flex: 1 }}>
                  {categoryCounts.slice(0, 5).map((item, index) => (
                    <Stack key={item.name} direction="row" justifyContent="space-between">
                      <Typography sx={{ fontWeight: 750 }}>{item.name}</Typography>
                      <Typography sx={{ color: ui.muted }}>{item.value}</Typography>
                    </Stack>
                  ))}
                </Stack>
              </Stack>
            ) : <Typography color="text.secondary">No finding categories returned by the findings API.</Typography>}
          </WorkspacePanel>
        </Grid>
        <Grid size={{ xs: 12, lg: 3 }}>
          <WorkspacePanel sx={{ p: 2.5, height: 330 }}>
            <SectionHeader title="Recent Findings" to="/findings?window=24h" />
            <Stack spacing={1.2}>
              {recentFindings.slice(0, 5).map((finding) => {
                const tone = severityTone(finding.health_status);
                return (
                  <Button key={finding.id ?? finding.title} component={RouterLink} to="/findings?window=24h" sx={{ justifyContent: 'flex-start', gap: 1.2, p: 0, color: 'inherit', textTransform: 'none' }}>
                    <IconTile bg={tone.bg} color={tone.color}><BoltRoundedIcon fontSize="small" /></IconTile>
                    <Box sx={{ minWidth: 0, flex: 1, textAlign: 'left' }}>
                      <Typography sx={{ fontWeight: 800, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{finding.title}</Typography>
                      <Typography sx={{ color: ui.muted, fontSize: 13 }}>{relativeTime(finding.created_at)}</Typography>
                    </Box>
                    <Pill label={finding.health_status} tone="severity" />
                  </Button>
                );
              })}
              {findingsQuery.error ? <Typography color="error">Recent findings unavailable.</Typography> : !recentFindings.length ? <Typography color="text.secondary">No findings returned for the last 24 hours.</Typography> : null}
            </Stack>
          </WorkspacePanel>
        </Grid>
      </Grid>

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 4 }}>
          <WorkspacePanel sx={{ p: 2.5, minHeight: 280 }}>
            <SectionHeader title="Open Cases" to="/cases" />
            <Stack spacing={1.4}>
              {openCases.slice(0, 4).map((item) => <CaseMiniRow key={item.id} id={item.id} title={item.title} meta={`${item.caseId} • Updated ${relativeTime(item.updatedAt)}`} status={item.status} />)}
              {casesQuery.error ? <Typography color="error">Open cases unavailable.</Typography> : !openCases.length ? <Typography color="text.secondary">No open cases returned by the API.</Typography> : null}
            </Stack>
          </WorkspacePanel>
        </Grid>
        <Grid size={{ xs: 12, lg: 4 }}>
          <WorkspacePanel sx={{ p: 2.5, minHeight: 280 }}>
            <SectionHeader title="Recent Behavior Changes" to="/behavior-intelligence" />
            <Stack spacing={1.4}>
              {behaviors.slice(0, 4).map((item) => <CaseMiniRow key={item.id} id={item.case_id ?? 0} title={item.title} meta={`Detected ${relativeTime(item.created_at)} • ${item.evidence_json.length} signals`} status={item.severity} severity />)}
              {behaviorsQuery.error ? <Typography color="error">Behavior changes unavailable.</Typography> : !behaviors.length ? <Typography color="text.secondary">No behavior changes returned by the API.</Typography> : null}
            </Stack>
          </WorkspacePanel>
        </Grid>
        <Grid size={{ xs: 12, lg: 4 }}>
          <WorkspacePanel sx={{ p: 2.5, minHeight: 280 }}>
            <SectionHeader title="Operational Memory" to="/operational-memory" />
            <Stack spacing={1.4}>
              {indexedCases.slice(0, 3).map((item) => <CaseMiniRow key={item.id} id={item.id} title={`Indexed: ${item.title}`} meta={`Last updated ${relativeTime(item.updatedAt)}`} status="indexed" />)}
              {memoryUnavailable ? <Typography color="error">Memory unavailable.</Typography> : !indexedCases.length ? <Typography color="text.secondary">No indexed cases returned by the cases API.</Typography> : null}
              <Button component={RouterLink} to="/assistant" variant="contained" sx={{ mt: 1, bgcolor: ui.blue, textTransform: 'none', fontWeight: 850 }}>
                Ask Ops Signals
              </Button>
            </Stack>
          </WorkspacePanel>
        </Grid>
      </Grid>
    </Stack>
  );
}

function UnavailableBlock({ title, message }: { title: string; message: string }) {
  return (
    <Box sx={{ height: 220, display: 'grid', placeItems: 'center', textAlign: 'center', px: 3, borderRadius: '8px', bgcolor: '#f8fafc', border: `1px dashed ${ui.border}` }}>
      <Box>
        <Typography sx={{ fontWeight: 900, color: ui.text }}>{title}</Typography>
        <Typography sx={{ color: ui.muted, mt: 1, maxWidth: 430 }}>{message}</Typography>
      </Box>
    </Box>
  );
}

function CaseMiniRow({ id, title, meta, status, severity = false }: { id: number; title: string; meta: string; status: string; severity?: boolean }) {
  return (
    <Button component={RouterLink} to={id ? `/cases/${id}` : '/behavior-intelligence'} sx={{ justifyContent: 'flex-start', gap: 1.3, p: 0, color: 'inherit', textTransform: 'none' }}>
      <IconTile bg={severity ? '#fff7ed' : '#fff1f2'} color={severity ? ui.orange : ui.red}><ShowChartRoundedIcon fontSize="small" /></IconTile>
      <Box sx={{ minWidth: 0, flex: 1, textAlign: 'left' }}>
        <Typography sx={{ fontWeight: 800, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{title}</Typography>
        <Typography sx={{ color: ui.muted, fontSize: 13 }}>{meta}</Typography>
      </Box>
      <Pill label={status} tone={severity ? 'severity' : 'status'} />
    </Button>
  );
}
