import { Typography, useTheme } from '@mui/material';
import { Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip as RechartsTooltip, XAxis, YAxis } from 'recharts';
import type { Finding } from '../types';
import { findingChart, formatReading } from '../utils/findingChartMarks';

type MarkLabelProps = { viewBox?: { x: number; y: number; width?: number }; value: string; side: 'start' | 'end'; color: string; row: number };

// Above the plot, starting at the mark (or ending at it, for marks in the right half) so the
// label stays inside the chart.
function MarkLabel({ viewBox, value, side, color, row }: MarkLabelProps) {
  if (!viewBox) return null;
  const x = side === 'start' ? viewBox.x : viewBox.x + (viewBox.width ?? 0);
  return (
    <text x={x + (side === 'start' ? 2 : -2)} y={viewBox.y - 6 - row * 14} textAnchor={side} fill={color} fontSize={11.5} fontWeight={600}>
      {value}
    </text>
  );
}

/** A finding's readings, with the stretch or moment its sentence talks about marked on them. */
export function FindingReadingsChart({ finding, readings }: { finding: Finding; readings: Array<{ timestamp: string; value: number }> }) {
  const theme = useTheme();
  const chart = findingChart(finding, readings);
  const problem = theme.palette.warning.main;
  const gap = theme.palette.text.secondary;
  const labelRows = chart.bands.filter((b) => b.label).length + chart.lines.length;
  const tickTime = (value: number) => new Date(value).toLocaleString(undefined, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });

  return (
    <>
      <ResponsiveContainer width="100%" height={200 + Math.max(0, labelRows - 1) * 14}>
        <LineChart data={chart.points} margin={{ top: labelRows ? 8 + labelRows * 14 : 8, right: 28, left: 0, bottom: 0 }}>
          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={chart.domain}
            tickFormatter={tickTime}
            tickLine={false}
            axisLine={false}
            minTickGap={40}
          />
          <YAxis domain={['auto', 'auto']} tickFormatter={formatReading} tickLine={false} axisLine={false} width={52} />
          <RechartsTooltip
            labelFormatter={(value: number) => new Date(value).toLocaleString()}
            formatter={(value: number) => [formatReading(value), 'Value']}
          />
          {chart.bands.map((band, i) => {
            const color = band.style === 'gap' ? gap : problem;
            return (
              <ReferenceArea
                key={`band-${i}`}
                x1={band.x1}
                x2={band.x2}
                fill={color}
                fillOpacity={band.style === 'gap' ? 0.12 : 0.16}
                stroke={color}
                strokeOpacity={0.7}
                strokeDasharray="4 3"
                ifOverflow="hidden"
                label={band.label ? <MarkLabel value={band.label} side={band.labelSide} color={band.style === 'gap' ? theme.palette.text.primary : problem} row={0} /> : undefined}
              />
            );
          })}
          {chart.lines.map((line, i) => (
            <ReferenceLine
              key={`line-${i}`}
              x={line.x}
              stroke={problem}
              strokeWidth={1.5}
              strokeDasharray="4 3"
              label={<MarkLabel value={line.label} side={line.labelSide} color={problem} row={chart.lines.length - 1 - i} />}
            />
          ))}
          <Line type="linear" dataKey="value" stroke="#4f46e5" strokeWidth={2} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
      {chart.note && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
          {chart.note}
        </Typography>
      )}
    </>
  );
}
