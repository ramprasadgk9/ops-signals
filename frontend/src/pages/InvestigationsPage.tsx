import { useMemo, useState } from 'react';
import { Box, Button, Grid2 as Grid, Stack, Tab, Table, TableBody, TableCell, TableHead, TableRow, Tabs, Typography } from '@mui/material';
import OpenInNewRoundedIcon from '@mui/icons-material/OpenInNewRounded';
import { Link as RouterLink } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { ErrorState } from '../components/ErrorState';
import { PageHeader, Pill, WorkspacePanel } from '../standalone/components';
import { formatDateTime, relativeTime, ui } from '../standalone/theme';
import { groupInvestigationRows, toCaseRows } from '../standalone/casesService';

export function InvestigationsPage() {
  const casesQuery = useQuery({ queryKey: ['cases-investigations'], queryFn: () => api.cases(200) });
  const [tab, setTab] = useState('active');
  const rows = toCaseRows(casesQuery.data ?? []);
  const groups = useMemo(() => groupInvestigationRows(rows), [rows]);
  const counts = { active: groups.active.length, attention: groups.attention.length, onHold: groups.onHold.length, all: groups.all.length };
  const filtered = groups[tab as keyof typeof groups] ?? groups.active;
  const selected = filtered[0] ?? rows[0];
  const timeline = selected?.notes ?? [];

  if (casesQuery.isLoading) return <LoadingSkeleton />;
  if (casesQuery.error) return <ErrorState message="Failed to load investigations" onRetry={() => void casesQuery.refetch()} />;

  return (
    <Stack spacing={3}>
      <PageHeader
        title="Investigations"
        subtitle="Track and prioritize ongoing investigations"
        action={<Button variant="contained" disabled sx={{ bgcolor: ui.blue, textTransform: 'none', fontWeight: 850 }}>New Case Requires Finding</Button>}
      />
      <Tabs value={tab} onChange={(_, value) => setTab(value)} sx={{ '& .MuiTab-root': { textTransform: 'none', fontWeight: 850 }, '& .Mui-selected': { color: `${ui.purple} !important` }, '& .MuiTabs-indicator': { bgcolor: ui.purple, height: 3 } }}>
        <Tab value="active" label={`Active ${counts.active}`} />
        <Tab value="attention" label={`Needs Attention ${counts.attention}`} />
        <Tab value="onHold" label={`On Hold ${counts.onHold}`} />
        <Tab value="all" label={`All ${counts.all}`} />
      </Tabs>
      <WorkspacePanel sx={{ overflow: 'hidden' }}>
        <Table>
          <TableHead><TableRow sx={{ '& th': { color: ui.muted, fontWeight: 800, borderColor: ui.border } }}><TableCell>Case</TableCell><TableCell>Finding</TableCell><TableCell>Severity</TableCell><TableCell>Status</TableCell><TableCell>Assigned To</TableCell><TableCell>Updated</TableCell><TableCell align="right">Actions</TableCell></TableRow></TableHead>
          <TableBody>
            {filtered.map((item) => (
              <TableRow key={item.id} hover sx={{ '& td': { py: 2.2, borderColor: '#f1f5f9' } }}>
                <TableCell sx={{ fontWeight: 850 }}>{item.caseId}</TableCell>
                <TableCell sx={{ fontWeight: 800 }}>{item.title}</TableCell>
                <TableCell><Pill label={item.severity} tone="severity" /></TableCell>
                <TableCell><Pill label={item.investigationStatus} /></TableCell>
                <TableCell sx={{ color: ui.muted }}>Assignment not supported</TableCell>
                <TableCell>{relativeTime(item.updatedAt)}</TableCell>
                <TableCell align="right"><Button component={RouterLink} to={`/cases/${item.id}`} variant="outlined" size="small" sx={{ minWidth: 36, px: 1, borderColor: ui.border }}><OpenInNewRoundedIcon fontSize="small" /></Button></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </WorkspacePanel>
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 6 }}>
          <WorkspacePanel sx={{ p: 2.5 }}>
            <Typography variant="h6" sx={{ fontWeight: 850, mb: 2 }}>Investigation Timeline {selected ? `(C-${selected.id})` : ''}</Typography>
            <Stack spacing={2}>
              <Stack direction="row" spacing={2}>
                <Box sx={{ width: 10, height: 10, mt: 0.7, borderRadius: '50%', bgcolor: '#60a5fa', boxShadow: '0 0 0 4px #eef2ff' }} />
                <Box><Typography sx={{ color: ui.muted, fontSize: 13 }}>{selected ? formatDateTime(selected.createdAt) : 'n/a'}</Typography><Typography sx={{ fontWeight: 850 }}>Case created from finding</Typography><Typography sx={{ color: ui.muted }}>{selected?.summary ?? 'No case selected.'}</Typography></Box>
              </Stack>
              {timeline.map((note, index) => (
                <Stack key={`${note.timestamp ?? 'note'}-${index}`} direction="row" spacing={2}>
                  <Box sx={{ width: 10, height: 10, mt: 0.7, borderRadius: '50%', bgcolor: index % 2 ? ui.purple : '#60a5fa', boxShadow: '0 0 0 4px #eef2ff' }} />
                  <Box><Typography sx={{ color: ui.muted, fontSize: 13 }}>{formatDateTime(note.timestamp)}</Typography><Typography sx={{ fontWeight: 850 }}>Investigation note</Typography><Typography sx={{ color: ui.muted }}>{note.note}</Typography></Box>
                </Stack>
              ))}
              {selected && timeline.length === 0 ? <Typography color="text.secondary">No investigation notes are stored for this case yet.</Typography> : null}
            </Stack>
          </WorkspacePanel>
        </Grid>
        <Grid size={{ xs: 12, lg: 6 }}>
          <WorkspacePanel sx={{ p: 2.5 }}>
            <Typography variant="h6" sx={{ fontWeight: 850, mb: 2 }}>Case Summary</Typography>
            {selected ? (
              <Stack spacing={2}><Typography sx={{ fontSize: 20, fontWeight: 900 }}>{selected.caseId}</Typography><SummaryRow label="Status" value={<Pill label={selected.investigationStatus} />} /><SummaryRow label="Severity" value={<Pill label={selected.severity} tone="severity" />} /><SummaryRow label="Created" value={formatDateTime(selected.createdAt)} /><SummaryRow label="Assigned To" value="Assignment not supported" /><SummaryRow label="Services" value={selected.service} /><SummaryRow label="Metrics" value={selected.metric} /><SummaryRow label="Priority" value={selected.priority} /><Button component={RouterLink} to={`/cases/${selected.id}`} variant="contained" sx={{ bgcolor: ui.blue, textTransform: 'none', fontWeight: 850 }}>Open Case</Button></Stack>
            ) : <Typography color="text.secondary">No investigations returned yet.</Typography>}
          </WorkspacePanel>
        </Grid>
      </Grid>
    </Stack>
  );
}

function SummaryRow({ label, value }: { label: string; value: React.ReactNode }) {
  return <Stack direction="row" alignItems="center" justifyContent="space-between"><Typography sx={{ color: ui.muted }}>{label}</Typography><Box sx={{ fontWeight: 800 }}>{value}</Box></Stack>;
}
