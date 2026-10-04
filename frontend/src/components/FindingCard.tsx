import { Button, Card, CardActions, CardContent, Chip, Stack, Tooltip, Typography } from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { api } from '../api/queries';
import type { Finding, Signal } from '../types';
import { breakdownScopeLabel, breakdownSentence, breakdownSpreadColor, findingBreakdown } from '../utils/findingBreakdown';
import { categoryDetail, categoryLabel } from '../utils/findingCategories';
import { changeChipLabel, findingChanges, priorChange } from '../utils/findingChanges';
import { groupSignalsByAnalyzer, signalGroupChipLabel, signalGroupTooltip, supportingSignals } from '../utils/signalGroups';

type Props = {
  finding: Finding;
  onViewDetails?: (finding: Finding) => void;
  signals?: Signal[];
};

export function FindingCard({ finding, onViewDetails, signals = [] }: Props) {
  const navigate = useNavigate();
  const createCaseMutation = useMutation({
    mutationFn: (findingId: number) => api.createCase(findingId),
    onSuccess: (data) => {
      navigate(`/cases/${data.case_id}`);
    },
  });

  const getHealthColor = (status?: string): 'error' | 'warning' | 'success' | 'default' => {
    switch (status?.toLowerCase()) {
      case 'critical':
        return 'error';
      case 'significant':
        return 'warning';
      case 'normal':
        return 'success';
      default:
        return 'default';
    }
  };

  const getHealthLabel = (status?: string): string => {
    return status ? status.charAt(0).toUpperCase() + status.slice(1) : 'Unknown';
  };

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
              {[finding.service, finding.metric_name, finding.cluster].filter(Boolean).join(' · ')}
            </Typography>
          </Stack>
          <Chip 
            label={getHealthLabel(finding.health_status)} 
            color={getHealthColor(finding.health_status)}
            size="small"
            sx={{ flexShrink: 0 }}
          />
        </Stack>
        
        <Stack direction="row" spacing={0.75} alignItems="flex-start" sx={{ mb: 2 }}>
          {finding.ai_summary && (
            <Chip label="AI" size="small" variant="outlined" color="info" sx={{ height: 18, fontSize: '0.65rem', mt: 0.25 }} />
          )}
          <Typography variant="body2" color="text.secondary">
            {finding.ai_summary ?? finding.summary}
          </Typography>
        </Stack>

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
        <Button 
          size="small" 
          variant="outlined"
          onClick={handleCreateCase}
          disabled={createCaseMutation.isPending}
        >
          {createCaseMutation.isPending ? 'Creating...' : 'Create Case'}
        </Button>
      </CardActions>
    </Card>
  );
}
