import { Box, Button, Card, CardActions, CardContent, Chip, Stack, Tooltip, Typography } from '@mui/material';
import { findingSourceLabel } from '../utils/findingSource';
import { useNavigate } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { api } from '../api/queries';
import { useConnectionName } from '../api/useConnectionName';
import type { BehaviorFinding, Finding, FindingDetailsSection, MetricUsageItem, SeenBeforeResponse } from '../types';
import { breakdownScopeLabel, breakdownSentence, breakdownSpreadColor, findingBreakdown } from '../utils/findingBreakdown';
import { findingLevel, findingLevelHint } from '../utils/findingLevel';
import { problemTiming } from '../utils/findingProblem';
import { testedSentence, trustBadge } from '../utils/findingTrust';
import { CUSTOM_SETTINGS_LABEL, customSettings, customSettingsTooltip } from '../utils/customSettings';
import { FindingTrustPanel } from './FindingTrustPanel';
import { PlainBadge, PlainFindingSummary } from './PlainFindingSummary';
import { changeChipLabel, findingChanges, priorChange } from '../utils/findingChanges';
import { watchedByTag } from '../utils/metricUsage';
import { useWebPermissions, WEB_LOCK_REASONS } from '../hooks/useWebPermissions';
import { AiLabel } from '../demo/AiLabel';

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
  onViewDetails?: (finding: Finding, section?: FindingDetailsSection) => void;
  repeats?: FindingRepeats;
  /** Which dashboards and alerts read this finding's metric, from the latest metric usage check. */
  usage?: MetricUsageItem;
  /** Combined patterns (behavior rules) this finding is one of the metrics of. */
  partOf?: BehaviorFinding[];
  /** Past cases that look like this finding, for the Seen before column. */
  seenBefore?: SeenBeforeResponse;
};

function seenAt(value?: string): string {
  return value ? new Date(value).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : 'unknown';
}

export function FindingCard({ finding, onViewDetails, repeats, usage, partOf = [], seenBefore }: Props) {
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

  const breakdown = findingBreakdown(finding);
  const changes = findingChanges(finding);
  const changeChip = changeChipLabel(changes);
  const prior = priorChange(changes);
  const scope = breakdownScopeLabel(breakdown);
  const watchedBy = usage ? watchedByTag(usage) : null;
  // Trust replaces the importance-based level: importance didn't separate real problems from noise in tests.
  const badge = trustBadge(finding.trust);
  const custom = customSettings(finding);

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
            <Tooltip title={[badge.detail, testedSentence(finding.trust)].filter(Boolean).join(' ')} arrow>
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
              <AiLabel><Chip label="AI" size="small" variant="outlined" color="info" sx={{ height: 18, fontSize: '0.65rem', mt: 0.25 }} /></AiLabel>
            )}
            <Typography variant="body2" color="text.secondary">
              {finding.ai_summary ?? finding.summary}
            </Typography>
          </Stack>
        )}

        {partOf.map((behavior) => (
          <Tooltip key={behavior.id} title="This metric is one of several that matched a combined pattern together. Click to see the pattern." arrow>
            <Chip
              label={`Part of: ${behavior.title}`}
              size="small"
              color="success"
              variant="outlined"
              clickable
              onClick={() => document.getElementById(`combined-pattern-${behavior.id}`)?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })}
              sx={{ mb: 1, mr: 1 }}
            />
          </Tooltip>
        ))}
        {custom && (
          <Tooltip title={customSettingsTooltip(custom)} arrow>
            <Chip label={CUSTOM_SETTINGS_LABEL} size="small" variant="outlined" color="secondary" data-testid="finding-custom-settings" sx={{ mb: 1, mr: 1 }} />
          </Tooltip>
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

        {finding.trust ? (
          <FindingTrustPanel
            finding={finding}
            answerOnly={finding.trust.tier === 'context' && !finding.trust.moved}
            seenBefore={seenBefore}
            onSeePastCases={onViewDetails ? (section = 'seen-before') => onViewDetails(finding, section) : undefined}
          />
        ) : null}

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
