import { Alert, Box, Button, Chip, Stack, Typography } from '@mui/material';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { WorkspacePanel } from '../standalone/components';
import { ui } from '../standalone/theme';
import type { AIStatus } from '../types';

const PROVIDER_LABELS: Record<string, string> = {
  ollama: 'Ollama',
  openai_compatible: 'OpenAI-compatible',
  anthropic: 'Anthropic',
};

const DOCS_HINT = 'docs/ask-ops-signals-assistant.md, "Other AI Providers"';

/** Integrations-page view of the optional AI provider: what the backend started with, whether
 * it is in use (and why not), and a one-request connection test. Read-only: the provider is set
 * in config.yaml or OPS_SIGNALS_* env vars and takes effect on restart. */
export function AiProviderCard() {
  const statusQuery = useQuery({ queryKey: ['ai-status'], queryFn: () => api.aiStatus(), retry: false });
  const testMutation = useMutation({ mutationFn: () => api.testAiConnection() });
  const status = statusQuery.data;
  const result = testMutation.data;

  return (
    <WorkspacePanel sx={{ p: 2.5 }}>
      <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', md: 'center' }} spacing={2} sx={{ mb: 2 }}>
        <Box>
          <Stack direction="row" spacing={1} alignItems="center">
            <Typography variant="h6" sx={{ fontSize: 18, fontWeight: 900 }}>AI provider</Typography>
            {status ? <Chip size="small" label={stateLabel(status)} color={stateColor(status)} sx={{ fontWeight: 800 }} /> : null}
          </Stack>
          <Typography sx={{ color: ui.muted, fontSize: 13 }}>
            Optional. Adds AI-written answers and summaries on top of the evidence; everything works without it.
          </Typography>
        </Box>
        {status?.enabled ? (
          <Button
            onClick={() => testMutation.mutate()}
            disabled={testMutation.isPending}
            variant="outlined"
            sx={{ textTransform: 'none', fontWeight: 800, whiteSpace: 'nowrap', flexShrink: 0 }}
          >
            {testMutation.isPending ? 'Testing...' : 'Test connection'}
          </Button>
        ) : null}
      </Stack>

      {statusQuery.isError ? <Typography color="text.secondary">AI status could not be loaded.</Typography> : null}

      {status && !status.enabled ? (
        <Typography color="text.secondary" sx={{ fontSize: 14 }}>
          To turn it on, set <code>OPS_SIGNALS_AI_ENABLED=1</code> and <code>OPS_SIGNALS_AI_PROVIDER</code> (ollama, openai_compatible or anthropic), then restart the backend. See {DOCS_HINT}.
        </Typography>
      ) : null}

      {status?.enabled ? (
        <Stack spacing={1.5}>
          <Box component="dl" sx={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', columnGap: 2, rowGap: 0.5, m: 0, fontSize: 14 }}>
            <Detail label="Provider" value={PROVIDER_LABELS[status.provider] ?? status.provider} />
            <Detail label="Model" value={status.model} />
            <Detail label="Endpoint" value={status.endpoint} />
            {status.api_key_set !== null ? <Detail label="API key" value={status.api_key_set ? 'Set' : 'Not set'} /> : null}
          </Box>
          {status.issue ? <Alert severity="warning">{status.issue}</Alert> : null}
          <Typography sx={{ color: ui.muted, fontSize: 12 }}>
            Change the provider in config.yaml or OPS_SIGNALS_* environment variables and restart the backend. See {DOCS_HINT}.
          </Typography>
        </Stack>
      ) : null}

      {testMutation.isError ? <Alert severity="error" sx={{ mt: 1.5 }}>{testMutation.error.message}</Alert> : null}
      {result?.ok ? (
        <Alert severity="success" sx={{ mt: 1.5 }}>
          Connected to {result.model ?? 'the model'}{result.latency_ms !== null ? ` in ${Math.round(result.latency_ms)} ms` : ''}. Reply: "{result.reply}"
        </Alert>
      ) : null}
      {result && !result.ok ? <Alert severity="error" sx={{ mt: 1.5 }}>{result.error}</Alert> : null}
    </WorkspacePanel>
  );
}

function stateLabel(status: AIStatus): string {
  if (!status.enabled) return 'Off';
  return status.active ? 'In use' : 'Not in use';
}

function stateColor(status: AIStatus): 'success' | 'warning' | 'default' {
  if (!status.enabled) return 'default';
  return status.active ? 'success' : 'warning';
}

function Detail({ label, value }: { label: string; value: string | null }) {
  return (
    <>
      <Box component="dt" sx={{ color: ui.muted, fontWeight: 700 }}>{label}</Box>
      <Box component="dd" sx={{ m: 0, overflowWrap: 'anywhere' }}>{value ?? '--'}</Box>
    </>
  );
}
