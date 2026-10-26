import { useEffect, useState } from 'react';
import { findingSourceLabel } from '../utils/findingSource';
import { Box, Button, Chip, FormControlLabel, Grid2 as Grid, InputAdornment, MenuItem, Stack, Switch, TextField, Tooltip as MuiTooltip, Typography } from '@mui/material';
import SearchRoundedIcon from '@mui/icons-material/SearchRounded';
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
import { ui } from '../standalone/theme';
import type { Finding, FindingDetailsSection } from '../types';
import { categoryDetail, categoryLabel, categoryShortDescription } from '../utils/findingCategories';
import { findingIdFromQuery, findingSortFromParam, findingSorts, groupRepeatedFindings, searchFindings } from '../utils/findingSearch';
import { needsAttention } from '../utils/findingTrust';
import { inWindow, partFindings, patternsByFinding, searchPatterns } from '../utils/combinedPatterns';
import { CombinedPatternCard } from '../components/CombinedPatternCard';
import { ServiceFilterField } from '../components/ServiceFilterField';
import { inService, serviceFilterLabel, serviceOptions, showServiceFilter } from '../utils/serviceFilter';

type FindingsWindow = '6h' | '24h' | '7d';

const categoryColors = ['#ff3b3f', '#ff8a1f', '#3b82f6', '#7c3aed', 'var(--os-muted)'];
const windows: Array<{ id: FindingsWindow; label: string }> = [
  { id: '6h', label: 'Last 6 hours' },
  { id: '24h', label: 'Last 24 hours' },
  { id: '7d', label: 'Last 7 days' },
];
const PAGE_SIZE = 20;

function windowFromParams(value: string | null): FindingsWindow {
  return value === '6h' || value === '7d' ? value : '24h';
}

export function FindingsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const window = windowFromParams(searchParams.get('window'));
  const findingsQuery = useQuery({ queryKey: ['findings', window], queryFn: () => api.findings(undefined, undefined, undefined, window) });
  const summaryQuery = useQuery({ queryKey: ['overview-summary', window], queryFn: () => api.overviewSummary(window) });
  // Findings only carry signal_ids, not the signals themselves - without this, every card's
  // "Evidence" section has nothing to match against and always shows 0 supporting signals,
  // regardless of how many signals the finding actually has.
  const runIds = (findingsQuery.data ?? [])
    .map((finding) => finding.analysis_run_id)
    .filter((id): id is string => Boolean(id));
  const signalsQuery = useQuery({
    queryKey: ['findings-signals', ...runIds],
    queryFn: () => api.signalsByRunIds(runIds),
    enabled: runIds.length > 0,
  });

  // Who watches each finding's metric (latest metric usage check); no tag when there is no check.
  const metricNames = [...new Set((findingsQuery.data ?? []).map((finding) => finding.metric_name).filter(Boolean))].sort();
  const usageQuery = useQuery({
    queryKey: ['metric-usage-lookup', ...metricNames],
    queryFn: () => api.metricUsageLookup(metricNames),
    enabled: metricNames.length > 0,
    retry: false,
  });

  // Combined patterns (behavior rules that matched several metrics together). Optional: if this
  // read fails, the page renders exactly as it would without it.
  const behaviorsQuery = useQuery({ queryKey: ['behavior-findings'], queryFn: () => api.behaviorFindings(), retry: false });

  const [selectedFinding, setSelectedFinding] = useState<Finding | null>(null);
  const [drawerSection, setDrawerSection] = useState<FindingDetailsSection | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  // Re-fetches this one finding on open so ai_summary (computed and cached lazily, on first
  // detail view, by the backend) has a chance to populate - the list endpoint above never
  // triggers that computation, so the list-provided finding always has ai_summary: null.
  const findingDetailQuery = useQuery({
    queryKey: ['finding-detail', selectedFinding?.id],
    queryFn: () => api.getFinding(selectedFinding!.id!),
    enabled: drawerOpen && Boolean(selectedFinding?.id),
  });

  // Deep link from elsewhere (e.g. an alert linked to this finding): /findings?finding=<id> opens
  // its drawer, whether or not it falls inside the selected time window.
  const linkedFindingParam = searchParams.get('finding');
  const linkedFindingId = linkedFindingParam && /^\d+$/.test(linkedFindingParam) ? Number(linkedFindingParam) : null;
  const linkedFindingQuery = useQuery({
    queryKey: ['finding-detail', linkedFindingId],
    queryFn: () => api.getFinding(linkedFindingId!),
    enabled: linkedFindingId !== null,
    retry: false,
  });
  useEffect(() => {
    if (linkedFindingQuery.data) {
      setSelectedFinding(linkedFindingQuery.data);
      setDrawerOpen(true);
    }
  }, [linkedFindingQuery.data]);

  // Link from Behavior Intelligence: /findings?pattern=<id> scrolls to that combined pattern's card.
  const linkedPatternParam = searchParams.get('pattern');
  const linkedPatternId = linkedPatternParam && /^\d+$/.test(linkedPatternParam) ? Number(linkedPatternParam) : null;
  useEffect(() => {
    if (linkedPatternId === null || findingsQuery.isLoading || summaryQuery.isLoading || !behaviorsQuery.data) return;
    document.getElementById(`combined-pattern-${linkedPatternId}`)?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
  }, [linkedPatternId, findingsQuery.isLoading, summaryQuery.isLoading, behaviorsQuery.data]);

  const handleCloseDrawer = () => {
    setDrawerOpen(false);
    if (searchParams.has('finding')) {
      const next = new URLSearchParams(searchParams);
      next.delete('finding');
      setSearchParams(next, { replace: true });
    }
  };

  const handleViewDetails = (finding: Finding, section?: FindingDetailsSection) => {
    setSelectedFinding(finding);
    setDrawerSection(section ?? null);
    setDrawerOpen(true);
  };

  // Search and sort live in the URL, so a filtered list can be shared and survives a reload.
  const searchQuery = searchParams.get('q') ?? '';
  const sort = findingSortFromParam(searchParams.get('sort'));
  // Repeated findings (same change on the same series, one per run) share a card unless ?group=off.
  const groupRepeats = searchParams.get('group') !== 'off';
  const setParam = (name: string, value: string | null) => {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(name, value);
    else next.delete(name);
    setSearchParams(next, { replace: true });
  };
  const [shown, setShown] = useState(PAGE_SIZE);
  const [contextShown, setContextShown] = useState(PAGE_SIZE);
  const [contextOpen, setContextOpen] = useState(false);
  useEffect(() => {
    setShown(PAGE_SIZE);
    setContextShown(PAGE_SIZE);
  }, [searchQuery, sort, groupRepeats, window, searchParams.get('cluster'), searchParams.get('source'), searchParams.get('service'), searchParams.get('only')]);
  const showRuns = (finding: Finding) => {
    const next = new URLSearchParams(searchParams);
    next.set('q', [finding.service, finding.metric_name, finding.cluster].filter(Boolean).join(' '));
    next.set('group', 'off');
    setSearchParams(next, { replace: true });
  };

  if (findingsQuery.isLoading || summaryQuery.isLoading) return <LoadingSkeleton />;

  const findings = findingsQuery.data ?? [];
  // Same service in several clusters (one Mimir/Thanos endpoint) gives one finding per cluster;
  // the filter only appears when there is more than one cluster to choose from.
  const clusters = [...new Set(findings.map((finding) => finding.cluster).filter((cluster): cluster is string => Boolean(cluster)))].sort();
  const clusterFilter = searchParams.get('cluster');
  const clusterFindings = clusterFilter ? findings.filter((finding) => finding.cluster === clusterFilter) : findings;
  // Same idea for sources (Prometheus, OTLP, CSV): the filter appears only when there is a choice.
  const sources = [...new Set(findings.map((finding) => finding.source).filter((source): source is string => Boolean(source)))].sort();
  const sourceFilter = searchParams.get('source');
  const sourceFindings = sourceFilter ? clusterFindings.filter((finding) => finding.source === sourceFilter) : clusterFindings;
  // Services can number in the hundreds, so this one is a searchable dropdown, not chips. Counts
  // follow the cluster and source filters, so each says what picking it will show.
  const serviceFilter = searchParams.get('service');
  const services = serviceOptions(sourceFindings, serviceFilter);
  const serviceFindings = inService(sourceFindings, serviceFilter);
  // ?only=patterns keeps the findings a behavior rule used in a combined pattern (the "Part of" ones).
  // Not ?pattern=, which is the deep link to one pattern's card.
  const patternLinks = patternsByFinding(behaviorsQuery.data ?? [], findings);
  const onlyPatterns = searchParams.get('only') === 'patterns';
  const kindFindings = onlyPatterns ? serviceFindings.filter((finding) => finding.id !== undefined && patternLinks.has(finding.id)) : serviceFindings;
  // Searching a pattern's name or rule id also finds the findings it was made from.
  const patternText = (finding: Finding) =>
    (finding.id !== undefined ? patternLinks.get(finding.id) ?? [] : []).map((behavior) => `${behavior.title} ${behavior.definition_id}`).join(' ');
  const visibleFindings = searchFindings(kindFindings, searchQuery, sort, patternText);
  const visibleGroups = groupRepeatedFindings(visibleFindings, groupRepeats);
  // Context findings (single-check spikes, patterns, forecasts) were no better than chance in tests:
  // they stay one click away instead of crowding the list that asks for attention.
  const attentionGroups = visibleGroups.filter((group) => needsAttention(group.finding));
  const contextGroups = visibleGroups.filter((group) => !needsAttention(group.finding));
  // A pattern has no cluster or source of its own: with any of these filters on, keep the patterns
  // made from a finding the filters kept.
  const filteredIds = new Set(serviceFindings.map((finding) => finding.id));
  const visiblePatterns = searchPatterns(
    (behaviorsQuery.data ?? []).filter((behavior) => inWindow(behavior, window)),
    searchQuery,
  ).filter((behavior) => !(clusterFilter || sourceFilter || serviceFilter) || partFindings(behavior, patternLinks, findings).some((finding) => filteredIds.has(finding.id)));
  const setClusterFilter = (cluster: string | null) => setParam('cluster', cluster);
  const setSourceFilter = (source: string | null) => setParam('source', source);
  const setServiceFilter = (service: string | null) => setParam('service', service);
  const setOnlyPatterns = (on: boolean) => setParam('only', on ? 'patterns' : null);
  // "#57" for a finding outside this window: offer to open it directly, as the deep link does.
  const searchedId = findingIdFromQuery(searchQuery);
  const searchedIdMissing = searchedId !== null && !visibleFindings.some((finding) => finding.id === searchedId);
  const summary = summaryQuery.data;
  const categoryCounts = (summary?.category_breakdown ?? []).map((item) => ({ key: item.category, name: categoryLabel(item.category), value: item.count }));
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
              onClick={() => setParam('window', item.id)}
              sx={{ textTransform: 'none', fontWeight: 800, bgcolor: item.id === window ? '#009688' : 'var(--os-surface)' }}
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
                <Typography sx={{ color: 'var(--os-text-2)', fontWeight: 750 }}>Active Findings</Typography>
              </Box>
            </Stack>
          </WorkspacePanel>
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <WorkspacePanel sx={{ p: 2.5 }}>
            <Stack direction="row" spacing={1.5} alignItems="center">
              <CategoryRoundedIcon sx={{ color: 'var(--os-ink-brand)' }} />
              <Box>
                <Typography sx={{ fontSize: 28, fontWeight: 900 }}>{findings.length}</Typography>
                <Typography sx={{ color: 'var(--os-text-2)', fontWeight: 750 }}>Findings In Window</Typography>
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
          <WorkspacePanel sx={{ p: 2.5, minHeight: 330 }}>
            <Typography sx={{ fontSize: 18, fontWeight: 900, mb: 1.5 }}>Top Finding Categories</Typography>
            {categoryCounts.length ? (
              <Stack direction="row" alignItems="center" spacing={2}>
                <Box sx={{ width: 190, height: 220 }}>
                  <ResponsiveContainer>
                    <PieChart>
                      <Pie data={categoryCounts} dataKey="value" innerRadius={55} outerRadius={88} stroke="var(--os-surface)">
                        {categoryCounts.map((entry, index) => <Cell key={entry.name} fill={categoryColors[index % categoryColors.length]} />)}
                      </Pie>
                      <Tooltip />
                    </PieChart>
                  </ResponsiveContainer>
                </Box>
                <Stack spacing={1.5} sx={{ flex: 1 }}>
                  {categoryCounts.slice(0, 6).map((item) => (
                    <MuiTooltip key={item.key} title={categoryDetail(item.key) ?? ''} arrow placement="left">
                      <Box>
                        <Stack direction="row" justifyContent="space-between">
                          <Typography sx={{ fontWeight: 750 }}>{item.name}</Typography>
                          <Typography sx={{ color: ui.muted }}>{item.value}</Typography>
                        </Stack>
                        {categoryShortDescription(item.key) && (
                          <Typography variant="caption" sx={{ color: ui.muted, display: 'block', lineHeight: 1.35 }}>
                            {categoryShortDescription(item.key)}
                          </Typography>
                        )}
                      </Box>
                    </MuiTooltip>
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
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ mb: 2 }}>
          <TextField
            size="small"
            value={searchQuery}
            onChange={(event) => setParam('q', event.target.value)}
            placeholder="Search by service, metric, cluster, pattern or #finding"
            inputProps={{ 'aria-label': 'Search findings' }}
            InputProps={{ startAdornment: <InputAdornment position="start"><SearchRoundedIcon fontSize="small" /></InputAdornment> }}
            sx={{ flex: 1, bgcolor: 'var(--os-surface)' }}
          />
          {showServiceFilter(services, serviceFilter) ? (
            <ServiceFilterField options={services} value={serviceFilter} total={sourceFindings.length} onChange={setServiceFilter} />
          ) : null}
          <TextField
            select
            size="small"
            label="Sort by"
            value={sort}
            onChange={(event) => setParam('sort', event.target.value === 'latest' ? null : event.target.value)}
            sx={{ minWidth: 220, bgcolor: 'var(--os-surface)' }}
          >
            {findingSorts.map((item) => <MenuItem key={item.id} value={item.id}>{item.label}</MenuItem>)}
          </TextField>
          <FormControlLabel
            control={<Switch checked={groupRepeats} onChange={(event) => setParam('group', event.target.checked ? null : 'off')} />}
            label="Group repeats"
            sx={{ whiteSpace: 'nowrap', mr: 0 }}
          />
        </Stack>
        {clusters.length > 1 ? (
          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" alignItems="center" sx={{ mb: 2 }} aria-label="Filter by cluster">
            <Typography variant="body2" sx={{ fontWeight: 750, color: ui.muted }}>Cluster</Typography>
            <Chip label="All clusters" color={clusterFilter ? 'default' : 'primary'} variant={clusterFilter ? 'outlined' : 'filled'} onClick={() => setClusterFilter(null)} />
            {clusters.map((cluster) => (
              <Chip
                key={cluster}
                label={cluster}
                color={clusterFilter === cluster ? 'primary' : 'default'}
                variant={clusterFilter === cluster ? 'filled' : 'outlined'}
                onClick={() => setClusterFilter(cluster)}
              />
            ))}
          </Stack>
        ) : null}
        {sources.length > 1 ? (
          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" alignItems="center" sx={{ mb: 2 }} aria-label="Filter by source">
            <Typography variant="body2" sx={{ fontWeight: 750, color: ui.muted }}>Source</Typography>
            <Chip label="All sources" color={sourceFilter ? 'default' : 'primary'} variant={sourceFilter ? 'outlined' : 'filled'} onClick={() => setSourceFilter(null)} />
            {sources.map((source) => (
              <Chip
                key={source}
                label={findingSourceLabel(source)}
                color={sourceFilter === source ? 'primary' : 'default'}
                variant={sourceFilter === source ? 'filled' : 'outlined'}
                onClick={() => setSourceFilter(source)}
              />
            ))}
          </Stack>
        ) : null}
        {patternLinks.size || onlyPatterns ? (
          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" alignItems="center" sx={{ mb: 2 }} aria-label="Filter by kind">
            <Typography variant="body2" sx={{ fontWeight: 750, color: ui.muted }}>Show</Typography>
            <Chip label="All findings" color={onlyPatterns ? 'default' : 'primary'} variant={onlyPatterns ? 'outlined' : 'filled'} onClick={() => setOnlyPatterns(false)} />
            <MuiTooltip title="Findings a Behavior Intelligence rule combined into a pattern (tagged “Part of”)">
              <Chip
                label="Behavior Intelligence"
                color={onlyPatterns ? 'primary' : 'default'}
                variant={onlyPatterns ? 'filled' : 'outlined'}
                onClick={() => setOnlyPatterns(true)}
              />
            </MuiTooltip>
          </Stack>
        ) : null}
        {linkedFindingQuery.isError ? (
          <Typography role="status" color="text.secondary" sx={{ mb: 1.5 }}>
            Finding #{linkedFindingId} could not be found.
          </Typography>
        ) : null}
        {visiblePatterns.length ? (
          <Stack spacing={1.5} sx={{ mb: 3 }}>
            <Box>
              <Typography sx={{ fontSize: 16, fontWeight: 900 }}>Combined patterns ({visiblePatterns.length})</Typography>
              <Typography variant="body2" sx={{ color: ui.muted }}>
                Several metrics on one service changed at the same time and matched a behavior rule. The single-metric findings below are tagged “Part of”.
              </Typography>
            </Box>
            <Grid container spacing={2}>
              {visiblePatterns.map((behavior) => (
                <Grid key={behavior.id} size={{ xs: 12, md: 6 }}>
                  <CombinedPatternCard behavior={behavior} parts={partFindings(behavior, patternLinks, findings)} onViewFinding={handleViewDetails} highlighted={behavior.id === linkedPatternId} />
                </Grid>
              ))}
            </Grid>
          </Stack>
        ) : null}
        {findingsQuery.error ? (
          <Typography color="error">Findings unavailable.</Typography>
        ) : visibleFindings.length ? (
          <Stack spacing={2}>
            <Typography variant="body2" sx={{ color: ui.muted }}>
              Showing {Math.min(shown, attentionGroups.length)} of {attentionGroups.length}
              {contextGroups.length ? ` · ${contextGroups.length} context only` : ''}
              {visibleGroups.length !== visibleFindings.length ? ` (${visibleFindings.length} findings, repeats grouped)` : ''}
              {visibleFindings.length !== findings.length ? ` · ${findings.length} in window` : ''}
              {serviceFilter ? (
                <>
                  {' · '}
                  <Button variant="text" size="small" onClick={() => setServiceFilter(null)} sx={{ p: 0, minWidth: 0, textTransform: 'none', fontWeight: 800, verticalAlign: 'baseline' }}>
                    Show all services
                  </Button>
                </>
              ) : null}
            </Typography>
            <Typography sx={{ fontSize: 16, fontWeight: 900 }}>Needs attention ({attentionGroups.length})</Typography>
            {attentionGroups.length ? (
              <TopFindingsList groups={attentionGroups.slice(0, shown)} onViewDetails={handleViewDetails} onShowRuns={showRuns} usageByMetric={usageQuery.data} patternsByFinding={patternLinks} />
            ) : (
              <Typography color="text.secondary">Nothing needs attention in this window.</Typography>
            )}
            {attentionGroups.length > shown ? (
              <Button variant="outlined" onClick={() => setShown((current) => current + PAGE_SIZE)} sx={{ alignSelf: 'center', textTransform: 'none', fontWeight: 800 }}>
                Show {Math.min(PAGE_SIZE, attentionGroups.length - shown)} more
              </Button>
            ) : null}
            {contextGroups.length ? (
              <Box>
                <Button
                  variant="text"
                  onClick={() => setContextOpen((open) => !open)}
                  aria-expanded={contextOpen}
                  sx={{ textTransform: 'none', fontWeight: 900, fontSize: 16, px: 0 }}
                >
                  {contextOpen ? '▾' : '▸'} Context only ({contextGroups.length})
                </Button>
                <Typography variant="body2" sx={{ color: ui.muted, mb: contextOpen ? 1.5 : 0 }}>
                  Not alerts: single unusual values, patterns and forecasts. In tests, findings like these were real about as often as a random alert. Useful when you are already investigating.
                </Typography>
                {contextOpen ? (
                  <Stack spacing={2}>
                    <TopFindingsList groups={contextGroups.slice(0, contextShown)} onViewDetails={handleViewDetails} onShowRuns={showRuns} usageByMetric={usageQuery.data} patternsByFinding={patternLinks} />
                    {contextGroups.length > contextShown ? (
                      <Button variant="outlined" onClick={() => setContextShown((current) => current + PAGE_SIZE)} sx={{ alignSelf: 'center', textTransform: 'none', fontWeight: 800 }}>
                        Show {Math.min(PAGE_SIZE, contextGroups.length - contextShown)} more
                      </Button>
                    ) : null}
                  </Stack>
                ) : null}
              </Box>
            ) : null}
          </Stack>
        ) : searchQuery ? (
          <Typography color="text.secondary">No findings in this window match "{searchQuery}".</Typography>
        ) : serviceFilter ? (
          <Stack spacing={1} alignItems="flex-start" role="status">
            <Typography sx={{ fontWeight: 800 }}>
              No findings for {serviceFilterLabel(serviceFilter)} in the {windows.find((item) => item.id === window)?.label.toLowerCase() ?? window}.
            </Typography>
            <Typography variant="body2" color="text.secondary">It may be quiet, or its findings are older.</Typography>
            <Stack direction="row" spacing={1}>
              {window !== '7d' ? <Button variant="outlined" size="small" onClick={() => setParam('window', '7d')} sx={{ textTransform: 'none', fontWeight: 800 }}>Last 7 days</Button> : null}
              <Button variant="outlined" size="small" onClick={() => setServiceFilter(null)} sx={{ textTransform: 'none', fontWeight: 800 }}>Show all services</Button>
            </Stack>
          </Stack>
        ) : onlyPatterns ? (
          <Typography color="text.secondary">No Behavior Intelligence findings in this window.</Typography>
        ) : (
          <Typography color="text.secondary">No findings returned for this window.</Typography>
        )}
        {searchedIdMissing ? (
          <Button variant="text" onClick={() => setParam('finding', String(searchedId))} sx={{ mt: 1, textTransform: 'none', fontWeight: 800 }}>
            Open finding #{searchedId}
          </Button>
        ) : null}
      </WorkspacePanel>

      <FindingDetailsDrawer
        open={drawerOpen}
        finding={findingDetailQuery.data ?? selectedFinding}
        signals={signalsQuery.data ?? []}
        section={drawerSection}
        onClose={handleCloseDrawer}
      />
    </Stack>
  );
}
