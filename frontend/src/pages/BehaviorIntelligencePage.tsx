import { useState } from 'react';
import { Box, Button, Grid2 as Grid, Stack, Tab, Table, TableBody, TableCell, TableHead, TableRow, Tabs, Typography } from '@mui/material';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import CalendarTodayRoundedIcon from '@mui/icons-material/CalendarTodayRounded';
import AddRoundedIcon from '@mui/icons-material/AddRounded';
import WarningAmberRoundedIcon from '@mui/icons-material/WarningAmberRounded';
import AccountTreeRoundedIcon from '@mui/icons-material/AccountTreeRounded';
import DnsRoundedIcon from '@mui/icons-material/DnsRounded';
import VerifiedRoundedIcon from '@mui/icons-material/VerifiedRounded';
import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded';
import AutoAwesomeRoundedIcon from '@mui/icons-material/AutoAwesomeRounded';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/queries';
import { ErrorState } from '../components/ErrorState';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { IconTile, PageHeader, Pill, WorkspacePanel } from '../standalone/components';
import { formatDateTime, relativeTime, titleCase, ui } from '../standalone/theme';
import { buildBehaviorSummary, toBehaviorRows, toBehaviorRuleRows, type BehaviorRow } from '../standalone/behaviorService';

function CreateCaseCell({ row }: { row: BehaviorRow }) {
  const navigate = useNavigate();
  const createCaseMutation = useMutation({
    mutationFn: (behaviorFindingId: number) => api.createCaseFromBehavior(behaviorFindingId),
    onSuccess: (data) => navigate(`/cases/${data.case_id}`),
  });

  if (row.caseId) {
    return (
      <Button component={RouterLink} to={`/cases/${row.caseId}`} size="small" sx={{ textTransform: 'none', fontWeight: 800 }}>
        View Case
      </Button>
    );
  }

  return (
    <Button
      size="small"
      variant="outlined"
      onClick={() => createCaseMutation.mutate(row.id)}
      disabled={createCaseMutation.isPending}
      sx={{ textTransform: 'none', fontWeight: 800 }}
    >
      {createCaseMutation.isPending ? 'Creating…' : 'Create Case'}
    </Button>
  );
}

function SuggestedPatternsTab() {
  const queryClient = useQueryClient();
  const suggestionsQuery = useQuery({ queryKey: ['behavior-suggestions'], queryFn: () => api.behaviorSuggestions() });
  const mineMutation = useMutation({
    mutationFn: api.mineBehaviorSuggestions,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['behavior-suggestions'] }),
  });
  const promoteMutation = useMutation({
    mutationFn: (id: number) => api.promoteBehaviorSuggestion(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['behavior-suggestions'] }),
  });
  const dismissMutation = useMutation({
    mutationFn: (id: number) => api.dismissBehaviorSuggestion(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['behavior-suggestions'] }),
  });
  const suggestions = suggestionsQuery.data ?? [];

  return (
    <Stack spacing={2}>
      <WorkspacePanel sx={{ p: 2.5 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center">
          <Box>
            <Typography sx={{ fontWeight: 900, fontSize: 18 }}>Suggested Patterns</Typography>
            <Typography sx={{ color: ui.muted }}>
              Mined from how often pairs of metrics show activity close together in time — a starting point to review, not a final answer.
            </Typography>
          </Box>
          <Button startIcon={<AutoAwesomeRoundedIcon />} variant="contained" onClick={() => mineMutation.mutate()} disabled={mineMutation.isPending} sx={{ bgcolor: ui.purple, textTransform: 'none', fontWeight: 850 }}>
            {mineMutation.isPending ? 'Mining…' : 'Mine Suggestions'}
          </Button>
        </Stack>
      </WorkspacePanel>

      {suggestions.length === 0 ? (
        <WorkspacePanel sx={{ p: 3 }}>
          <Typography color="text.secondary">
            No pending suggestions. Click "Mine Suggestions" to scan recent signal history for metric pairs worth turning into a pattern.
          </Typography>
        </WorkspacePanel>
      ) : (
        suggestions.map((suggestion) => (
          <WorkspacePanel key={suggestion.id} sx={{ p: 2.5 }}>
            <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={2}>
              <Box>
                <Typography sx={{ fontWeight: 900 }}>
                  {suggestion.metric_a} + {suggestion.metric_b}
                  {suggestion.service ? ` on ${suggestion.service}` : ''}
                </Typography>
                <Typography sx={{ color: ui.muted, fontSize: 13, mt: 0.5 }}>
                  Co-occurred {suggestion.co_occurrence_count} of {Math.min(suggestion.metric_a_occasions, suggestion.metric_b_occasions)} times
                  ({Math.round(suggestion.correlation_strength * 100)}% correlation strength)
                </Typography>
              </Box>
              <Stack direction="row" spacing={1} alignItems="flex-start">
                <Button size="small" variant="outlined" onClick={() => dismissMutation.mutate(suggestion.id)} disabled={dismissMutation.isPending} sx={{ textTransform: 'none', fontWeight: 800 }}>
                  Dismiss
                </Button>
                <Button size="small" variant="contained" onClick={() => promoteMutation.mutate(suggestion.id)} disabled={promoteMutation.isPending} sx={{ bgcolor: ui.blue, textTransform: 'none', fontWeight: 800 }}>
                  Promote to Pack
                </Button>
              </Stack>
            </Stack>
          </WorkspacePanel>
        ))
      )}
    </Stack>
  );
}

export function BehaviorIntelligencePage() {
  const definitionsQuery = useQuery({ queryKey: ['behavior-definitions'], queryFn: api.behaviorDefinitions });
  const findingsQuery = useQuery({ queryKey: ['behavior-findings'], queryFn: () => api.behaviorFindings() });
  const [tab, setTab] = useState('detected');
  const behaviorRows = toBehaviorRows(findingsQuery.data ?? []);
  const ruleRows = toBehaviorRuleRows(definitionsQuery.data ?? []);
  const selected = behaviorRows[0];
  const summary = buildBehaviorSummary(findingsQuery.data ?? []);

  if (definitionsQuery.isLoading || findingsQuery.isLoading) return <LoadingSkeleton />;
  if (definitionsQuery.error || findingsQuery.error) return <ErrorState message="Failed to load behavior intelligence" onRetry={() => {
    void definitionsQuery.refetch();
    void findingsQuery.refetch();
  }} />;

  return (
    <Stack spacing={3}>
      <PageHeader
        title="Behavior Intelligence"
        subtitle="Detect patterns and behaviors across multiple signals and metrics"
        action={<Stack direction="row" spacing={1.5}><Button startIcon={<CalendarTodayRoundedIcon />} variant="outlined" disabled sx={{ bgcolor: '#fff', borderColor: ui.border, color: '#334155', textTransform: 'none', fontWeight: 750 }}>Time Window Unavailable</Button><Button component={RouterLink} to="/behavior-intelligence/lab" startIcon={<AddRoundedIcon />} variant="contained" sx={{ bgcolor: ui.blue, textTransform: 'none', fontWeight: 850 }}>Add Pattern</Button></Stack>}
      />
      <Tabs value={tab} onChange={(_, value) => setTab(value)} sx={{ '& .MuiTab-root': { textTransform: 'none', fontWeight: 850 }, '& .Mui-selected': { color: `${ui.purple} !important` }, '& .MuiTabs-indicator': { bgcolor: ui.purple, height: 3 } }}>
        <Tab value="detected" label="Detected Behaviors" />
        <Tab value="rules" label="Rules" />
        <Tab value="library" label="Patterns Library" />
        <Tab value="suggested" label="Suggested Patterns" />
      </Tabs>

      {tab === 'detected' ? (
        <>
          <Grid container spacing={2}>
            <Grid size={{ xs: 12, sm: 6, lg: 3 }}><MetricCard icon={<WarningAmberRoundedIcon />} label="Active Behaviors" value={summary.activeBehaviors} delta="returned evaluations" bg="#fff1f2" color={ui.red} /></Grid>
            <Grid size={{ xs: 12, sm: 6, lg: 3 }}><MetricCard icon={<AccountTreeRoundedIcon />} label="Total Signals" value={summary.totalSignals} delta="evidence fields" bg="#f0fdf4" color={ui.green} /></Grid>
            <Grid size={{ xs: 12, sm: 6, lg: 3 }}><MetricCard icon={<DnsRoundedIcon />} label="Affected Services" value={summary.affectedServices} delta="distinct services" bg="#eef2ff" color="#4f46e5" /></Grid>
            <Grid size={{ xs: 12, sm: 6, lg: 3 }}><MetricCard icon={<VerifiedRoundedIcon />} label="Confidence Avg." value={summary.confidenceAverage == null ? 'No data' : `${summary.confidenceAverage}%`} delta="mean of returned evaluations" bg="#ecfdf5" color="#059669" /></Grid>
          </Grid>
          <WorkspacePanel sx={{ overflow: 'hidden' }}>
            <Table>
              <TableHead><TableRow sx={{ '& th': { color: ui.muted, fontWeight: 850, borderColor: ui.border } }}><TableCell>Behavior</TableCell><TableCell>Pattern</TableCell><TableCell>Severity</TableCell><TableCell>Confidence</TableCell><TableCell>Impacted Services</TableCell><TableCell>Occurrences</TableCell><TableCell>Last Seen</TableCell><TableCell>Status</TableCell><TableCell align="right">Case</TableCell></TableRow></TableHead>
              <TableBody>
                {behaviorRows.map((finding) => (
                  <TableRow key={finding.id} hover sx={{ '& td': { py: 2, borderColor: '#f1f5f9' } }}>
                    <TableCell sx={{ fontWeight: 900 }}>{finding.title}</TableCell>
                    <TableCell>{titleCase(finding.pattern)}</TableCell>
                    <TableCell><Pill label={finding.severity} tone="severity" /></TableCell>
                    <TableCell>{finding.confidencePercent}%</TableCell>
                    <TableCell>{finding.impactedServices}</TableCell>
                    <TableCell>{finding.occurrenceCount}× since {formatDateTime(finding.detectedAt)}</TableCell>
                    <TableCell>{relativeTime(finding.lastSeenAt)}</TableCell>
                    <TableCell><Pill label={finding.status} /></TableCell>
                    <TableCell align="right"><CreateCaseCell row={finding} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {!behaviorRows.length ? <Typography sx={{ p: 2.5, color: ui.muted }}>No behavior evaluations found yet.</Typography> : null}
          </WorkspacePanel>
          <WorkspacePanel sx={{ p: 3, borderColor: '#ddd6fe', bgcolor: '#fff' }}>
            {selected ? (
              <Grid container spacing={3}>
                <Grid size={{ xs: 12, lg: 6 }}>
                  <Typography variant="h6" sx={{ fontWeight: 900, mb: 1 }}>{selected.title}</Typography>
                  <Typography sx={{ color: ui.muted, mb: 3 }}>{selected.summary}</Typography>
                  <Typography sx={{ fontWeight: 850, mb: 1.5 }}>Contributing Signals ({selected.evidence.length})</Typography>
                  <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
                    {selected.evidence.map((item) => <Box key={item} sx={{ px: 1.4, py: 0.7, borderRadius: '8px', bgcolor: '#f3f0ff', color: ui.purple, fontWeight: 800, fontSize: 13 }}>{titleCase(item.split('.').pop())}</Box>)}
                  </Stack>
                </Grid>
                <Grid size={{ xs: 12, lg: 6 }}>
                  <Typography sx={{ fontWeight: 850, mb: 1.5 }}>Recent Occurrences</Typography>
                  <Box sx={{ minHeight: 96, display: 'grid', placeItems: 'center', textAlign: 'center', borderRadius: '8px', bgcolor: '#f8fafc', border: `1px dashed ${ui.border}`, px: 2 }}>
                    <Box>
                      <Typography sx={{ fontWeight: 900 }}>Occurrence history is not available yet.</Typography>
                      <Typography sx={{ color: ui.muted, mt: 0.75 }}>The current behavior API returns detected evaluations, not a time-bucketed occurrence series.</Typography>
                    </Box>
                  </Box>
                  <Button endIcon={<ArrowForwardRoundedIcon />} variant="outlined" sx={{ mt: 3, float: 'right', borderColor: '#ddd6fe', color: ui.purple, textTransform: 'none', fontWeight: 850 }}>View Details</Button>
                </Grid>
              </Grid>
            ) : <Typography color="text.secondary">Select a detected behavior after evaluations are available.</Typography>}
          </WorkspacePanel>
        </>
      ) : null}

      {tab === 'rules' ? (
        <WorkspacePanel sx={{ overflow: 'hidden' }}>
          <Table>
            <TableHead><TableRow sx={{ '& th': { color: ui.muted, fontWeight: 850, borderColor: ui.border } }}><TableCell>Rule</TableCell><TableCell>Description</TableCell><TableCell>Version</TableCell><TableCell>Source</TableCell><TableCell>Status</TableCell></TableRow></TableHead>
            <TableBody>
              {ruleRows.map((definition) => <TableRow key={definition.id}><TableCell sx={{ fontWeight: 900 }}>{definition.title}</TableCell><TableCell>{definition.description}</TableCell><TableCell>{definition.version}</TableCell><TableCell>{definition.sourceFile}</TableCell><TableCell><Pill label={definition.status} /></TableCell></TableRow>)}
            </TableBody>
          </Table>
        </WorkspacePanel>
      ) : null}

      {tab === 'library' ? (
        <Grid container spacing={2}>
          {ruleRows.map((definition) => <Grid key={definition.id} size={{ xs: 12, md: 6, lg: 4 }}><WorkspacePanel sx={{ p: 2.5, minHeight: 170 }}><Typography sx={{ fontWeight: 900, mb: 1 }}>{definition.title}</Typography><Typography sx={{ color: ui.muted }}>{definition.description}</Typography><Stack direction="row" spacing={1} sx={{ mt: 1 }}><Pill label={definition.status} /><Pill label={definition.sourceFile} /></Stack></WorkspacePanel></Grid>)}
        </Grid>
      ) : null}

      {tab === 'suggested' ? <SuggestedPatternsTab /> : null}
    </Stack>
  );
}

function MetricCard({ icon, label, value, delta, bg, color }: { icon: React.ReactNode; label: string; value: string | number; delta: string; bg: string; color: string }) {
  return <WorkspacePanel sx={{ p: 2.5 }}><Stack direction="row" spacing={2} alignItems="center"><IconTile bg={bg} color={color}>{icon}</IconTile><Box><Typography sx={{ fontSize: 26, fontWeight: 900, lineHeight: 1 }}>{value}</Typography><Typography sx={{ fontWeight: 800 }}>{label}</Typography><Typography sx={{ mt: 1, color: ui.green, fontSize: 13, fontWeight: 800 }}>↑ {delta}</Typography></Box></Stack></WorkspacePanel>;
}
