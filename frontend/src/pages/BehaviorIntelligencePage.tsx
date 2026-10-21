import { useState } from 'react';
import { Alert, Box, Button, Drawer, Grid2 as Grid, Stack, Tab, Table, TableBody, TableCell, TableHead, TableRow, Tabs, Tooltip, Typography } from '@mui/material';
import { Link as RouterLink, useNavigate, useSearchParams } from 'react-router-dom';
import AddRoundedIcon from '@mui/icons-material/AddRounded';
import WarningAmberRoundedIcon from '@mui/icons-material/WarningAmberRounded';
import AccountTreeRoundedIcon from '@mui/icons-material/AccountTreeRounded';
import DnsRoundedIcon from '@mui/icons-material/DnsRounded';
import VerifiedRoundedIcon from '@mui/icons-material/VerifiedRounded';
import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded';
import AutoAwesomeRoundedIcon from '@mui/icons-material/AutoAwesomeRounded';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/queries';
import { BehaviorBuilder, BLANK_SEED, seedFromDefinition, type BuilderSeed } from '../components/BehaviorBuilder';
import { ErrorState } from '../components/ErrorState';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { PatternMetrics, PatternWhy } from '../components/PatternEvidence';
import { useWebPermissions } from '../hooks/useWebPermissions';
import { IconTile, PageHeader, Pill, WorkspacePanel } from '../standalone/components';
import { formatDateTime, relativeTime, titleCase, ui } from '../standalone/theme';
import { buildBehaviorSummary, toBehaviorRows, type BehaviorRow } from '../standalone/behaviorService';
import type { BehaviorDefinition, BehaviorFinding, BehaviorPatternSuggestion } from '../types';
import { patternFindingsHref } from '../utils/combinedPatterns';

type PageTab = 'detected' | 'patterns';

function CreateCaseCell({ row }: { row: BehaviorRow }) {
  const navigate = useNavigate();
  const createCaseMutation = useMutation({
    mutationFn: (behaviorFindingId: number) => api.createCaseFromBehavior(behaviorFindingId),
    onSuccess: (data) => navigate(`/cases/${data.case_id}`),
  });

  if (row.caseId) {
    return (
      <Button component={RouterLink} to={`/cases/${row.caseId}`} size="small" onClick={(event) => event.stopPropagation()} sx={{ textTransform: 'none', fontWeight: 800 }}>
        View Case
      </Button>
    );
  }

  return (
    <Button
      size="small"
      variant="outlined"
      onClick={(event) => {
        event.stopPropagation();
        createCaseMutation.mutate(row.id);
      }}
      disabled={createCaseMutation.isPending}
      sx={{ textTransform: 'none', fontWeight: 800 }}
    >
      {createCaseMutation.isPending ? 'Creating…' : 'Create Case'}
    </Button>
  );
}

/** Which analyzers a rule listens to, across its inputs; an input that names none takes any. */
export function ruleNeeds(definition: BehaviorDefinition): string {
  const lists = definition.inputs.map((item) => (Array.isArray(item.analyzers) ? (item.analyzers as string[]) : []));
  if (lists.some((list) => list.length === 0)) return 'any analyzer';
  return [...new Set(lists.flat())].join(', ');
}

/** When each rule last matched, by definition id. */
export function lastFiredByRule(findings: BehaviorFinding[]): Map<string, string> {
  const last = new Map<string, string>();
  for (const finding of findings) {
    const current = last.get(finding.definition_id);
    if (!current || Date.parse(finding.last_seen_at) > Date.parse(current)) last.set(finding.definition_id, finding.last_seen_at);
  }
  return last;
}

function fileName(path?: string | null): string {
  return path ? path.split('/').pop() ?? path : 'unknown';
}

function DetectedTab({ findings, rows, ruleCount, onSeePatterns }: { findings: BehaviorFinding[]; rows: BehaviorRow[]; ruleCount: number; onSeePatterns: () => void }) {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const summary = buildBehaviorSummary(findings);
  const selected = findings.find((item) => item.id === selectedId) ?? findings[0];
  const viewHref = selected ? patternFindingsHref(selected) : null;

  return (
    <>
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}><MetricCard icon={<WarningAmberRoundedIcon />} label="Active Behaviors" value={summary.activeBehaviors} delta="seen in the last 24 hours" bg="var(--os-tint-rose)" color={ui.red} /></Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}><MetricCard icon={<AccountTreeRoundedIcon />} label="Metrics Combined" value={summary.metricsCombined} delta="distinct metrics" bg="var(--os-tint-green)" color={ui.green} /></Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}><MetricCard icon={<DnsRoundedIcon />} label="Affected Services" value={summary.affectedServices} delta="distinct services" bg="var(--os-tint-indigo)" color="#4f46e5" /></Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}><MetricCard icon={<VerifiedRoundedIcon />} label="Confidence Avg." value={summary.confidenceAverage == null ? 'No data' : `${summary.confidenceAverage}%`} delta="mean of the matches" bg="var(--os-tint-green)" color="#059669" /></Grid>
      </Grid>

      {rows.length ? (
        <WorkspacePanel sx={{ overflowX: 'auto' }}>
          <Table sx={{ minWidth: 900 }}>
            <TableHead><TableRow sx={{ '& th': { color: ui.muted, fontWeight: 850, borderColor: ui.border } }}><TableCell>Behavior</TableCell><TableCell>Pattern</TableCell><TableCell>Severity</TableCell><TableCell>Confidence</TableCell><TableCell>Impacted Services</TableCell><TableCell>Occurrences</TableCell><TableCell>Last Seen</TableCell><TableCell>Status</TableCell><TableCell align="right">Case</TableCell></TableRow></TableHead>
            <TableBody>
              {rows.map((row) => (
                <TableRow
                  key={row.id}
                  hover
                  selected={row.id === selected?.id}
                  onClick={() => setSelectedId(row.id)}
                  sx={{ cursor: 'pointer', '& td': { py: 2, borderColor: 'var(--os-surface-alt)' } }}
                >
                  <TableCell sx={{ fontWeight: 900 }}>
                    <Box component="button" type="button" onClick={() => setSelectedId(row.id)} aria-pressed={row.id === selected?.id} sx={{ all: 'unset', cursor: 'pointer', fontWeight: 900 }}>
                      {row.title}
                    </Box>
                  </TableCell>
                  <TableCell>{titleCase(row.pattern)}</TableCell>
                  <TableCell><Pill label={row.severity} tone="severity" /></TableCell>
                  <TableCell>{row.confidencePercent}%</TableCell>
                  <TableCell>{row.impactedServices}</TableCell>
                  <TableCell>{row.occurrenceCount}× since {formatDateTime(row.detectedAt)}</TableCell>
                  <TableCell>{relativeTime(row.lastSeenAt)}</TableCell>
                  <TableCell><Pill label={row.status} /></TableCell>
                  <TableCell align="right"><CreateCaseCell row={row} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </WorkspacePanel>
      ) : (
        <WorkspacePanel sx={{ p: 3 }}>
          <Typography sx={{ fontWeight: 900, fontSize: 18, mb: 0.75 }}>No behaviors detected yet</Typography>
          <Typography sx={{ color: ui.muted, mb: 2 }}>
            {ruleCount} {ruleCount === 1 ? 'pattern is' : 'patterns are'} active. A behavior appears here when every metric in one of them changes together on one service in an analysis run.
          </Typography>
          <Button variant="outlined" onClick={onSeePatterns} sx={{ textTransform: 'none', fontWeight: 800 }}>See the patterns</Button>
        </WorkspacePanel>
      )}

      {selected ? (
        <WorkspacePanel sx={{ p: 3, borderColor: 'var(--os-tint-violet-border)', bgcolor: 'var(--os-surface)' }}>
          <Grid container spacing={3}>
            <Grid size={{ xs: 12, lg: 7 }}>
              <Typography variant="h6" sx={{ fontWeight: 900, mb: 0.5 }}>{selected.title}</Typography>
              <Typography variant="caption" sx={{ color: ui.muted, fontWeight: 700, display: 'block', mb: 1 }}>
                {[selected.service, `rule ${selected.definition_id}`].filter(Boolean).join(' · ')}
              </Typography>
              <Typography sx={{ color: ui.muted, mb: 2 }}>{selected.ai_explanation ?? selected.summary}</Typography>
              <Typography sx={{ fontWeight: 850, mb: 1 }}>Metrics combined</Typography>
              <Box sx={{ mb: 1.5 }}><PatternMetrics behavior={selected} /></Box>
              <PatternWhy behavior={selected} />
            </Grid>
            <Grid size={{ xs: 12, lg: 5 }}>
              <Typography sx={{ fontWeight: 850, mb: 1 }}>Occurrences</Typography>
              <Typography>
                Seen {selected.occurrence_count} {selected.occurrence_count === 1 ? 'time' : 'times'} · first {formatDateTime(selected.created_at)} · last {relativeTime(selected.last_seen_at)}
              </Typography>
              <Typography sx={{ color: ui.muted, fontSize: 13, mt: 0.5 }}>
                Each run that sees it again adds to the count. A timeline of every occurrence is not stored yet.
              </Typography>
              <Box sx={{ mt: 3, display: 'flex', justifyContent: 'flex-end' }}>
                {viewHref ? (
                  <Button component={RouterLink} to={viewHref} endIcon={<ArrowForwardRoundedIcon />} variant="outlined" sx={{ borderColor: 'var(--os-tint-violet-border)', color: ui.purple, textTransform: 'none', fontWeight: 850 }}>
                    View on Findings
                  </Button>
                ) : (
                  <Tooltip title="Last seen more than 7 days ago, which is before the oldest Findings window." arrow>
                    <span>
                      <Button disabled endIcon={<ArrowForwardRoundedIcon />} variant="outlined" sx={{ textTransform: 'none', fontWeight: 850 }}>View on Findings</Button>
                    </span>
                  </Tooltip>
                )}
              </Box>
            </Grid>
          </Grid>
        </WorkspacePanel>
      ) : null}
    </>
  );
}

function ActiveRules({ definitions, findings, canAdmin, onEditCopy }: { definitions: BehaviorDefinition[]; findings: BehaviorFinding[]; canAdmin: boolean; onEditCopy: (id: string) => void }) {
  const lastFired = lastFiredByRule(findings);
  return (
    <Stack spacing={1.5} component="section" aria-labelledby="active-patterns-heading">
      <Box>
        <Typography id="active-patterns-heading" sx={{ fontWeight: 900, fontSize: 18 }}>Active in your setup ({definitions.length})</Typography>
        <Typography sx={{ color: ui.muted, fontSize: 13 }}>
          The patterns every analysis run checks. Needs lists the analyzers a pattern reads; it can only match when one of them ran on its metrics.
        </Typography>
      </Box>
      <WorkspacePanel sx={{ overflowX: 'auto' }}>
        <Table sx={{ minWidth: 820 }}>
          <TableHead><TableRow sx={{ '& th': { color: ui.muted, fontWeight: 850, borderColor: ui.border } }}><TableCell>Pattern</TableCell><TableCell>Needs</TableCell><TableCell>Last fired</TableCell><TableCell>Pack</TableCell><TableCell>Status</TableCell><TableCell align="right"><Box component="span" sx={{ position: 'absolute', width: '1px', height: '1px', overflow: 'hidden', clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap' }}>Actions</Box></TableCell></TableRow></TableHead>
          <TableBody>
            {definitions.map((definition) => {
              const fired = lastFired.get(definition.id);
              return (
                <TableRow key={definition.id}>
                  <TableCell>
                    <Typography sx={{ fontWeight: 900 }}>{definition.title}</Typography>
                    <Typography sx={{ color: ui.muted, fontSize: 13 }}>{definition.description}</Typography>
                  </TableCell>
                  <TableCell sx={{ fontFamily: 'monospace', fontSize: 12 }}>{ruleNeeds(definition)}</TableCell>
                  <TableCell>{fired ? relativeTime(fired) : 'Never'}</TableCell>
                  <TableCell sx={{ fontFamily: 'monospace', fontSize: 12 }}>{fileName(definition.source_file)} · v{definition.version}</TableCell>
                  <TableCell><Pill label={definition.enabled ? 'active' : 'disabled'} /></TableCell>
                  <TableCell align="right">
                    {canAdmin ? (
                      <Button size="small" variant="outlined" onClick={() => onEditCopy(definition.id)} sx={{ textTransform: 'none', fontWeight: 800, whiteSpace: 'nowrap' }}>
                        Edit copy
                      </Button>
                    ) : null}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </WorkspacePanel>
    </Stack>
  );
}

function SuggestedPatterns({ canAdmin, onOpen }: { canAdmin: boolean; onOpen: (id: number) => void }) {
  const queryClient = useQueryClient();
  const suggestionsQuery = useQuery({ queryKey: ['behavior-suggestions'], queryFn: () => api.behaviorSuggestions() });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['behavior-suggestions'] });
  const mineMutation = useMutation({ mutationFn: api.mineBehaviorSuggestions, onSuccess: refresh });
  const promoteMutation = useMutation({ mutationFn: (id: number) => api.promoteBehaviorSuggestion(id), onSuccess: refresh });
  const dismissMutation = useMutation({ mutationFn: (id: number) => api.dismissBehaviorSuggestion(id), onSuccess: refresh });
  const suggestions = suggestionsQuery.data ?? [];

  return (
    <Stack spacing={1.5} component="section" aria-labelledby="suggested-patterns-heading">
      <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', md: 'center' }} spacing={1.5}>
        <Box>
          <Typography id="suggested-patterns-heading" sx={{ fontWeight: 900, fontSize: 18 }}>Suggested from your data</Typography>
          <Typography sx={{ color: ui.muted, fontSize: 13 }}>
            Mined from how often pairs of metrics show activity close together in time — a starting point to review, not a final answer.
          </Typography>
        </Box>
        {canAdmin ? (
          <Button startIcon={<AutoAwesomeRoundedIcon />} variant="contained" onClick={() => mineMutation.mutate()} disabled={mineMutation.isPending} sx={{ bgcolor: ui.purple, textTransform: 'none', fontWeight: 850, flexShrink: 0 }}>
            {mineMutation.isPending ? 'Mining…' : 'Mine Suggestions'}
          </Button>
        ) : null}
      </Stack>

      {suggestions.length === 0 ? (
        <WorkspacePanel sx={{ p: 2.5 }}>
          <Typography color="text.secondary">
            {suggestionsQuery.isError ? 'Suggestions could not be loaded.' : canAdmin ? 'No pending suggestions. Mine Suggestions scans recent signal history for metric pairs worth turning into a pattern.' : 'No pending suggestions.'}
          </Typography>
        </WorkspacePanel>
      ) : (
        suggestions.map((suggestion: BehaviorPatternSuggestion) => (
          <WorkspacePanel key={suggestion.id} sx={{ p: 2.5 }}>
            <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={2}>
              <Box sx={{ minWidth: 0 }}>
                <Typography sx={{ fontWeight: 900, overflowWrap: 'anywhere' }}>
                  {suggestion.metric_a} + {suggestion.metric_b}
                  {suggestion.service ? ` on ${suggestion.service}` : ''}
                </Typography>
                <Typography sx={{ color: ui.muted, fontSize: 13, mt: 0.5 }}>
                  Co-occurred {suggestion.co_occurrence_count} of {Math.min(suggestion.metric_a_occasions, suggestion.metric_b_occasions)} times
                  ({Math.round(suggestion.correlation_strength * 100)}% correlation strength)
                </Typography>
              </Box>
              {canAdmin ? (
                <Stack direction="row" spacing={1} alignItems="flex-start" useFlexGap flexWrap="wrap">
                  <Button size="small" variant="contained" onClick={() => onOpen(suggestion.id)} sx={{ bgcolor: ui.blue, textTransform: 'none', fontWeight: 800 }}>
                    Turn into pattern
                  </Button>
                  <Tooltip title="Saves the suggested draft as it is to suggested_patterns.yml, without opening the builder." arrow>
                    <span>
                      <Button size="small" variant="outlined" onClick={() => promoteMutation.mutate(suggestion.id)} disabled={promoteMutation.isPending} sx={{ textTransform: 'none', fontWeight: 800 }}>
                        Save as is
                      </Button>
                    </span>
                  </Tooltip>
                  <Button size="small" onClick={() => dismissMutation.mutate(suggestion.id)} disabled={dismissMutation.isPending} sx={{ textTransform: 'none', fontWeight: 800 }}>
                    Dismiss
                  </Button>
                </Stack>
              ) : null}
            </Stack>
          </WorkspacePanel>
        ))
      )}
    </Stack>
  );
}

/** The builder's starting point for the `builder` URL value: new, rule:<id> or suggestion:<id>. */
function resolveBuilder(
  value: string,
  definitions: BehaviorDefinition[],
  suggestions: BehaviorPatternSuggestion[] | undefined,
): { seed: BuilderSeed; label: string } | null {
  if (value.startsWith('rule:')) {
    const definition = definitions.find((item) => item.id === value.slice('rule:'.length));
    return definition ? { seed: seedFromDefinition(definition, '_copy'), label: `Editing a copy of ${fileName(definition.source_file)} · saving never changes the original` } : null;
  }
  if (value.startsWith('suggestion:')) {
    if (!suggestions) return null;
    const suggestion = suggestions.find((item) => String(item.id) === value.slice('suggestion:'.length));
    return suggestion ? { seed: seedFromDefinition(suggestion.draft_definition_json), label: `From a suggestion${suggestion.service ? ` on ${suggestion.service}` : ''}` } : null;
  }
  return { seed: BLANK_SEED, label: 'New pattern' };
}

export function BehaviorIntelligencePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { canAdmin } = useWebPermissions();
  const tab: PageTab = searchParams.get('tab') === 'patterns' ? 'patterns' : 'detected';
  const builder = searchParams.get('builder');
  const definitionsQuery = useQuery({ queryKey: ['behavior-definitions'], queryFn: api.behaviorDefinitions });
  const findingsQuery = useQuery({ queryKey: ['behavior-findings'], queryFn: () => api.behaviorFindings() });
  // Same query the Suggested section reads; here only to seed the builder from a suggestion link.
  const suggestionsQuery = useQuery({
    queryKey: ['behavior-suggestions'],
    queryFn: () => api.behaviorSuggestions(),
    enabled: Boolean(builder?.startsWith('suggestion:')),
  });

  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(patch)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    setSearchParams(next);
  };
  const openBuilder = (value: string) => update({ tab: 'patterns', builder: value });
  const closeBuilder = () => update({ builder: null });

  if (definitionsQuery.isLoading || findingsQuery.isLoading) return <LoadingSkeleton />;
  if (definitionsQuery.error || findingsQuery.error) return <ErrorState message="Failed to load behavior intelligence" onRetry={() => {
    void definitionsQuery.refetch();
    void findingsQuery.refetch();
  }} />;

  const definitions = definitionsQuery.data ?? [];
  const findings = findingsQuery.data ?? [];
  const rows = toBehaviorRows(findings);
  const resolved = builder && canAdmin ? resolveBuilder(builder, definitions, suggestionsQuery.data) : null;

  return (
    <Stack spacing={3}>
      <PageHeader
        title="Behavior Intelligence"
        subtitle="Problems that show up in several metrics at once: what has been detected, and the patterns that look for it."
        action={canAdmin ? (
          <Button onClick={() => openBuilder('new')} startIcon={<AddRoundedIcon />} variant="contained" sx={{ bgcolor: ui.blue, textTransform: 'none', fontWeight: 850 }}>
            New pattern
          </Button>
        ) : undefined}
      />
      <Tabs
        value={tab}
        onChange={(_, value: PageTab) => update({ tab: value === 'detected' ? null : value })}
        sx={{ '& .MuiTab-root': { textTransform: 'none', fontWeight: 850 }, '& .Mui-selected': { color: `${ui.purple} !important` }, '& .MuiTabs-indicator': { bgcolor: ui.purple, height: 3 } }}
      >
        <Tab value="detected" label={`Detected (${findings.length})`} />
        <Tab value="patterns" label={`Patterns (${definitions.length})`} />
      </Tabs>

      {tab === 'detected' ? (
        <DetectedTab findings={findings} rows={rows} ruleCount={definitions.filter((item) => item.enabled).length} onSeePatterns={() => update({ tab: 'patterns' })} />
      ) : (
        <Stack spacing={4}>
          {!canAdmin ? <Alert severity="info">You can see every pattern. Ask an Ops Signals admin to add or change one.</Alert> : null}
          <ActiveRules definitions={definitions} findings={findings} canAdmin={canAdmin} onEditCopy={(id) => openBuilder(`rule:${id}`)} />
          <SuggestedPatterns canAdmin={canAdmin} onOpen={(id) => openBuilder(`suggestion:${id}`)} />
        </Stack>
      )}

      <Drawer
        anchor="right"
        open={Boolean(resolved)}
        // A stray click beside the panel must not throw away a half-written pattern.
        onClose={(_event, reason) => { if (reason !== 'backdropClick') closeBuilder(); }}
        PaperProps={{ sx: { width: { xs: '100%', md: 'min(960px, 92vw)' }, p: { xs: 2, md: 3 }, bgcolor: 'var(--os-bg)' } }}
      >
        {resolved ? <BehaviorBuilder key={builder} seed={resolved.seed} sourceLabel={resolved.label} onClose={closeBuilder} /> : null}
      </Drawer>
    </Stack>
  );
}

function MetricCard({ icon, label, value, delta, bg, color }: { icon: React.ReactNode; label: string; value: string | number; delta: string; bg: string; color: string }) {
  return <WorkspacePanel sx={{ p: 2.5 }}><Stack direction="row" spacing={2} alignItems="center"><IconTile bg={bg} color={color}>{icon}</IconTile><Box><Typography sx={{ fontSize: 26, fontWeight: 900, lineHeight: 1 }}>{value}</Typography><Typography sx={{ fontWeight: 800 }}>{label}</Typography><Typography sx={{ mt: 1, color: ui.muted, fontSize: 13, fontWeight: 700 }}>{delta}</Typography></Box></Stack></WorkspacePanel>;
}
