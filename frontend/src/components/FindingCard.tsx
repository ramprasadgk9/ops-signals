import { Button, Card, CardActions, CardContent, Chip, Stack, Tooltip, Typography } from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { api } from '../api/queries';
import type { Finding, Signal } from '../types';

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

  const getCategoryLabel = (category?: string): string => {
    if (!category) return 'Insight';
    return category
      .split('_')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  };

  const handleCreateCase = () => {
    if (finding.id) {
      createCaseMutation.mutate(finding.id);
    }
  };

  const matchedSignals = finding.signal_ids
    .map((signalId) => signals.find((signal) => signal.id === signalId))
    .filter((signal): signal is Signal => Boolean(signal))
    .filter((signal) => signal.severity ? signal.severity.toLowerCase() !== 'low' : signal.importance_score >= 0.55);

  const signalTooltip = (signal: Signal) => {
    const evidenceKeys = Object.keys(signal.evidence ?? {});
    const evidenceSummary =
      evidenceKeys.length > 0
        ? evidenceKeys
            .slice(0, 3)
            .map((key) => `${key}: ${typeof signal.evidence[key] === 'object' ? JSON.stringify(signal.evidence[key]) : String(signal.evidence[key])}`)
            .join('\n')
        : 'No evidence details available.';
    return `${signal.analyzer_id ?? signal.signal_type}\n${signal.summary ?? 'No summary available.'}\n\nEvidence:\n${evidenceSummary}`;
  };

  return (
    <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <CardContent sx={{ flexGrow: 1 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start" sx={{ mb: 1 }}>
          <Typography variant="h6" sx={{ pr: 1 }}>{finding.title}</Typography>
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
        
        <Stack spacing={1} sx={{ mt: 2 }}>
          <Stack direction="row" justifyContent="space-between">
            <Typography variant="caption" color="text.secondary">Importance</Typography>
            <Typography variant="body2" sx={{ fontWeight: 700 }}>
              {finding.importance_score.toFixed(2)}
            </Typography>
          </Stack>
          
          <Stack direction="row" justifyContent="space-between">
            <Typography variant="caption" color="text.secondary">Category</Typography>
            <Typography variant="body2">{getCategoryLabel(finding.category)}</Typography>
          </Stack>
          
          <Stack direction="row" justifyContent="space-between">
            <Typography variant="caption" color="text.secondary">Evidence</Typography>
            <Typography variant="body2">{matchedSignals.length} supporting signal{matchedSignals.length !== 1 ? 's' : ''}</Typography>
          </Stack>

          {matchedSignals.length > 0 ? (
            <Stack spacing={0.5}>
              <Typography variant="caption" color="text.secondary">Signals used</Typography>
              <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap' }}>
                {matchedSignals.map((signal) => (
                  <Tooltip key={signal.id} title={<span style={{ whiteSpace: 'pre-line' }}>{signalTooltip(signal)}</span>} arrow>
                    <Chip
                      label={`${signal.analyzer_id ?? signal.signal_type}`}
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
