import { Box, Card, CardContent, Chip, IconButton, Stack, Tooltip, Typography } from '@mui/material';
import ContentCopyRoundedIcon from '@mui/icons-material/ContentCopyRounded';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';

function copyText(text: string) {
  void navigator.clipboard.writeText(text);
}

/** `showEndpoint={false}` where the endpoint is already shown nearby (the Integrations page's OTLP tile). */
export function OtlpIngestionCard({ showEndpoint = true }: { showEndpoint?: boolean } = {}) {
  const statusQuery = useQuery({
    queryKey: ['otlp-status'],
    queryFn: () => api.otlpStatus(),
    refetchInterval: 10_000,
  });

  const status = statusQuery.data;
  const endpointUrl = `${window.location.origin}${status?.endpoint_path ?? '/api/otlp/v1/metrics'}`;
  const receiving = (status?.points_received_total ?? 0) > 0;
  const rejectedEntries = Object.entries(status?.points_rejected_total ?? {}).filter(([, count]) => count > 0);

  return (
    <Card>
      <CardContent>
        <Stack direction="row" alignItems="center" spacing={1.5} sx={{ mb: 2 }}>
          <Typography variant="h6">{showEndpoint ? 'OTLP Metrics Ingestion' : 'OTLP Ingestion Activity'}</Typography>
          {statusQuery.isSuccess && (
            <Chip
              size="small"
              label={receiving ? 'Receiving data' : 'No data received yet'}
              color={receiving ? 'success' : 'default'}
              variant={receiving ? 'filled' : 'outlined'}
            />
          )}
        </Stack>
        <Stack spacing={2}>
          {showEndpoint ? (
          <Box>
            <Typography variant="subtitle2">Endpoint</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              Point an OTel Collector&apos;s <code>otlphttp</code> exporter, or an OTel SDK, at this address to
              push metrics for analysis. Unlike Prometheus, Ops Signals never connects out to anything for
              OTLP - there is nothing to &quot;test&quot; here, only whether data has actually arrived (below).
            </Typography>
            <Stack direction="row" alignItems="center" spacing={1}>
              <Typography
                variant="body2"
                sx={{ fontFamily: 'monospace', bgcolor: 'action.hover', px: 1.5, py: 0.75, borderRadius: 1, wordBreak: 'break-all' }}
              >
                {endpointUrl}
              </Typography>
              <Tooltip title="Copy endpoint URL">
                <IconButton size="small" onClick={() => copyText(endpointUrl)} aria-label="Copy OTLP endpoint URL">
                  <ContentCopyRoundedIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </Stack>
            <Typography variant="caption" color="text.secondary">
              Accepts <code>application/x-protobuf</code> or <code>application/json</code>. Gauge and Sum
              (counter) metrics only.
            </Typography>
          </Box>
          ) : null}

          {statusQuery.isSuccess && status && (
            <Box>
              <Typography variant="subtitle2">Ingestion Activity</Typography>
              <Stack direction="row" spacing={3} sx={{ mt: 0.5 }}>
                <Box>
                  <Typography variant="h6">{status.points_received_total.toLocaleString()}</Typography>
                  <Typography variant="caption" color="text.secondary">Points received</Typography>
                </Box>
                <Box>
                  <Typography variant="h6">{status.backlog_size.toLocaleString()}</Typography>
                  <Typography variant="caption" color="text.secondary">Awaiting analysis</Typography>
                </Box>
              </Stack>
              {rejectedEntries.length > 0 && (
                <Typography variant="body2" color="warning.main" sx={{ mt: 1 }}>
                  Rejected: {rejectedEntries.map(([reason, count]) => `${count.toLocaleString()} (${reason})`).join(', ')}
                </Typography>
              )}
            </Box>
          )}

          {statusQuery.isError && (
            <Typography variant="body2" color="error">
              Could not load OTLP ingestion status.
            </Typography>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}
