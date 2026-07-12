import { ResponsiveContainer, ComposedChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceArea, ReferenceLine } from 'recharts';
import { Box, Typography } from '@mui/material';
import type { Signal, TimeseriesPoint } from '../types';

type Props = {
  points: TimeseriesPoint[];
  signals: Signal[];
};

export function MetricTimelineChart({ points, signals }: Props) {
  const baseline = signals.filter((s) => s.signal_type === 'baseline_shift');
  const anomalies = signals.filter((s) => s.signal_type === 'anomaly');
  const trends = signals.filter((s) => s.signal_type === 'trend');

  return (
    <Box sx={{ height: 260, mt: 2 }}>
      <Typography variant="subtitle1">Metric Timeline</Typography>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={points}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.25} />
          <XAxis dataKey="timestamp" hide />
          <YAxis />
          <Tooltip />
          <Line type="monotone" dataKey="value" stroke="#0f766e" dot={false} strokeWidth={2} />
          {baseline.map((s) => (
            <ReferenceLine key={s.id} x={s.start_time} stroke="#7c2d12" strokeDasharray="5 4" />
          ))}
          {anomalies.map((s) => (
            <ReferenceArea key={s.id} x1={s.start_time} x2={s.end_time} fill="#ef4444" fillOpacity={0.14} />
          ))}
          {trends.map((s) => (
            <ReferenceArea key={s.id} x1={s.start_time} x2={s.end_time} fill="#0ea5e9" fillOpacity={0.08} />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </Box>
  );
}
