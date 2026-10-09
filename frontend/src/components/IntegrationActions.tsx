import { Box, Button, Stack, Typography } from '@mui/material';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link as RouterLink } from 'react-router-dom';
import { api } from '../api/queries';
import { ui } from '../standalone/theme';

// Bundled from sample_data/ruptures_data/ruptures_sample.csv: a checkout cpu_usage series with one
// abrupt regime shift, so the demo run ends with a real finding rather than an empty page.
export const DEMO_CSV_PATH = 'samples/demo-checkout-cpu.csv';
export const DEMO_SERVICE = 'checkout';
export const DEMO_METRIC = 'cpu_usage';

function refreshDataViews(queryClient: ReturnType<typeof useQueryClient>) {
  // Prefix matches: every alert list, status read and findings view picks up the new data.
  for (const key of ['alerts', 'ingestion-status', 'findings', 'findings-overview', 'overview-summary', 'assistant-starters']) {
    void queryClient.invalidateQueries({ queryKey: [key] });
  }
}

function ResultText({ tone, children }: { tone: 'ok' | 'warn' | 'error'; children: React.ReactNode }) {
  const color = tone === 'ok' ? 'var(--os-ink-green)' : tone === 'warn' ? 'var(--os-ink-orange)' : 'var(--os-ink-red)';
  return (
    <Typography role="status" variant="body2" sx={{ color }}>
      {children}
    </Typography>
  );
}

export function SendTestAlertButton() {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => api.sendTestAlert(),
    onSuccess: () => refreshDataViews(queryClient),
  });
  const receipt = mutation.data;

  return (
    <Stack spacing={1}>
      <Box>
        <Button variant="outlined" size="small" onClick={() => mutation.mutate()} disabled={mutation.isPending} sx={{ textTransform: 'none', fontWeight: 750 }}>
          {mutation.isPending ? 'Sending…' : 'Send test alert'}
        </Button>
      </Box>
      {mutation.isError ? <ResultText tone="error">Could not send the test alert: {mutation.error.message}</ResultText> : null}
      {receipt?.disabled ? <ResultText tone="warn">Alert enrichment is off, so the test alert was not stored.</ResultText> : null}
      {receipt && !receipt.disabled ? (
        <ResultText tone="ok">Test alert sent. It appears on the Alerts page in a few seconds, and in Slack if notifications are set up.</ResultText>
      ) : null}
    </Stack>
  );
}

async function loadDemoData() {
  const response = await fetch(`${import.meta.env.BASE_URL}${DEMO_CSV_PATH}`);
  if (!response.ok) throw new Error(`demo data file not found (${response.status})`);
  const form = new FormData();
  form.append('file', new File([await response.blob()], 'demo-checkout-cpu.csv', { type: 'text/csv' }));
  form.append('provider', 'generic');
  form.append('service', DEMO_SERVICE);
  form.append('metric_name', DEMO_METRIC);
  form.append('interval', '5m');
  return api.runCsvUpload(form);
}

/** `links`: quiet text buttons, for a one-line mention rather than a tile. */
export function LoadDemoDataButton({ variant = 'buttons' }: { variant?: 'buttons' | 'links' } = {}) {
  const links = variant === 'links';
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: loadDemoData,
    onSuccess: () => refreshDataViews(queryClient),
  });

  return (
    <Stack spacing={1}>
      <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 1 }}>
        <Button variant={links ? 'text' : 'contained'} size="small" onClick={() => mutation.mutate()} disabled={mutation.isPending} sx={{ textTransform: 'none', fontWeight: 750, ...(links ? {} : { bgcolor: ui.blue }) }}>
          {mutation.isPending ? 'Analyzing demo data…' : 'Load demo data'}
        </Button>
        <Button component={RouterLink} to="/validate-data" variant={links ? 'text' : 'outlined'} size="small" sx={{ textTransform: 'none', fontWeight: 750 }}>
          Analyze your own CSV
        </Button>
      </Stack>
      {mutation.isError ? <ResultText tone="error">Could not load demo data: {mutation.error.message}</ResultText> : null}
      {mutation.data ? (
        <ResultText tone="ok">
          Demo analysis complete for {mutation.data.service} / {mutation.data.metric_name}.{' '}
          <Box component={RouterLink} to="/findings" sx={{ color: ui.blue, fontWeight: 700 }}>
            View findings →
          </Box>
        </ResultText>
      ) : null}
    </Stack>
  );
}
