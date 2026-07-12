import { Button, Card, CardActions, CardContent, Chip, Stack, Typography } from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { api } from '../api/queries';
import type { Finding } from '../types';

type Props = {
  finding: Finding;
  onViewDetails?: (finding: Finding) => void;
};

export function FindingCard({ finding, onViewDetails }: Props) {
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
        
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {finding.summary}
        </Typography>
        
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
            <Typography variant="body2">{finding.signal_ids.length} anomaly window{finding.signal_ids.length !== 1 ? 's' : ''}</Typography>
          </Stack>
          
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
