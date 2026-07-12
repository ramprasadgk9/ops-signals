import { Card, CardContent, Chip, Stack, Table, TableBody, TableCell, TableContainer, TableRow, Typography } from '@mui/material';

type Props = {
  score: number;
  status: string;
  breakdown?: {
    baselineShift?: number;
    trend?: number;
    anomalyWindows?: number;
  };
};

export function HealthScoreCard({ score, status, breakdown }: Props) {
  const getScoreBandColor = (s: number): 'success' | 'warning' | 'error' => {
    if (s >= 80) return 'success';
    if (s >= 60) return 'warning';
    return 'error';
  };

  const getScoreBandLabel = (s: number): string => {
    if (s >= 80) return 'Healthy';
    if (s >= 60) return 'Watch';
    if (s >= 30) return 'Needs Attention';
    return 'Critical';
  };

  return (
    <Card sx={{ height: '100%' }}>
      <CardContent>
        <Typography variant="h6" sx={{ mb: 2 }}>Operational Health</Typography>
        
        <Stack direction="row" alignItems="baseline" spacing={2} sx={{ mb: 3 }}>
          <Typography variant="h2" sx={{ fontWeight: 700 }}>{score}</Typography>
          <Chip 
            label={getScoreBandLabel(score)} 
            color={getScoreBandColor(score)} 
            variant="outlined"
          />
        </Stack>

        {breakdown && (
          <TableContainer>
            <Table size="small" sx={{ mb: 2 }}>
              <TableBody>
                <TableRow>
                  <TableCell sx={{ borderBottom: 'none', fontSize: '0.875rem' }}>
                    <Typography variant="caption" color="text.secondary">Calculated from</Typography>
                  </TableCell>
                  <TableCell align="right" sx={{ borderBottom: 'none', fontWeight: 600 }} />
                </TableRow>
                {breakdown.baselineShift !== undefined && (
                  <TableRow>
                    <TableCell sx={{ borderBottom: 'none', fontSize: '0.875rem', pt: 0.5 }}>Baseline Shift</TableCell>
                    <TableCell align="right" sx={{ borderBottom: 'none', fontSize: '0.875rem', color: breakdown.baselineShift !== 0 ? 'error.main' : 'inherit', fontWeight: 600, pt: 0.5 }}>
                      {breakdown.baselineShift <= 0 ? '' : '-'}{Math.abs(breakdown.baselineShift)}
                    </TableCell>
                  </TableRow>
                )}
                {breakdown.trend !== undefined && (
                  <TableRow>
                    <TableCell sx={{ borderBottom: 'none', fontSize: '0.875rem', pt: 0.5 }}>Trend</TableCell>
                    <TableCell align="right" sx={{ borderBottom: 'none', fontSize: '0.875rem', color: breakdown.trend !== 0 ? 'error.main' : 'inherit', fontWeight: 600, pt: 0.5 }}>
                      {breakdown.trend <= 0 ? '' : '-'}{Math.abs(breakdown.trend)}
                    </TableCell>
                  </TableRow>
                )}
                {breakdown.anomalyWindows !== undefined && (
                  <TableRow>
                    <TableCell sx={{ borderBottom: 'none', fontSize: '0.875rem', pt: 0.5 }}>Anomaly Windows</TableCell>
                    <TableCell align="right" sx={{ borderBottom: 'none', fontSize: '0.875rem', color: breakdown.anomalyWindows !== 0 ? 'error.main' : 'inherit', fontWeight: 600, pt: 0.5 }}>
                      {breakdown.anomalyWindows <= 0 ? '' : '-'}{Math.abs(breakdown.anomalyWindows)}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </CardContent>
    </Card>
  );
}
