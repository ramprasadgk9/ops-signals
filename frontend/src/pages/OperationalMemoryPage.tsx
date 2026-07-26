import { Box, Button, Chip, Grid2 as Grid, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography } from '@mui/material';
import StorageRoundedIcon from '@mui/icons-material/StorageRounded';
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded';
import OpenInNewRoundedIcon from '@mui/icons-material/OpenInNewRounded';
import React from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { PageHeader, Pill, WorkspacePanel } from '../standalone/components';
import { formatDateTime, relativeTime, statusTone, ui } from '../standalone/theme';
import { toCaseRows } from '../standalone/casesService';
import { buildMemorySummaryFromStats } from '../standalone/memoryService';

const filters = [
  { id: 'indexed', label: 'Indexed' },
  { id: 'stale', label: 'Stale' },
  { id: 'failed', label: 'Failed' },
  { id: 'not_indexed', label: 'Not Indexed' },
  { id: 'all', label: 'All' },
];

export function OperationalMemoryPage() {
  const casesQuery = useQuery({ queryKey: ['operational-memory-cases'], queryFn: () => api.cases(200) });
  const memoryStatsQuery = useQuery({ queryKey: ['memory-stats'], queryFn: api.memoryStats });
  const [activeFilter, setActiveFilter] = React.useState('indexed');

  if (casesQuery.isLoading || memoryStatsQuery.isLoading) return <LoadingSkeleton />;

  const cases = casesQuery.data ?? [];
  const rows = toCaseRows(cases).map((row) => ({
    ...row,
    memoryStatus: cases.find((item) => item.id === row.id)?.memory_status ?? 'unknown',
  }));
  const memorySummary = buildMemorySummaryFromStats(memoryStatsQuery.data);
  const memoryUnavailable = Boolean(memoryStatsQuery.error || memorySummary?.availability === 'unavailable');
  const visibleRows = rows
    .filter((row) => activeFilter === 'all' || row.memoryStatus === activeFilter)
    .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());

  return (
    <Stack spacing={3}>
      <PageHeader
        title="Operational Memory"
        subtitle="Case knowledge indexed for retrieval, grounded in the existing cases and memory statistics APIs."
        action={
          <Button
            onClick={() => {
              void casesQuery.refetch();
              void memoryStatsQuery.refetch();
            }}
            startIcon={<RefreshRoundedIcon />}
            variant="outlined"
            sx={{ textTransform: 'none', fontWeight: 800 }}
          >
            Retry
          </Button>
        }
      />

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <MemoryStat label="Indexed Cases" value={memoryUnavailable ? 'Unavailable' : memoryStatsQuery.data?.indexed_cases ?? 0} />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <MemoryStat label="Stale Cases" value={memoryUnavailable ? 'Unavailable' : memoryStatsQuery.data?.stale_cases ?? 0} />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <MemoryStat label="Failed Cases" value={memoryUnavailable ? 'Unavailable' : memoryStatsQuery.data?.error_cases ?? 0} />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <MemoryStat label="Total Cases" value={memoryUnavailable ? 'Unavailable' : memoryStatsQuery.data?.total_cases ?? rows.length} />
        </Grid>
      </Grid>

      {memoryUnavailable ? (
        <WorkspacePanel sx={{ p: 2.5, borderColor: '#fecaca', bgcolor: '#fff7f7' }}>
          <Typography sx={{ fontWeight: 900, color: ui.red }}>Memory unavailable</Typography>
          <Typography sx={{ mt: 0.75, color: ui.muted }}>
            The memory statistics endpoint did not return an authoritative status, so counts are not replaced with zero.
          </Typography>
        </WorkspacePanel>
      ) : null}

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', md: 'center' }} spacing={2} sx={{ mb: 2 }}>
          <Box>
            <Typography variant="h6" sx={{ fontSize: 18, fontWeight: 900 }}>Memory Inventory</Typography>
            <Typography sx={{ color: ui.muted, fontSize: 13 }}>Case rows from `/api/cases?limit=200`; authoritative counts from `/api/memory/stats`.</Typography>
          </Box>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            {filters.map((filter) => (
              <Chip
                key={filter.id}
                label={filter.label}
                onClick={() => setActiveFilter(filter.id)}
                color={activeFilter === filter.id ? 'primary' : 'default'}
                variant={activeFilter === filter.id ? 'filled' : 'outlined'}
                sx={{ fontWeight: 800 }}
              />
            ))}
          </Stack>
        </Stack>

        {casesQuery.error ? (
          <Typography color="error">Cases unavailable. Memory inventory could not be loaded.</Typography>
        ) : !visibleRows.length ? (
          <Box sx={{ py: 7, textAlign: 'center', border: `1px dashed ${ui.border}`, borderRadius: '8px', bgcolor: '#f8fafc' }}>
            <Typography sx={{ fontWeight: 900 }}>No {filters.find((filter) => filter.id === activeFilter)?.label.toLowerCase()} cases returned.</Typography>
            <Typography sx={{ mt: 0.75, color: ui.muted }}>This is an empty backend result, not sample data.</Typography>
          </Box>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Case</TableCell>
                <TableCell>Service</TableCell>
                <TableCell>Metric</TableCell>
                <TableCell>Memory Status</TableCell>
                <TableCell>Updated</TableCell>
                <TableCell align="right">Action</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {visibleRows.map((row) => (
                <TableRow key={row.id} hover>
                  <TableCell>
                    <Typography sx={{ fontWeight: 850 }}>{row.title}</Typography>
                    <Typography sx={{ color: ui.muted, fontSize: 12 }}>{row.caseId} • {row.summary}</Typography>
                  </TableCell>
                  <TableCell>{row.service}</TableCell>
                  <TableCell>{row.metric}</TableCell>
                  <TableCell><Pill label={row.memoryStatus} /></TableCell>
                  <TableCell>
                    <Typography sx={{ fontWeight: 750 }}>{relativeTime(row.updatedAt)}</Typography>
                    <Typography sx={{ color: ui.muted, fontSize: 12 }}>{formatDateTime(row.updatedAt)}</Typography>
                  </TableCell>
                  <TableCell align="right">
                    <Button component={RouterLink} to={`/cases/${row.id}`} endIcon={<OpenInNewRoundedIcon />} size="small" sx={{ textTransform: 'none', fontWeight: 800 }}>
                      Open Case
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </WorkspacePanel>
    </Stack>
  );
}

function MemoryStat({ label, value }: { label: string; value: number | string }) {
  const tone = statusTone(String(label));
  return (
    <WorkspacePanel sx={{ p: 2.25 }}>
      <Stack direction="row" spacing={1.5} alignItems="center">
        <Box sx={{ width: 44, height: 44, borderRadius: '8px', bgcolor: tone.bg, color: ui.green, display: 'grid', placeItems: 'center' }}>
          <StorageRoundedIcon />
        </Box>
        <Box>
          <Typography sx={{ fontSize: 24, fontWeight: 900, lineHeight: 1 }}>{value}</Typography>
          <Typography sx={{ color: ui.muted, fontWeight: 800 }}>{label}</Typography>
        </Box>
      </Stack>
    </WorkspacePanel>
  );
}
