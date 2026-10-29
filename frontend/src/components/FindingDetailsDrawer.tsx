import { Alert, Box, Chip, CircularProgress, Drawer, List, ListItem, ListItemText, Stack, Tooltip, Typography } from '@mui/material';
import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Line, LineChart, ResponsiveContainer, Tooltip as RechartsTooltip, XAxis, YAxis } from 'recharts';
import { api } from '../api/queries';
import { useConnectionName } from '../api/useConnectionName';
import { LinkedAlerts } from './AlertComponents';
import { FindingBreakdown } from './FindingBreakdown';
import { FoundDeployTag } from './FoundDeployTag';
import { NoveltyBadge } from './NoveltyBadge';
import { SuggestedFixes } from './FixHistory';
import { FixCameBackBanner } from './FixCameBack';
import { PastCaseMatches } from './PastCaseMatches';
import type { Finding, FindingDetailsSection, Signal } from '../types';
import { breakdownScopeLabel, breakdownSpreadColor, findingBreakdown } from '../utils/findingBreakdown';
import { categoryDetail, categoryLabel } from '../utils/findingCategories';
import { breakdownMissingForSource, findingSourceLabel } from '../utils/findingSource';
import { findingLevel, findingLevelHint } from '../utils/findingLevel';
import { changeChipLabel, findingChanges, findingWhatChanged } from '../utils/findingChanges';
import { groupSignalsByAnalyzer, signalGroupChipLabel, signalGroupTooltip, supportingSignals } from '../utils/signalGroups';
import { PlainBadge, PlainFindingSummary } from './PlainFindingSummary';
import { testedCaption, testedHeadline, testedTooltip } from '../utils/findingTrust';
import { customSettings } from '../utils/customSettings';
import { useFindingAiWording } from '../hooks/useFindingAiWording';
import { CustomSettingsBox } from './CustomSettingsBox';

type Props = {
  open: boolean;
  finding: Finding | null;
  signals?: Signal[];
  /** Scrolls to this part once open, e.g. Seen before? when its chip on the card was clicked. */
  section?: FindingDetailsSection | null;
  onClose: () => void;
};

// Source badge shown next to the ingested-data chart - the answer to "where did this data come
// from, so I can backtrack if something looks wrong." One label/color per ingestion path this
// app supports; unrecognized providers fall back to their raw value rather than a wrong label.
const PROVIDER_LABELS: Record<string, string> = {
  otel: 'OTLP',
  prometheus: 'Prometheus',
  datadog: 'Datadog',
  csv: 'CSV',
  generic: 'CSV',
  custom: 'CSV',
};

const PROVIDER_COLORS: Record<string, string> = {
  otel: '#6d28d9',
  prometheus: '#e4581f',
  datadog: '#632ca6',
  csv: 'var(--os-ink-brand)',
  generic: 'var(--os-ink-brand)',
  custom: 'var(--os-ink-brand)',
};

function providerLabel(provider?: string | null): string {
  if (!provider) return 'Unknown source';
  return PROVIDER_LABELS[provider] ?? provider;
}

function providerColor(provider?: string | null): string {
  if (!provider) return 'var(--os-muted)';
  return PROVIDER_COLORS[provider] ?? 'var(--os-muted)';
}

export function FindingDetailsDrawer({ open, finding, signals = [], section = null, onClose }: Props) {
  useEffect(() => {
    if (!open || !section) return;
    // After the drawer has slid in and laid out its sections.
    const timer = window.setTimeout(() => document.getElementById(`finding-details-${section}`)?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }), 250);
    return () => window.clearTimeout(timer);
  }, [open, section, finding?.id]);

  const analysisRunId = finding?.analysis_run_id;

  const connectionName = useConnectionName(finding?.connection_id);
  const seenBeforeQuery = useQuery({
    queryKey: ['finding-seen-before', finding?.id],
    queryFn: () => api.findingSeenBefore(finding!.id as number),
    enabled: open && typeof finding?.id === 'number',
    retry: false,
  });

  const aiWording = useFindingAiWording(finding, open);

  const analysisRunQuery = useQuery({
    queryKey: ['finding-drawer-analysis-run', analysisRunId],
    queryFn: () => api.analysisRun(analysisRunId!),
    enabled: open && Boolean(analysisRunId),
  });

  // The page's signals only cover the findings in its list; a finding opened from a link (e.g. an
  // alert) can be outside it, so the drawer loads its own run's signals.
  const runSignalsQuery = useQuery({
    queryKey: ['finding-drawer-signals', analysisRunId],
    queryFn: () => api.signalsByRunIds([analysisRunId!]),
    enabled: open && Boolean(analysisRunId),
  });

  const timeseriesQuery = useQuery({
    queryKey: ['finding-drawer-timeseries', finding?.service, finding?.metric_name, analysisRunId, finding?.cluster],
    queryFn: () => api.timeseries(finding!.service!, finding!.metric_name, analysisRunId!, finding!.cluster),
    enabled: open && Boolean(finding?.service) && Boolean(analysisRunId),
  });

  if (!finding) return null;

  const matchedSignals = supportingSignals(finding.signal_ids, runSignalsQuery.data ?? signals);

  const signalGroups = groupSignalsByAnalyzer(matchedSignals);
  const breakdown = findingBreakdown(finding);
  const changes = findingChanges(finding);
  const changeChip = changeChipLabel(changes);
  const whatChanged = changes ? findingWhatChanged(changes) : null;
  const scope = breakdownScopeLabel(breakdown);
  // The breakdown has its own section above; the raw view shows the rest of the comparison.
  const { breakdown: _breakdown, ...comparison } = finding.comparison_json;

  return (
    <Drawer anchor="right" open={open} onClose={onClose}>
      <Box sx={{ width: { xs: '100vw', md: 560 }, p: 3, overflowY: 'auto' }}>
        {finding.plain ? <PlainBadge plain={finding.plain} /> : null}
        <Typography variant="h5" sx={{ mt: finding.plain ? 0.75 : 0 }}>{finding.plain?.headline ?? finding.title}</Typography>
        
        <Stack direction="row" spacing={1} sx={{ my: 2, flexWrap: 'wrap', gap: 1 }}>
          <Tooltip title={findingLevelHint(finding.health_status)} arrow>
            <Chip label={`${findingLevel(finding.health_status).label} importance`} color={findingLevel(finding.health_status).chip} />
          </Tooltip>
          <Tooltip title={categoryDetail(finding.category) ?? ''} arrow>
            <Chip label={`Category: ${categoryLabel(finding.category)}`} />
          </Tooltip>
          <Chip label={`Importance: ${finding.importance_score.toFixed(2)}`} />
          <Chip label={`Priority: P${finding.investigation_priority}`} variant="outlined" />
          {scope && <Chip label={scope} color={breakdownSpreadColor(breakdown)} />}
          {changeChip && <Chip label={changeChip} variant="outlined" />}
        </Stack>

        <LinkedAlerts findingId={finding.id} />

        <Box sx={{ mb: 3, p: 2, backgroundColor: 'var(--os-surface-alt)', borderRadius: 1 }} data-testid="finding-details-plain">
          {finding.plain ? (
            <PlainFindingSummary
              plain={finding.plain}
              summary={`${finding.title} ${finding.summary}`}
              ai={aiWording.ai}
              aiPending={aiWording.aiPending}
              showAiHint={aiWording.showAiHint}
            />
          ) : (
            <Stack direction="row" spacing={0.75} alignItems="flex-start">
              {finding.ai_summary && (
                <Chip label="AI" size="small" variant="outlined" color="info" sx={{ height: 18, fontSize: '0.65rem', mt: 0.25 }} />
              )}
              <Typography variant="body2">{finding.ai_summary ?? finding.summary}</Typography>
            </Stack>
          )}
        </Box>

        {seenBeforeQuery.data?.came_back && typeof finding.id === 'number' ? (
          <Box sx={{ mb: 3 }}>
            <FixCameBackBanner id="finding-details-came-back" cameBack={seenBeforeQuery.data.came_back} why={() => api.findingFixCameBackWhy(finding.id as number)} />
          </Box>
        ) : null}

        {customSettings(finding) ? <CustomSettingsBox custom={customSettings(finding)!} /> : null}

        {finding.trust ? (
          <Box sx={{ mb: 3 }} data-testid="finding-tested">
            <Typography variant="h6" sx={{ mb: 0.5 }}>In testing</Typography>
            <Typography sx={{ fontWeight: 800 }}>{testedHeadline(finding.trust)}</Typography>
            <Typography variant="body2" color="text.secondary">{testedCaption(finding.trust)}</Typography>
            {testedTooltip(finding.trust) ? (
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>{testedTooltip(finding.trust)}</Typography>
            ) : null}
          </Box>
        ) : null}

        {typeof finding.id === 'number' ? (
          <Box id="finding-details-seen-before" sx={{ mb: 3, scrollMarginTop: 16 }} data-testid="seen-before">
            <Typography variant="h6" sx={{ mb: 0.5 }}>Seen before?</Typography>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5 }}>
              Past cases that look like this finding, including incidents imported from postmortems. No case needed.
            </Typography>
            {seenBeforeQuery.isLoading ? <CircularProgress size={20} /> : null}
            {seenBeforeQuery.isError ? <Typography variant="body2" color="text.secondary">Past cases could not be searched.</Typography> : null}
            {seenBeforeQuery.data && !seenBeforeQuery.data.available ? (
              <Typography variant="body2" color="text.secondary">{seenBeforeQuery.data.reason}</Typography>
            ) : null}
            {seenBeforeQuery.data?.available ? <NoveltyBadge novelty={seenBeforeQuery.data.novelty} /> : null}
            {seenBeforeQuery.data?.available && seenBeforeQuery.data.matches.length ? <SuggestedFixes findingId={finding.id} /> : null}
            {seenBeforeQuery.data?.available ? (
              <PastCaseMatches
                matches={seenBeforeQuery.data.matches}
                service={finding.service}
                emptyText="Nothing like this in memory yet. Import past incidents from the Recurring problems page to give it history."
              />
            ) : null}
          </Box>
        ) : null}

        {breakdown && <FindingBreakdown breakdown={breakdown} changes={changes} />}
        {/* Data-quality findings are about the data, not the service, so never get a breakdown anyway. */}
        {!breakdown && finding.category !== 'data_quality' && breakdownMissingForSource(finding.source) ? (
          <Box data-testid="breakdown-source-note" sx={{ mb: 3, p: 1.5, border: 1, borderColor: 'divider', borderStyle: 'dashed', borderRadius: 1 }}>
            <Typography variant="caption" color="text.secondary">
              {breakdownMissingForSource(finding.source)}
            </Typography>
          </Box>
        ) : null}

        <List dense>
          <ListItem>
            <ListItemText primary="Metric" secondary={finding.metric_name} />
          </ListItem>
          {finding.service && (
            <ListItem>
              <ListItemText primary="Service" secondary={finding.service} />
            </ListItem>
          )}
          {finding.cluster && (
            <ListItem>
              <ListItemText primary="Cluster" secondary={finding.cluster} />
            </ListItem>
          )}
          {connectionName && (
            <ListItem>
              <ListItemText primary="Prometheus connection" secondary={connectionName} />
            </ListItem>
          )}
          {finding.source && (
            <ListItem>
              <ListItemText primary="Data source" secondary={findingSourceLabel(finding.source)} />
            </ListItem>
          )}
          {whatChanged && (
            <ListItem data-testid="finding-what-changed">
              <ListItemText
                primary="What changed"
                secondaryTypographyProps={{ component: 'div' }}
                secondary={
                  <Stack component="span" spacing={0.25} sx={{ mt: 0.5 }}>
                    {whatChanged.lines.map((line, index) => (
                      <Typography key={line} variant="body2" color="text.secondary">
                        {line}
                        {whatChanged.found?.[index] ? <FoundDeployTag hint={whatChanged.found[index]} /> : null}
                      </Typography>
                    ))}
                    {whatChanged.note && <Typography variant="caption" color="text.secondary">{whatChanged.note}</Typography>}
                  </Stack>
                }
              />
            </ListItem>
          )}
          <ListItem>
            <ListItemText 
              primary="Evidence (Supporting Signals)" 
              secondary={`${matchedSignals.length} supporting signal${matchedSignals.length !== 1 ? 's' : ''} detected`}
            />
          </ListItem>
          {finding.signal_ids.length > 0 && (
            <ListItem>
              <ListItemText 
                primary="Signals used"
                secondaryTypographyProps={{ component: 'div' }}
                secondary={
                  <Stack component="span" spacing={0.75} sx={{ mt: 1, flexWrap: 'wrap' }}>
                    {signalGroups.length > 0
                      ? signalGroups.map((group) => (
                          <Tooltip key={group.key} title={<span style={{ whiteSpace: 'pre-line' }}>{signalGroupTooltip(group)}</span>} arrow>
                            <Chip
                              label={signalGroupChipLabel(group)}
                              size="small"
                              variant="outlined"
                              sx={{ mr: 0.5, mb: 0.5 }}
                            />
                          </Tooltip>
                        ))
                      : <Typography variant="caption" color="text.secondary">No problem-signals matched.</Typography>}
                  </Stack>
                }
              />
            </ListItem>
          )}
        </List>

        {analysisRunId && (
          <>
            <Stack direction="row" alignItems="center" spacing={1.5} sx={{ mt: 3, mb: 1 }}>
              <Typography variant="h6">Ingested Data</Typography>
              {analysisRunQuery.data && (
                <Chip
                  size="small"
                  label={providerLabel(analysisRunQuery.data.provider)}
                  sx={{ bgcolor: providerColor(analysisRunQuery.data.provider), color: '#fff', fontWeight: 700 }}
                />
              )}
            </Stack>
            {analysisRunQuery.data && (
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5 }}>
                {analysisRunQuery.data.sample_count} points · {analysisRunQuery.data.status} · run {analysisRunId.slice(0, 8)}
              </Typography>
            )}

            {timeseriesQuery.isLoading && (
              <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
                <CircularProgress size={24} />
              </Box>
            )}
            {timeseriesQuery.isError && (
              <Typography variant="body2" color="error">
                Could not load the ingested data for this finding.
              </Typography>
            )}
            {timeseriesQuery.data && timeseriesQuery.data.length === 0 && (
              analysisRunQuery.data?.points_deleted ? (
                <Alert severity="info" variant="outlined">
                  The data behind this chart was deleted after {analysisRunQuery.data.points_retention_days} days, as set in
                  OPS_SIGNALS_POINT_RETENTION_DAYS. The finding and its numbers above are kept. Open a case for a finding to
                  keep its chart.
                </Alert>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  No raw points found for this analysis run.
                </Typography>
              )
            )}
            {timeseriesQuery.data && timeseriesQuery.data.length > 0 && (
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={timeseriesQuery.data}>
                  <XAxis
                    dataKey="timestamp"
                    tickFormatter={(value: string) => new Date(value).toLocaleString(undefined, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                    tickLine={false}
                    axisLine={false}
                    minTickGap={40}
                  />
                  <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={40} />
                  <RechartsTooltip labelFormatter={(value: string) => new Date(value).toLocaleString()} />
                  <Line type="monotone" dataKey="value" stroke="#4f46e5" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </>
        )}

        {Object.keys(comparison).length > 0 && (
          <>
            <Typography variant="h6" sx={{ mt: 3, mb: 2 }}>Comparison Analysis</Typography>
            <Box sx={{ backgroundColor: 'var(--os-surface-alt)', p: 2, borderRadius: 1, maxHeight: 300, overflowY: 'auto' }}>
              <Typography variant="caption" component="pre" sx={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap', fontSize: '0.75rem' }}>
                {JSON.stringify(comparison, null, 2)}
              </Typography>
            </Box>
          </>
        )}
      </Box>
    </Drawer>
  );
}
