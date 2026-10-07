import { Button, Card, CardActions, CardContent, Chip, Stack, Tooltip, Typography } from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { api } from '../api/queries';
import { useConnectionName } from '../api/useConnectionName';
import type { Finding, Signal } from '../types';
import { breakdownScopeLabel, breakdownSentence, breakdownSpreadColor, findingBreakdown } from '../utils/findingBreakdown';
import { categoryDetail, categoryLabel } from '../utils/findingCategories';
import { findingLevel, findingLevelHint } from '../utils/findingLevel';
import { changeChipLabel, findingChanges, priorChange } from '../utils/findingChanges';
import { groupSignalsByAnalyzer, signalGroupChipLabel, signalGroupTooltip, supportingSignals } from '../utils/signalGroups';

/** The same finding seen in several runs; the card shows one of them. */
export type FindingRepeats = {
  count: number;
  firstSeen?: string;
  lastSeen?: string;
  onShowAll?: () => void;
};

type Props = {
  finding: Finding;
  onViewDetails?: (finding: Finding) => void;
  signals?: Signal[];
  repeats?: FindingRepeats;
};

function seenAt(value?: string): string {
  return value ? new Date(value).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : 'unknown';
}

export function FindingCard({ finding, onViewDetails, signals = [], repeats }: Props) {
  const navigate = useNavigate();
  const connectionName = useConnectionName(finding.connection_id);
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

  return (
    <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <CardContent sx={{ flexGrow: 1 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start" sx={{ mb: 1 }}>
          <Stack sx={{ pr: 1, minWidth: 0 }}>
            <Typography variant="h6">{finding.title}</Typography>
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
              {[finding.service, finding.metric_name, finding.cluster, connectionName].filter(Boolean).join(' · ')}
            </Typography>
          </Stack>
          <Tooltip title={findingLevelHint(finding.health_status)} arrow>
            <Chip
              label={findingLevel(finding.health_status).label}
              color={findingLevel(finding.health_status).chip}
              size="small"
              sx={{ flexShrink: 0 }}
            />
          </Tooltip>
        </Stack>
        
        <Stack direction="row" spacing={0.75} alignItems="flex-start" sx={{ mb: 2 }}>
          {finding.ai_summary && (
            <Chip label="AI" size="small" variant="outlined" color="info" sx={{ height: 18, fontSize: '0.65rem', mt: 0.25 }} />
          )}
          <Typography variant="body2" color="text.secondary">
            {finding.ai_summary ?? finding.summary}
          </Typography>
        </Stack>

        {repeats && repeats.count > 1 && (
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
              disabled={createCaseMutation.isPending}
            >
              {createCaseMutation.isPending ? 'Creating...' : 'Create Case'}
            </Button>
          </span>
        </Tooltip>
      </CardActions>
    </Card>
  );
}
