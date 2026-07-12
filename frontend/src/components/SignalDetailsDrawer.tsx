import { Box, Chip, Drawer, List, ListItem, ListItemText, Stack, Typography } from '@mui/material';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import type { Signal, TimeseriesPoint } from '../types';

type Props = {
  open: boolean;
  signal: Signal | null;
  timeseries: TimeseriesPoint[];
  onClose: () => void;
};

export function SignalDetailsDrawer({ open, signal, timeseries, onClose }: Props) {
  if (!signal) return null;

  // Filter timeseries data to match signal's service and metric
  const signalTimeseries = timeseries.filter(
    (point) => point.service === signal.service && point.metric_name === signal.metric_name
  );

  return (
    <Drawer anchor="right" open={open} onClose={onClose}>
      <Box sx={{ width: { xs: '100vw', md: 560 }, p: 3, overflowY: 'auto' }}>
        <Typography variant="h5">{signal.summary ?? signal.signal_type}</Typography>
        <Stack direction="row" spacing={1} sx={{ my: 2 }}>
          {signal.severity && <Chip label={`Severity: ${signal.severity}`} color={signal.severity === 'high' ? 'error' : 'default'} />}
          <Chip label={`Importance: ${signal.importance_score.toFixed(2)}`} />
          {signal.confidence !== undefined && <Chip label={`Confidence: ${Math.round(signal.confidence * 100)}%`} />}
        </Stack>

        <List dense>
          <ListItem>
            <ListItemText primary="Signal Type" secondary={signal.signal_type} />
          </ListItem>
          {signal.analyzer_id && (
            <ListItem>
              <ListItemText primary="Analyzer" secondary={signal.analyzer_id} />
            </ListItem>
          )}
          <ListItem>
            <ListItemText primary="Metric" secondary={signal.metric_name} />
          </ListItem>
          {signal.service && (
            <ListItem>
              <ListItemText primary="Service" secondary={signal.service} />
            </ListItem>
          )}
          {signal.start_time && (
            <ListItem>
              <ListItemText primary="Period" secondary={`${signal.start_time} - ${signal.end_time ?? 'ongoing'}`} />
            </ListItem>
          )}
        </List>

        {signalTimeseries.length > 0 && (
          <>
            <Typography variant="h6" sx={{ mt: 3, mb: 2 }}>Metric Timeline</Typography>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={signalTimeseries}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis 
                  dataKey="timestamp" 
                  tick={{ fontSize: 12 }}
                  tickFormatter={(value) => new Date(value).toLocaleTimeString()}
                />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip 
                  formatter={(value: number) => value.toFixed(4)}
                  labelFormatter={(label) => new Date(label).toLocaleString()}
                />
                <Line 
                  type="monotone" 
                  dataKey="value" 
                  stroke="#1976d2" 
                  dot={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </>
        )}

        {Object.keys(signal.evidence).length > 0 && (
          <>
            <Typography variant="h6" sx={{ mt: 2, mb: 1 }}>Evidence</Typography>
            <List dense>
              {Object.entries(signal.evidence).map(([key, value]) => (
                <ListItem key={key}>
                  <ListItemText 
                    primary={key} 
                    secondary={typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)}
                  />
                </ListItem>
              ))}
            </List>
          </>
        )}
      </Box>
    </Drawer>
  );
}
