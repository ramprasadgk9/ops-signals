import { Box, Chip, Drawer, List, ListItem, ListItemText, Stack, Typography } from '@mui/material';
import type { Finding } from '../types';

type Props = {
  open: boolean;
  finding: Finding | null;
  onClose: () => void;
};

export function FindingDetailsDrawer({ open, finding, onClose }: Props) {
  if (!finding) return null;

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

  const getCategoryLabel = (category?: string): string => {
    if (!category) return 'Insight';
    return category
      .split('_')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  };

  return (
    <Drawer anchor="right" open={open} onClose={onClose}>
      <Box sx={{ width: { xs: '100vw', md: 560 }, p: 3, overflowY: 'auto' }}>
        <Typography variant="h5">{finding.title}</Typography>
        
        <Stack direction="row" spacing={1} sx={{ my: 2, flexWrap: 'wrap', gap: 1 }}>
          <Chip 
            label={finding.health_status.charAt(0).toUpperCase() + finding.health_status.slice(1)} 
            color={getHealthColor(finding.health_status)}
          />
          <Chip label={`Category: ${getCategoryLabel(finding.category)}`} />
          <Chip label={`Importance: ${finding.importance_score.toFixed(2)}`} />
          <Chip label={`Priority: P${finding.investigation_priority}`} variant="outlined" />
        </Stack>

        <Box sx={{ mb: 3, p: 2, backgroundColor: '#f5f5f5', borderRadius: 1 }}>
          <Typography variant="body2">{finding.summary}</Typography>
        </Box>

        <List dense>
          <ListItem>
            <ListItemText primary="Metric" secondary={finding.metric_name} />
          </ListItem>
          {finding.service && (
            <ListItem>
              <ListItemText primary="Service" secondary={finding.service} />
            </ListItem>
          )}
          <ListItem>
            <ListItemText 
              primary="Evidence (Anomaly Windows)" 
              secondary={`${finding.signal_ids.length} anomalies detected`}
            />
          </ListItem>
          {finding.signal_ids.length > 0 && (
            <ListItem>
              <ListItemText 
                primary="Signal IDs"
                secondary={
                  <Stack component="span" spacing={0.5} sx={{ mt: 1 }}>
                    {finding.signal_ids.map((id) => (
                      <Typography key={id} variant="caption" component="div" sx={{ fontFamily: 'monospace', fontSize: '0.75rem' }}>
                        {id}
                      </Typography>
                    ))}
                  </Stack>
                }
              />
            </ListItem>
          )}
        </List>

        {Object.keys(finding.comparison_json).length > 0 && (
          <>
            <Typography variant="h6" sx={{ mt: 3, mb: 2 }}>Comparison Analysis</Typography>
            <Box sx={{ backgroundColor: '#f5f5f5', p: 2, borderRadius: 1, maxHeight: 300, overflowY: 'auto' }}>
              <Typography variant="caption" component="pre" sx={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap', fontSize: '0.75rem' }}>
                {JSON.stringify(finding.comparison_json, null, 2)}
              </Typography>
            </Box>
          </>
        )}
      </Box>
    </Drawer>
  );
}
