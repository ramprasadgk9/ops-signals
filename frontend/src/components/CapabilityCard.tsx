import { Box, Card, CardContent, Chip, Divider, Stack, Table, TableBody, TableCell, TableRow, Typography } from '@mui/material';
import type { Capability } from '../types';

type Props = {
  capability: Capability;
};

export function CapabilityCard({ capability }: Props) {
  const supported = capability.metadata_json.supported_question_ids ?? [];
  const status = capability.metadata_json.status ?? (capability.enabled ? 'Active' : 'Inactive');
  
  return (
    <Card sx={{ height: '100%' }}>
      <CardContent>
        <Stack spacing={2}>
          {/* Header with title and status */}
          <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
            <Box>
              <Typography variant="h6">{capability.title}</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                {capability.description}
              </Typography>
            </Box>
            <Chip 
              label={status} 
              color={capability.enabled ? 'success' : 'default'} 
              size="small"
            />
          </Stack>

          <Divider />

          {/* Metadata table */}
          <Table size="small">
            <TableBody>
              <TableRow>
                <TableCell sx={{ borderBottom: 'none', py: 0.5, fontWeight: 600, fontSize: '0.875rem', width: '40%' }}>
                  Analyzer
                </TableCell>
                <TableCell sx={{ borderBottom: 'none', py: 0.5, fontSize: '0.875rem' }}>
                  {capability.analyzer_id}
                </TableCell>
              </TableRow>
              <TableRow>
                <TableCell sx={{ borderBottom: 'none', py: 0.5, fontWeight: 600, fontSize: '0.875rem' }}>
                  Capability ID
                </TableCell>
                <TableCell sx={{ borderBottom: 'none', py: 0.5, fontSize: '0.875rem' }}>
                  {capability.id}
                </TableCell>
              </TableRow>
              <TableRow>
                <TableCell sx={{ borderBottom: 'none', py: 0.5, fontWeight: 600, fontSize: '0.875rem', verticalAlign: 'top', pt: 1 }}>
                  Supported Questions
                </TableCell>
                <TableCell sx={{ borderBottom: 'none', py: 0.5, fontSize: '0.875rem', pt: 1 }}>
                  <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap">
                    {supported.length > 0 ? (
                      supported.map((q) => (
                        <Chip key={q} size="small" label={q} variant="outlined" />
                      ))
                    ) : (
                      <Typography variant="caption" color="text.secondary">None</Typography>
                    )}
                  </Stack>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </Stack>
      </CardContent>
    </Card>
  );
}
