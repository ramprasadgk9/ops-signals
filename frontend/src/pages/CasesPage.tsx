import { useMemo, useState } from 'react';
import {
  Box,
  Button,
  Grid2 as Grid,
  InputAdornment,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import SearchRoundedIcon from '@mui/icons-material/SearchRounded';
import FilterAltRoundedIcon from '@mui/icons-material/FilterAltRounded';
import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded';
import { Link as RouterLink } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { ErrorState } from '../components/ErrorState';
import { PageHeader, Pill, WorkspacePanel } from '../standalone/components';
import { formatDateTime, relativeTime, titleCase, ui } from '../standalone/theme';
import { filterCaseRows, toCaseRows } from '../standalone/casesService';
import { CaseTicketCard } from '../components/CaseTicketCard';

export function CasesPage() {
  const casesQuery = useQuery({ queryKey: ['cases'], queryFn: () => api.cases(200) });
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('all');
  const [severity, setSeverity] = useState('all');
  const [selectedCaseId, setSelectedCaseId] = useState<number | null>(null);
  const cases = casesQuery.data ?? [];
  const rows = toCaseRows(cases);
  const filtered = useMemo(() => {
    return filterCaseRows(rows, { search, status, severity });
  }, [rows, search, severity, status]);
  const selected = useMemo(() => {
    if (selectedCaseId != null) {
      const match = filtered.find((item) => item.id === selectedCaseId);
      if (match) return match;
    }
    return filtered[0] ?? rows[0];
  }, [filtered, rows, selectedCaseId]);

  if (casesQuery.isLoading) return <LoadingSkeleton />;
  if (casesQuery.error) return <ErrorState message="Failed to load cases" onRetry={() => void casesQuery.refetch()} />;

  return (
    <Stack spacing={3}>
      <PageHeader
        title="Cases"
        subtitle="Manage and track operational investigations"
        action={<Button variant="contained" disabled sx={{ bgcolor: ui.blue, textTransform: 'none', fontWeight: 850 }}>New Case Requires Finding</Button>}
      />
      <Stack direction={{ xs: 'column', lg: 'row' }} spacing={1.5}>
        <TextField size="small" placeholder="Search cases..." value={search} onChange={(event) => setSearch(event.target.value)} sx={{ width: { xs: '100%', lg: 280 }, bgcolor: '#fff' }} InputProps={{ startAdornment: <InputAdornment position="start"><SearchRoundedIcon fontSize="small" /></InputAdornment> }} />
        <TextField select size="small" value={status} onChange={(event) => setStatus(event.target.value)} sx={{ minWidth: 150, bgcolor: '#fff' }}>
          <MenuItem value="all">All Status</MenuItem>
          {['open', 'in_progress', 'resolved', 'identified', 'not_started', 'completed'].map((value) => <MenuItem key={value} value={value}>{titleCase(value)}</MenuItem>)}
        </TextField>
        <TextField select size="small" value={severity} onChange={(event) => setSeverity(event.target.value)} sx={{ minWidth: 150, bgcolor: '#fff' }}>
          <MenuItem value="all">All Severity</MenuItem>
          {['critical', 'high', 'medium', 'low', 'significant', 'normal'].map((value) => <MenuItem key={value} value={value}>{titleCase(value)}</MenuItem>)}
        </TextField>
        <Button startIcon={<FilterAltRoundedIcon />} variant="outlined" disabled sx={{ borderColor: ui.border, color: '#334155', bgcolor: '#fff', textTransform: 'none', fontWeight: 750 }}>Additional Filters Unavailable</Button>
      </Stack>
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, xl: 9 }}>
          <WorkspacePanel sx={{ overflow: 'hidden' }}>
            <Table>
              <TableHead>
                <TableRow sx={{ '& th': { color: ui.muted, fontWeight: 800, borderColor: ui.border } }}>
                  <TableCell>Case ID</TableCell>
                  <TableCell>Title</TableCell>
                  <TableCell>Severity</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Owner</TableCell>
                  <TableCell>Created</TableCell>
                  <TableCell>Updated</TableCell>
                  <TableCell>Outcome</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {filtered.map((item) => {
                  const isSelected = selected?.id === item.id;
                  return (
                    <TableRow
                      key={item.id}
                      hover
                      selected={isSelected}
                      onClick={() => setSelectedCaseId(item.id)}
                      sx={{
                        cursor: 'pointer',
                        bgcolor: isSelected ? 'rgba(79, 70, 229, 0.05)' : 'inherit',
                        '& td': { py: 2, borderColor: '#f1f5f9' },
                      }}
                    >
                      <TableCell sx={{ fontWeight: 850 }}>{item.caseId}</TableCell>
                      <TableCell>
                        <Button
                          component={RouterLink}
                          to={`/cases/${item.id}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedCaseId(item.id);
                          }}
                          sx={{ p: 0, color: ui.text, textTransform: 'none', fontWeight: 850, textAlign: 'left' }}
                        >
                          {item.title}
                        </Button>
                      </TableCell>
                      <TableCell><Pill label={item.severity} tone="severity" /></TableCell>
                      <TableCell><Pill label={item.status} /></TableCell>
                      <TableCell sx={{ color: ui.muted }}>Assignment not supported</TableCell>
                      <TableCell>{formatDateTime(item.createdAt)}</TableCell>
                      <TableCell>{relativeTime(item.updatedAt)}</TableCell>
                      <TableCell>{item.outcome === 'resolved' ? <Pill label="verified" /> : '--'}</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
            <Typography sx={{ p: 2.2, color: ui.muted, fontWeight: 650 }}>Showing {filtered.length} of {cases.length} cases</Typography>
          </WorkspacePanel>
        </Grid>
        <Grid size={{ xs: 12, xl: 3 }}>
          <WorkspacePanel sx={{ p: 2.5 }}>
            <Typography variant="h6" sx={{ fontWeight: 850, mb: 2 }}>Case Overview {selected ? `(C-${selected.id})` : ''}</Typography>
            {selected ? (
              <Stack spacing={2.2}>
                <Box><Typography sx={{ color: ui.muted, fontSize: 13, mb: 0.5 }}>Summary</Typography><Typography>{selected.summary}</Typography></Box>
                <Box><Typography sx={{ color: ui.muted, fontSize: 13, mb: 0.5 }}>Root Cause</Typography><Typography>{selected.rootCause ?? 'Not identified yet.'}</Typography></Box>
                <Box><Typography sx={{ color: ui.muted, fontSize: 13, mb: 0.5 }}>Resolution</Typography><Typography>{selected.resolution ?? 'Pending investigation.'}</Typography></Box>
                <Stack direction="row" justifyContent="space-between"><Typography color={ui.muted}>Outcome</Typography><Pill label={selected.outcome} /></Stack>
                <Stack direction="row" justifyContent="space-between"><Typography color={ui.muted}>Resolved At</Typography><Typography>{selected.resolvedAt ? formatDateTime(selected.resolvedAt) : 'Not resolved'}</Typography></Stack>
                <Button component={RouterLink} to={`/cases/${selected.id}`} endIcon={<ArrowForwardRoundedIcon />} variant="outlined" sx={{ borderColor: ui.border, color: '#334155', textTransform: 'none', fontWeight: 850 }}>View Case Details</Button>
                <CaseTicketCard caseId={selected.id} />
              </Stack>
            ) : <Typography color="text.secondary">No cases returned yet.</Typography>}
          </WorkspacePanel>
        </Grid>
      </Grid>
    </Stack>
  );
}
