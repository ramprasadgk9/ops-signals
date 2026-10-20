import React from 'react';
import { Alert, Box, Button, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography } from '@mui/material';
import UploadFileRoundedIcon from '@mui/icons-material/UploadFileRounded';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/queries';
import { Pill, WorkspacePanel } from '../standalone/components';
import { formatDateTime, ui } from '../standalone/theme';
import { ImportIncidentsDialog } from './ImportIncidentsDialog';
import { useWebPermissions, WEB_LOCK_REASONS } from '../hooks/useWebPermissions';

/** Integrations-page view of incident-history imports: what was imported, when, and a way to
 * import again or undo a batch. */
export function ImportHistoryCard() {
  const { canAdmin } = useWebPermissions();
  const queryClient = useQueryClient();
  const [open, setOpen] = React.useState(false);
  const importsQuery = useQuery({ queryKey: ['case-imports'], queryFn: () => api.caseImports(), retry: false });
  const undoMutation = useMutation({
    mutationFn: (batchId: string) => api.undoCaseImport(batchId),
    onSuccess: () => void queryClient.invalidateQueries(),
  });
  const batches = importsQuery.data ?? [];
  const importedCases = batches
    .filter((batch) => batch.status === 'completed')
    .reduce((total, batch) => total + (batch.counts.new ?? 0), 0);

  return (
    <WorkspacePanel sx={{ p: 2.5 }}>
      <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', md: 'center' }} spacing={2} sx={{ mb: 2 }}>
        <Box>
          <Typography variant="h6" sx={{ fontSize: 18, fontWeight: 900 }}>Incident history</Typography>
          <Typography sx={{ color: ui.muted, fontSize: 13 }}>
            Past incidents imported from Jira, PagerDuty, incident.io or CSV and Markdown files, as resolved cases for similar-case search.
            {batches.length ? ` ${importedCases} cases imported so far.` : ''}
          </Typography>
        </Box>
        <Button onClick={() => setOpen(true)} startIcon={<UploadFileRoundedIcon />} variant="outlined" sx={{ textTransform: 'none', fontWeight: 800, whiteSpace: 'nowrap', flexShrink: 0 }}>
          {batches.length ? 'Import again' : 'Import past incidents'}
        </Button>
      </Stack>
      <ImportIncidentsDialog open={open} onClose={() => setOpen(false)} />

      {importsQuery.isError ? <Typography color="text.secondary">Import history could not be loaded.</Typography> : null}
      {undoMutation.isError ? <Alert severity="error" sx={{ mb: 1 }}>{undoMutation.error.message}</Alert> : null}
      {!importsQuery.isLoading && !importsQuery.isError && !batches.length ? (
        <Typography color="text.secondary">Nothing imported yet. Re-importing the same export later only updates what changed.</Typography>
      ) : null}
      {batches.length ? (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>When</TableCell>
              <TableCell>Source</TableCell>
              <TableCell>Files</TableCell>
              <TableCell>Result</TableCell>
              <TableCell>Status</TableCell>
              <TableCell align="right" />
            </TableRow>
          </TableHead>
          <TableBody>
            {batches.slice(0, 10).map((batch) => (
              <TableRow key={batch.id}>
                <TableCell>{formatDateTime(batch.created_at)}</TableCell>
                <TableCell>{batch.sources.join(', ') || '--'}</TableCell>
                <TableCell>{Object.keys(batch.file_profiles).length}</TableCell>
                <TableCell>
                  {batch.counts.new ?? 0} new · {batch.counts.updated ?? 0} updated · {batch.counts.unchanged ?? 0} unchanged · {batch.counts.skipped ?? 0} skipped
                </TableCell>
                <TableCell><Pill label={batch.status} /></TableCell>
                <TableCell align="right">
                  {batch.status === 'completed' && (batch.counts.new ?? 0) > 0 ? (
                    <Button
                      size="small"
                      color="warning"
                      disabled={undoMutation.isPending || !canAdmin}
                      title={canAdmin ? undefined : WEB_LOCK_REASONS.admin}
                      onClick={() => {
                        if (window.confirm(`Delete the ${batch.counts.new} cases this import created?`)) undoMutation.mutate(batch.id);
                      }}
                      sx={{ textTransform: 'none', fontWeight: 800 }}
                    >
                      Undo
                    </Button>
                  ) : null}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : null}
    </WorkspacePanel>
  );
}
