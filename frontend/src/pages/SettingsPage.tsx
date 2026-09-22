import { Box, Card, CardContent, Chip, IconButton, Stack, Tooltip, Typography } from '@mui/material';
import ContentCopyRoundedIcon from '@mui/icons-material/ContentCopyRounded';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';

function copyText(text: string) {
  void navigator.clipboard.writeText(text);
}

function OtlpIngestionCard() {
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
          <Typography variant="h6">OTLP Metrics Ingestion</Typography>
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

export function SettingsPage() {
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <Box>
        <Typography variant="h4" sx={{ mb: 1 }}>Settings</Typography>
        <Typography variant="body2" color="text.secondary">
          Configure platform behavior and preferences.
        </Typography>
      </Box>

      <Card>
        <CardContent>
          <Typography variant="h6" sx={{ mb: 2 }}>Analysis Configuration</Typography>
          <Stack spacing={2}>
            <Box>
              <Typography variant="subtitle2">Provider Settings</Typography>
              <Typography variant="body2" color="text.secondary">
                Configure data providers and ingestion sources.
              </Typography>
            </Box>
            <Box>
              <Typography variant="subtitle2">Capability Settings</Typography>
              <Typography variant="body2" color="text.secondary">
                Enable or disable analysis capabilities and configure their parameters.
              </Typography>
            </Box>
          </Stack>
        </CardContent>
      </Card>

      <OtlpIngestionCard />

      <Card>
        <CardContent>
          <Typography variant="h6" sx={{ mb: 2 }}>Display Preferences</Typography>
          <Stack spacing={2}>
            <Box>
              <Typography variant="subtitle2">Theme</Typography>
              <Typography variant="body2" color="text.secondary">
                Switch between light and dark mode in the top navigation.
              </Typography>
            </Box>
          </Stack>
        </CardContent>
      </Card>
    </Box>
  );
}
