import { Box, Button, Card, CardActions, CardContent, Chip, Stack, Tooltip, Typography } from '@mui/material';
import { findingSourceLabel } from '../utils/findingSource';
import { useNavigate } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { api } from '../api/queries';
import { useConnectionName } from '../api/useConnectionName';
import type { Finding, MetricUsageItem, Signal } from '../types';
import { breakdownScopeLabel, breakdownSentence, breakdownSpreadColor, findingBreakdown } from '../utils/findingBreakdown';
import { categoryDetail, categoryLabel } from '../utils/findingCategories';
import { findingLevel, findingLevelHint } from '../utils/findingLevel';
import { problemTiming } from '../utils/findingProblem';
import { trustBadge } from '../utils/findingTrust';
import { FindingTrustPanel } from './FindingTrustPanel';
import { PlainBadge, PlainFindingSummary } from './PlainFindingSummary';
import { changeChipLabel, findingChanges, priorChange } from '../utils/findingChanges';
import { watchedByTag } from '../utils/metricUsage';
import { groupSignalsByAnalyzer, signalGroupChipLabel, signalGroupTooltip, supportingSignals } from '../utils/signalGroups';
import { useWebPermissions, WEB_LOCK_REASONS } from '../hooks/useWebPermissions';

/** The same finding seen in several runs; the card shows one of them. */
export type FindingRepeats = {
  count: number;
  firstSeen?: string;
  lastSeen?: string;
  /** The most recent of them: it says whether the problem is still going on. */
  latest?: Finding;
  /** The earliest start any of them saw. */
  startedAt?: string;
  onShowAll?: () => void;
};

type Props = {
  finding: Finding;
  onViewDetails?: (finding: Finding) => void;
  signals?: Signal[];
  repeats?: FindingRepeats;
  /** Which dashboards and alerts read this finding's metric, from the latest metric usage check. */
  usage?: MetricUsageItem;
};

function seenAt(value?: string): string {
  return value ? new Date(value).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : 'unknown';
}

export function FindingCard({ finding, onViewDetails, signals = [], repeats, usage }: Props) {
  const { canEdit } = useWebPermissions();
  const navigate = useNavigate();
  const connectionName = useConnectionName(finding.connection_id);
  const timing = problemTiming(repeats?.latest ?? finding, repeats?.startedAt);
  // Prometheus is the usual source; say so only for the others, which can't drill down by pod.
  const sourceCaption = finding.source && finding.source !== 'prometheus' ? `via ${findingSourceLabel(finding.source)}` : null;
  const createCaseMutation = useMutation({
    mutationFn: (findingId: number) => api.createCase(findingId),
    onSuccess: (data) => {
      navigate(`/cases/${data.case_id}`);
    },
  });

  const handleCreateCase = () => {
    if (finding.id) {
      createCaseMutation.mutate(finding.id);
    }
  };

  const matchedSignals = supportingSignals(finding.signal_ids, signals);

  const signalGroups = groupSignalsByAnalyzer(matchedSignals);
  const breakdown = findingBreakdown(finding);
  const changes = findingChanges(finding);
  const changeChip = changeChipLabel(changes);
  const prior = priorChange(changes);
  const scope = breakdownScopeLabel(breakdown);
  const watchedBy = usage ? watchedByTag(usage) : null;
  // Trust replaces the importance-based level: importance didn't separate real problems from noise in tests.
  const badge = trustBadge(finding.trust);

  return (
    <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <CardContent sx={{ flexGrow: 1 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start" sx={{ mb: 1 }}>
          <Stack spacing={0.5} sx={{ pr: 1, minWidth: 0 }}>
            {finding.plain ? <PlainBadge plain={finding.plain} /> : null}
            <Typography variant="h6">{finding.plain?.headline ?? finding.title}</Typography>
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
              {[finding.service, finding.metric_name, finding.cluster, connectionName, sourceCaption].filter(Boolean).join(' · ')}
            </Typography>
          </Stack>
          {badge ? (
            <Tooltip title={badge.detail} arrow>
              <Chip label={badge.label} color={badge.color} size="small" variant={badge.color === 'default' ? 'outlined' : 'filled'} sx={{ flexShrink: 0 }} />
            </Tooltip>
          ) : (
            <Tooltip title={findingLevelHint(finding.health_status)} arrow>
              <Chip
                label={findingLevel(finding.health_status).label}
                color={findingLevel(finding.health_status).chip}
                size="small"
                sx={{ flexShrink: 0 }}
              />
            </Tooltip>
          )}
        </Stack>
        
        {finding.plain ? (
          <Box sx={{ mb: 2 }}>
            <PlainFindingSummary plain={finding.plain} summary={`${finding.title} ${finding.summary}`} />
          </Box>
        ) : (
          <Stack direction="row" spacing={0.75} alignItems="flex-start" sx={{ mb: 2 }}>
            {finding.ai_summary && (
              <Chip label="AI" size="small" variant="outlined" color="info" sx={{ height: 18, fontSize: '0.65rem', mt: 0.25 }} />
            )}
            <Typography variant="body2" color="text.secondary">
              {finding.ai_summary ?? finding.summary}
            </Typography>
          </Stack>
        )}

        {watchedBy && (
          <Tooltip title={<span style={{ whiteSpace: 'pre-line' }}>{watchedBy.detail}</span>} arrow>
            <Chip
              label={watchedBy.label}
              size="small"
              variant="outlined"
              color={watchedBy.watched ? 'success' : 'error'}
              data-testid="finding-watched-by"
              sx={{ mb: 1, mr: 1 }}
            />
          </Tooltip>
        )}
        {timing && (
          <Tooltip
            title={
              repeats && repeats.count > 1
                ? `Seen by ${repeats.count} runs: first ${seenAt(repeats.firstSeen)}, latest ${seenAt(repeats.lastSeen)}. Counted as one problem.${repeats.onShowAll ? ' Click to list each run.' : ''}`
                : 'When the problem happened, as of the latest analysis.'
            }
            arrow
          >
            <Chip
              label={timing.label}
              size="small"
              color={timing.ongoing ? 'warning' : 'default'}
              variant="outlined"
              onClick={repeats && repeats.count > 1 ? repeats.onShowAll : undefined}
              data-testid="finding-timing"
              sx={{ mb: 1, mr: 1 }}
            />
          </Tooltip>
        )}
        {!timing && repeats && repeats.count > 1 && (
          <Tooltip
            title={`The same finding on this series in ${repeats.count} runs: first ${seenAt(repeats.firstSeen)}, latest ${seenAt(repeats.lastSeen)}. This card shows #${finding.id ?? '?'}.${repeats.onShowAll ? ' Click to list each run.' : ''}`}
            arrow
          >
            <Chip
              label={`Seen in ${repeats.count} runs`}
              size="small"
              color="info"
              variant="outlined"
              onClick={repeats.onShowAll}
              sx={{ mb: 1, mr: 1 }}
            />
          </Tooltip>
        )}
        {scope && breakdown && (
          <Tooltip title={`${breakdownSentence(breakdown)} Click for the full breakdown.`} arrow>
            <Chip
              label={scope}
              color={breakdownSpreadColor(breakdown)}
              size="small"
              variant="outlined"
              onClick={onViewDetails ? () => onViewDetails(finding) : undefined}
              sx={{ mb: 1 }}
            />
          </Tooltip>
        )}
        {changeChip && prior && (
          <Tooltip title={`The change started ${Math.round(prior.minutes_before_anchor ?? 0)} min after this ${prior.event_type ?? 'change'}. Click for details.`} arrow>
            <Chip
              label={changeChip}
              size="small"
              variant="outlined"
              onClick={onViewDetails ? () => onViewDetails(finding) : undefined}
              sx={{ mb: 1, ml: scope && breakdown ? 1 : 0 }}
            />
          </Tooltip>
        )}

        {finding.trust ? <FindingTrustPanel finding={finding} answerOnly={finding.trust.tier === 'context' && !finding.trust.moved} /> : null}

        <Stack spacing={1} sx={{ mt: 2 }}>
          <Stack direction="row" justifyContent="space-between">
            <Typography variant="caption" color="text.secondary">Importance</Typography>
            <Typography variant="body2" sx={{ fontWeight: 700 }}>
              {finding.importance_score.toFixed(2)}
            </Typography>
          </Stack>
          
          <Stack direction="row" justifyContent="space-between">
            <Typography variant="caption" color="text.secondary">Category</Typography>
            <Tooltip title={categoryDetail(finding.category) ?? ''} arrow>
              <Typography variant="body2" sx={{ cursor: categoryDetail(finding.category) ? 'help' : undefined }}>
                {categoryLabel(finding.category)}
              </Typography>
            </Tooltip>
          </Stack>
          
          <Stack direction="row" justifyContent="space-between">
            <Typography variant="caption" color="text.secondary">Evidence</Typography>
            <Typography variant="body2">{matchedSignals.length} supporting signal{matchedSignals.length !== 1 ? 's' : ''}</Typography>
          </Stack>

          {matchedSignals.length > 0 ? (
            <Stack spacing={0.5}>
              <Typography variant="caption" color="text.secondary">Signals used</Typography>
              <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap' }}>
                {signalGroups.map((group) => (
                  <Tooltip key={group.key} title={<span style={{ whiteSpace: 'pre-line' }}>{signalGroupTooltip(group)}</span>} arrow>
                    <Chip
                      label={signalGroupChipLabel(group)}
                      size="small"
                      variant="outlined"
                    />
                  </Tooltip>
                ))}
              </Stack>
            </Stack>
          ) : null}
          
          <Stack>
            <Typography variant="caption" color="text.secondary">Metric</Typography>
            <Typography variant="body2">{finding.metric_name}</Typography>
          </Stack>
        </Stack>
      </CardContent>
      <CardActions sx={{ gap: 1 }}>
        <Button 
          size="small" 
          onClick={() => onViewDetails?.(finding)}
        >
          View Details
        </Button>
        {/* The span keeps the tooltip working while the button is disabled. */}
        <Tooltip title="Opens a case for this finding. From the case you can also create a Jira ticket.">
          <span>
            <Button
              size="small"
              variant="outlined"
              onClick={handleCreateCase}
              disabled={createCaseMutation.isPending || !canEdit}
              title={canEdit ? undefined : WEB_LOCK_REASONS.createCase}
            >
              {createCaseMutation.isPending ? 'Creating...' : 'Create Case'}
            </Button>
          </span>
        </Tooltip>
      </CardActions>
    </Card>
  );
}
