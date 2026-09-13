import { Box, Chip, Drawer, List, ListItem, ListItemText, Stack, Tooltip, Typography } from '@mui/material';
import type { Finding, Signal } from '../types';

type Props = {
  open: boolean;
  finding: Finding | null;
  signals?: Signal[];
  onClose: () => void;
};

export function FindingDetailsDrawer({ open, finding, signals = [], onClose }: Props) {
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
          <Stack direction="row" spacing={0.75} alignItems="flex-start">
            {finding.ai_summary && (
              <Chip label="AI" size="small" variant="outlined" color="info" sx={{ height: 18, fontSize: '0.65rem', mt: 0.25 }} />
            )}
            <Typography variant="body2">{finding.ai_summary ?? finding.summary}</Typography>
          </Stack>
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
              primary="Evidence (Supporting Signals)" 
              secondary={`${matchedSignals.length} supporting signal${matchedSignals.length !== 1 ? 's' : ''} detected`}
            />
          </ListItem>
          {finding.signal_ids.length > 0 && (
            <ListItem>
              <ListItemText 
                primary="Signals used"
                secondary={
                  <Stack component="span" spacing={0.75} sx={{ mt: 1, flexWrap: 'wrap' }}>
                    {matchedSignals.length > 0
                      ? matchedSignals.map((signal) => (
                          <Tooltip key={signal.id} title={<span style={{ whiteSpace: 'pre-line' }}>{signalTooltip(signal)}</span>} arrow>
                            <Chip
                              label={signal.analyzer_id ?? signal.signal_type}
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
