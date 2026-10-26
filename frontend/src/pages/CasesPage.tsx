import { useMemo, useState } from 'react';
import {
  Box,
  Button,
  Grid2 as Grid,
  InputAdornment,
  MenuItem,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Typography,
} from '@mui/material';
import SearchRoundedIcon from '@mui/icons-material/SearchRounded';
import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded';
import { Link as RouterLink, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { ErrorState } from '../components/ErrorState';
import { PageHeader, Pill, WorkspacePanel } from '../standalone/components';
import { formatDateTime, relativeTime, titleCase, ui } from '../standalone/theme';
import { CASE_TABS, filterCaseRows, inCaseTab, isCaseTab, toCaseRows, type CaseRow, type CaseTab } from '../standalone/casesService';
import { CaseTicketCard } from '../components/CaseTicketCard';
import { JiraTicketingHint } from '../components/JiraTicketingHint';
import { CaseOriginBadge } from '../components/CaseOriginBadge';
import { RootCauseUnconfirmedBadge } from '../components/RootCauseUnconfirmedBadge';
import { ServiceFilterField } from '../components/ServiceFilterField';
import { inService, serviceOptions, showServiceFilter } from '../utils/serviceFilter';

export function CasesPage() {
  const casesQuery = useQuery({ queryKey: ['cases'], queryFn: () => api.cases(200) });
  const [search, setSearch] = useState('');
  const [severity, setSeverity] = useState('all');
  const [selectedCaseId, setSelectedCaseId] = useState<number | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get('tab');
  const tab: CaseTab = isCaseTab(tabParam) ? tabParam : 'open';
  const originParam = searchParams.get('origin');
  const [origin, setOrigin] = useState<'all' | 'detected' | 'imported'>(
    originParam === 'imported' || originParam === 'detected' ? originParam : 'all'
  );
  const cases = casesQuery.data ?? [];
  const rows = toCaseRows(cases);
  // ?service= is in the URL so a filtered list can be shared; each case keeps its finding's service.
  const service = searchParams.get('service');
  const otherFiltersMatch = useMemo(() => filterCaseRows(rows, { search, severity, origin }), [rows, search, severity, origin]);
  const services = serviceOptions(otherFiltersMatch, service);
  // Tab counts follow the search, severity, origin and service filters so each tab says what it will show.
  const matching = useMemo(() => inService(otherFiltersMatch, service), [otherFiltersMatch, service]);
  const filtered = matching.filter((row) => inCaseTab(row, tab));
  const selected = useMemo(() => {
    if (selectedCaseId != null) {
      const match = filtered.find((item) => item.id === selectedCaseId);
      if (match) return match;
    }
    return filtered[0];
  }, [filtered, selectedCaseId]);

  const setTab = (value: CaseTab) => {
    const next = new URLSearchParams(searchParams);
    if (value === 'open') next.delete('tab');
    else next.set('tab', value);
    setSearchParams(next, { replace: true });
  };

  const setService = (value: string | null) => {
    const next = new URLSearchParams(searchParams);
    if (value) next.set('service', value);
    else next.delete('service');
    setSearchParams(next, { replace: true });
  };

  if (casesQuery.isLoading) return <LoadingSkeleton />;
  if (casesQuery.error) return <ErrorState message="Failed to load cases" onRetry={() => void casesQuery.refetch()} />;

  return (
    <Stack spacing={3}>
      <PageHeader
        title="Cases"
        subtitle="Track every investigation, from first look to confirmed root cause"
        action={<Button variant="contained" disabled sx={{ bgcolor: ui.blue, textTransform: 'none', fontWeight: 850 }}>New Case Requires Finding</Button>}
      />
      <JiraTicketingHint />
      <Tabs
        value={tab}
        onChange={(_, value: CaseTab) => setTab(value)}
        aria-label="Case status"
        variant="scrollable"
        allowScrollButtonsMobile
        sx={{ borderBottom: `1px solid ${ui.border}`, '& .MuiTab-root': { textTransform: 'none', fontWeight: 850 }, '& .Mui-selected': { color: `${ui.purple} !important` }, '& .MuiTabs-indicator': { bgcolor: ui.purple, height: 3 } }}
      >
        {CASE_TABS.map((item) => (
          <Tab key={item.value} value={item.value} label={`${item.label} ${matching.filter((row) => inCaseTab(row, item.value)).length}`} />
        ))}
      </Tabs>
      <Stack direction={{ xs: 'column', lg: 'row' }} spacing={1.5}>
        <TextField size="small" placeholder="Search cases..." value={search} onChange={(event) => setSearch(event.target.value)} sx={{ width: { xs: '100%', lg: 280 }, bgcolor: 'var(--os-surface)' }} InputProps={{ startAdornment: <InputAdornment position="start"><SearchRoundedIcon fontSize="small" /></InputAdornment> }} />
        {showServiceFilter(services, service) ? <ServiceFilterField options={services} value={service} total={otherFiltersMatch.length} onChange={setService} /> : null}
        <TextField select size="small" value={severity} onChange={(event) => setSeverity(event.target.value)} sx={{ minWidth: 150, bgcolor: 'var(--os-surface)' }} inputProps={{ 'aria-label': 'Severity' }}>
          <MenuItem value="all">All Severity</MenuItem>
          {['critical', 'high', 'medium', 'low', 'significant', 'normal'].map((value) => <MenuItem key={value} value={value}>{titleCase(value)}</MenuItem>)}
        </TextField>
        <TextField select size="small" value={origin} onChange={(event) => setOrigin(event.target.value as typeof origin)} sx={{ minWidth: 150, bgcolor: 'var(--os-surface)' }} inputProps={{ 'aria-label': 'Case origin' }}>
          <MenuItem value="all">Detected and imported</MenuItem>
          <MenuItem value="detected">Detected only</MenuItem>
          <MenuItem value="imported">Imported only</MenuItem>
        </TextField>
      </Stack>
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, xl: 9 }}>
          <WorkspacePanel sx={{ overflowX: 'auto' }}>
            <Table>
              <TableHead>
                <TableRow sx={{ '& th': { color: ui.muted, fontWeight: 800, borderColor: ui.border } }}>
                  <TableCell sx={{ whiteSpace: 'nowrap' }}>Case ID</TableCell>
                  <TableCell>Title</TableCell>
                  <TableCell>Severity</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Created</TableCell>
                  <TableCell>Updated</TableCell>
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
                        '& td': { py: 2, borderColor: 'var(--os-surface-alt)' },
                      }}
                    >
                      <TableCell sx={{ fontWeight: 850, whiteSpace: 'nowrap' }}>{item.caseId}</TableCell>
                      <TableCell>
                        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
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
                          <CaseOriginBadge source={item.source} sourceId={item.sourceId} sourceUrl={item.sourceUrl} />
                        </Stack>
                        <Typography sx={{ color: ui.muted, fontSize: 12.5, mt: 0.25 }}>{serviceAndMetric(item)}</Typography>
                      </TableCell>
                      <TableCell><Pill label={item.severity} tone="severity" /></TableCell>
                      <TableCell>
                        <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
                          <Pill label={item.workState} />
                          {item.rootCauseUnconfirmed ? <RootCauseUnconfirmedBadge /> : null}
                        </Stack>
                      </TableCell>
                      <TableCell>{formatDateTime(item.createdAt)}</TableCell>
                      <TableCell>{relativeTime(item.updatedAt)}</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
            {filtered.length === 0 ? <Typography sx={{ p: 3, color: ui.muted, textAlign: 'center' }}>No cases here.</Typography> : null}
            <Typography sx={{ p: 2.2, color: ui.muted, fontWeight: 650 }}>
              Showing {filtered.length} of {cases.length} cases
              {service ? (
                <>
                  {' · '}
                  <Button variant="text" size="small" onClick={() => setService(null)} sx={{ p: 0, minWidth: 0, textTransform: 'none', fontWeight: 800, verticalAlign: 'baseline' }}>
                    Show all services
                  </Button>
                </>
              ) : null}
            </Typography>
          </WorkspacePanel>
        </Grid>
        <Grid size={{ xs: 12, xl: 3 }}>
          <WorkspacePanel sx={{ p: 2.5 }}>
            {selected ? (
              <Stack component="aside" aria-label={`Case ${selected.caseId}`} spacing={2.2}>
                <Box>
                  <Typography sx={{ color: ui.muted, fontSize: 13, fontWeight: 800 }}>{selected.caseId}</Typography>
                  <Typography variant="h6" sx={{ fontWeight: 850, lineHeight: 1.3, mb: 1 }}>{selected.title}</Typography>
                  <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
                    <Pill label={selected.severity} tone="severity" />
                    <Pill label={selected.workState} />
                    {selected.rootCauseUnconfirmed ? <RootCauseUnconfirmedBadge /> : null}
                  </Stack>
                </Box>
                <Stack spacing={0.5}>
                  <DetailRow label="Service" value={selected.service} />
                  <DetailRow label="Metric" value={selected.metric} />
                </Stack>
                <Box><Typography sx={{ color: ui.muted, fontSize: 13, mb: 0.5 }}>Summary</Typography><Typography>{selected.summary}</Typography></Box>
                <Box><Typography sx={{ color: ui.muted, fontSize: 13, mb: 0.5 }}>Root Cause</Typography><Typography>{selected.rootCause ?? 'Not identified yet.'}</Typography></Box>
                {selected.resolution ? <Box><Typography sx={{ color: ui.muted, fontSize: 13, mb: 0.5 }}>Resolution</Typography><Typography>{selected.resolution}</Typography></Box> : null}
                <CaseTimeline item={selected} />
                <Button component={RouterLink} to={`/cases/${selected.id}`} endIcon={<ArrowForwardRoundedIcon />} variant="outlined" sx={{ borderColor: ui.border, color: 'var(--os-text-2)', textTransform: 'none', fontWeight: 850 }}>View Case Details</Button>
                <CaseTicketCard caseId={selected.id} />
              </Stack>
            ) : <Typography color="text.secondary">{cases.length ? 'Pick a case to see its details.' : 'No cases returned yet.'}</Typography>}
          </WorkspacePanel>
        </Grid>
      </Grid>
    </Stack>
  );
}

function serviceAndMetric(item: CaseRow) {
  return [item.service, item.metric].filter((value) => value && value !== 'n/a').join(' · ');
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <Stack direction="row" spacing={1.5}>
      <Typography sx={{ color: ui.muted, fontSize: 13, minWidth: 56 }}>{label}</Typography>
      <Typography sx={{ fontSize: 13, overflowWrap: 'anywhere' }}>{value}</Typography>
    </Stack>
  );
}

function CaseTimeline({ item }: { item: CaseRow }) {
  const events = [
    { when: item.createdAt, what: item.imported ? `Imported from ${titleCase(item.source)}` : 'Case created from finding', color: '#60a5fa' },
    ...item.notes.map((note) => ({ when: note.timestamp, what: note.note, color: ui.purple })),
    ...(item.resolvedAt ? [{ when: item.resolvedAt, what: item.rootCauseUnconfirmed ? 'Resolved, root cause not verified' : 'Resolved', color: '#22c55e' }] : []),
  ];
  return (
    <Box>
      <Typography sx={{ color: ui.muted, fontSize: 13, mb: 1 }}>Timeline</Typography>
      <Stack component="ol" spacing={1.5} sx={{ listStyle: 'none', m: 0, p: 0 }}>
        {events.map((event, index) => (
          <Stack component="li" key={`${event.when ?? 'note'}-${index}`} direction="row" spacing={1.5}>
            <Box sx={{ width: 10, height: 10, mt: 0.6, flex: '0 0 auto', borderRadius: '50%', bgcolor: event.color }} />
            <Box>
              <Typography sx={{ color: ui.muted, fontSize: 12 }}>{event.when ? formatDateTime(event.when) : 'No time recorded'}</Typography>
              <Typography sx={{ fontSize: 13.5, fontWeight: 700 }}>{event.what}</Typography>
            </Box>
          </Stack>
        ))}
      </Stack>
    </Box>
  );
}
