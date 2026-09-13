import { useState } from 'react';
import { Box, Button, Chip, Grid2 as Grid, Stack, Typography } from '@mui/material';
import WarningAmberRoundedIcon from '@mui/icons-material/WarningAmberRounded';
import CategoryRoundedIcon from '@mui/icons-material/CategoryRounded';
import { useQuery } from '@tanstack/react-query';
import { Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api/queries';
import { FindingDetailsDrawer } from '../components/FindingDetailsDrawer';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { TopFindingsList } from '../components/TopFindingsList';
import { WorkspacePanel } from '../standalone/components';
import { titleCase, ui } from '../standalone/theme';
import type { Finding } from '../types';

type FindingsWindow = '24h' | '7d';

const categoryColors = ['#ff3b3f', '#ff8a1f', '#3b82f6', '#7c3aed', '#64748b'];
const windows: Array<{ id: FindingsWindow; label: string }> = [
  { id: '24h', label: 'Last 24 hours' },
  { id: '7d', label: 'Last 7 days' },
];

function windowFromParams(value: string | null): FindingsWindow {
  return value === '7d' ? '7d' : '24h';
}

export function FindingsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const window = windowFromParams(searchParams.get('window'));
  const findingsQuery = useQuery({ queryKey: ['findings', window], queryFn: () => api.findings(undefined, undefined, undefined, window) });
  const summaryQuery = useQuery({ queryKey: ['overview-summary', window], queryFn: () => api.overviewSummary(window) });

  const [selectedFinding, setSelectedFinding] = useState<Finding | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  // Re-fetches this one finding on open so ai_summary (computed and cached lazily, on first
  // detail view, by the backend) has a chance to populate - the list endpoint above never
  // triggers that computation, so the list-provided finding always has ai_summary: null.
  const findingDetailQuery = useQuery({
    queryKey: ['finding-detail', selectedFinding?.id],
    queryFn: () => api.getFinding(selectedFinding!.id!),
    enabled: drawerOpen && Boolean(selectedFinding?.id),
  });

  const handleViewDetails = (finding: Finding) => {
    setSelectedFinding(finding);
    setDrawerOpen(true);
  };

  if (findingsQuery.isLoading || summaryQuery.isLoading) return <LoadingSkeleton />;

  const findings = findingsQuery.data ?? [];
  const summary = summaryQuery.data;
  const categoryCounts = (summary?.category_breakdown ?? []).map((item) => ({ name: titleCase(item.category), value: item.count }));
  const trendData = (summary?.severity_trend ?? []).map((item) => ({
    time: new Date(item.timestamp).toLocaleString(undefined, window === '7d' ? { month: 'numeric', day: 'numeric' } : { hour: '2-digit', minute: '2-digit' }),
    Critical: item.critical,
    High: item.high,
    Medium: item.medium,
    Low: item.low,
  }));

  return (
    <Stack spacing={3}>
      <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={2}>
        <Box>
          <Typography variant="h4" sx={{ fontWeight: 900 }}>Findings</Typography>
          <Typography variant="body2" color="text.secondary">
            Showing findings for the same window used by the Overview severity trend and category charts.
          </Typography>
        </Box>
        <Stack direction="row" spacing={1}>
          {windows.map((item) => (
            <Button
              key={item.id}
              variant={item.id === window ? 'contained' : 'outlined'}
              onClick={() => setSearchParams({ window: item.id })}
              sx={{ textTransform: 'none', fontWeight: 800, bgcolor: item.id === window ? '#009688' : '#fff' }}
            >
              {item.label}
            </Button>
          ))}
        </Stack>
      </Stack>

      {summaryQuery.error ? (
        <WorkspacePanel sx={{ p: 2.5 }}>
          <Typography color="error" sx={{ fontWeight: 800 }}>Overview summary unavailable, so chart totals cannot be reconciled.</Typography>
        </WorkspacePanel>
      ) : null}

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <WorkspacePanel sx={{ p: 2.5 }}>
            <Stack direction="row" spacing={1.5} alignItems="center">
              <WarningAmberRoundedIcon sx={{ color: ui.red }} />
              <Box>
                <Typography sx={{ fontSize: 28, fontWeight: 900 }}>{summary?.active_findings ?? 0}</Typography>
                <Typography sx={{ color: '#334155', fontWeight: 750 }}>Active Findings</Typography>
              </Box>
            </Stack>
          </WorkspacePanel>
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <WorkspacePanel sx={{ p: 2.5 }}>
            <Stack direction="row" spacing={1.5} alignItems="center">
              <CategoryRoundedIcon sx={{ color: '#0f766e' }} />
              <Box>
                <Typography sx={{ fontSize: 28, fontWeight: 900 }}>{findings.length}</Typography>
                <Typography sx={{ color: '#334155', fontWeight: 750 }}>Findings In Window</Typography>
              </Box>
            </Stack>
          </WorkspacePanel>
        </Grid>
      </Grid>

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 7 }}>
          <WorkspacePanel sx={{ p: 2.5, height: 330 }}>
            <Typography sx={{ fontSize: 18, fontWeight: 900, mb: 1.5 }}>Finding Severity Trend</Typography>
            {trendData.length ? (
              <ResponsiveContainer width="100%" height={250}>
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
        <Grid size={{ xs: 12, lg: 5 }}>
          <WorkspacePanel sx={{ p: 2.5, height: 330 }}>
            <Typography sx={{ fontSize: 18, fontWeight: 900, mb: 1.5 }}>Top Finding Categories</Typography>
            {categoryCounts.length ? (
              <Stack direction="row" alignItems="center" spacing={2}>
                <Box sx={{ width: 190, height: 220 }}>
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
                  {categoryCounts.slice(0, 6).map((item) => (
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
      </Grid>

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
          <Typography sx={{ fontSize: 18, fontWeight: 900 }}>Finding Records</Typography>
          <Chip label={windows.find((item) => item.id === window)?.label ?? window} />
        </Stack>
        {findingsQuery.error ? (
          <Typography color="error">Findings unavailable.</Typography>
        ) : findings.length ? (
          <TopFindingsList findings={findings} onViewDetails={handleViewDetails} />
        ) : (
          <Typography color="text.secondary">No findings returned for this window.</Typography>
        )}
      </WorkspacePanel>

      <FindingDetailsDrawer
        open={drawerOpen}
        finding={findingDetailQuery.data ?? selectedFinding}
        onClose={() => setDrawerOpen(false)}
      />
    </Stack>
  );
}
