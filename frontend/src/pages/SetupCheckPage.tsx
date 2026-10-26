import { useState } from 'react';
import { Box, Button, Link, Stack, Typography } from '@mui/material';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/queries';
import { PageHeader, WorkspacePanel } from '../standalone/components';
import { SignInSetupHelp } from '../components/SignInSetupHelp';
import { ui } from '../standalone/theme';
import {
  SETUP_GROUPS,
  checksIn,
  connectionTestText,
  fixLabel,
  hasFixDetails,
  setupDocsUrl,
  setupReport,
  setupSummary,
  unreachableSetupResult,
  type SetupCheck,
  type SetupCheckStatus,
} from '../utils/setupCheck';

export const SETUP_CHECK_QUERY_KEY = ['setup-check'];

const ICONS: Record<SetupCheckStatus, { mark: string; bg: string; color: string; border?: string }> = {
  ok: { mark: '✓', bg: ui.green, color: '#fff' },
  fail: { mark: '!', bg: ui.red, color: '#fff' },
  warn: { mark: '!', bg: ui.yellow, color: '#fff' },
  off: { mark: '–', bg: 'transparent', color: ui.muted, border: `1.5px solid ${ui.muted}` },
};

const STATUS_LABEL: Record<SetupCheckStatus, string> = { ok: 'Works', fail: 'Needs fixing', warn: 'Worth doing', off: 'Not set up' };

const buttonSx = { textTransform: 'none', fontWeight: 750, whiteSpace: 'nowrap' } as const;

function StatusIcon({ status }: { status: SetupCheckStatus }) {
  const icon = ICONS[status];
  return (
    <Box
      role="img"
      aria-label={STATUS_LABEL[status]}
      sx={{ width: 22, height: 22, borderRadius: '50%', bgcolor: icon.bg, color: icon.color, border: icon.border, display: 'grid', placeItems: 'center', fontSize: 13, fontWeight: 900, flex: '0 0 auto' }}
    >
      {icon.mark}
    </Box>
  );
}

function CodeBlock({ children }: { children: string }) {
  return (
    <Box component="pre" sx={{ m: 0, mt: 0.75, p: 1.25, borderRadius: '6px', bgcolor: 'rgba(15, 23, 42, 0.06)', border: `1px solid ${ui.border}`, fontSize: 12.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }}>
      {children}
    </Box>
  );
}

function CheckRow({ check }: { check: SetupCheck }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const test = useMutation({ mutationFn: () => api.testPrometheusConnection(check.connection_id ?? 'default') });
  const testAlert = useMutation({ mutationFn: () => api.sendTestAlert() });
  const details = hasFixDetails(check);
  const label = { fontSize: 11.5, letterSpacing: '.06em', textTransform: 'uppercase', color: ui.muted, fontWeight: 800, mb: 0.5 } as const;

  return (
    <Box sx={{ borderTop: `1px solid ${ui.border}` }}>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '22px 1fr', md: '22px 220px 1fr auto' }, gap: { xs: 1, md: 2 }, alignItems: 'center', py: 1.5, px: 0.5 }}>
        <StatusIcon status={check.status} />
        <Typography sx={{ fontWeight: 750 }}>{check.title}</Typography>
        <Box sx={{ gridColumn: { xs: '2', md: 'auto' } }}>
          <Typography sx={{ color: ui.muted, fontSize: 14 }}>{check.detail}</Typography>
          {test.data || test.error ? (
            <Typography role="status" sx={{ fontSize: 13, mt: 0.5, color: test.data?.available ? ui.green : ui.red, fontWeight: 700 }}>
              {test.data ? connectionTestText(test.data) : `Test failed: ${(test.error as Error).message}`}
            </Typography>
          ) : null}
          {testAlert.isSuccess || testAlert.isError ? (
            <Typography role="status" sx={{ fontSize: 13, mt: 0.5, color: testAlert.isSuccess ? ui.green : ui.red, fontWeight: 700 }}>
              {testAlert.isSuccess ? 'Test alert sent. Check again to see it counted.' : `Test alert failed: ${(testAlert.error as Error).message}`}
            </Typography>
          ) : null}
        </Box>
        <Stack direction="row" spacing={1} sx={{ gridColumn: { xs: '2', md: 'auto' }, justifySelf: { md: 'end' } }}>
          {details ? (
            <Button size="small" variant="outlined" sx={buttonSx} aria-expanded={open} aria-label={`${open ? 'Hide' : fixLabel(check)}: ${check.title}`} onClick={() => setOpen(!open)}>
              {open ? 'Hide' : fixLabel(check)}
            </Button>
          ) : check.docs && check.status !== 'ok' ? (
            <Button size="small" variant="outlined" sx={buttonSx} href={setupDocsUrl(check.docs)} target="_blank" rel="noreferrer">
              Guide
            </Button>
          ) : null}
          {check.action === 'test_connection' ? (
            <Button size="small" variant="outlined" sx={buttonSx} disabled={test.isPending} aria-label={`Test ${check.title}`} onClick={() => test.mutate()}>
              {test.isPending ? 'Testing…' : 'Test'}
            </Button>
          ) : null}
          {check.action === 'run_analysis' ? (
            <Button size="small" variant="contained" disableElevation sx={buttonSx} onClick={() => navigate('/validate-data')}>
              Run first analysis
            </Button>
          ) : null}
          {check.action === 'send_test_alert' ? (
            <Button size="small" variant="outlined" sx={buttonSx} disabled={testAlert.isPending} onClick={() => testAlert.mutate()}>
              Send test alert
            </Button>
          ) : null}
        </Stack>
      </Box>
      {check.action === 'sign_in' ? <SignInSetupHelp /> : null}
      {open && details ? (
        <Box sx={{ ml: { md: 4.5 }, mb: 1.5, p: 2, borderRadius: '6px', border: `1px solid ${check.status === 'fail' ? 'rgba(255, 77, 87, 0.35)' : ui.border}`, bgcolor: check.status === 'fail' ? 'rgba(255, 77, 87, 0.04)' : 'transparent', display: 'grid', gridTemplateColumns: { xs: '1fr', md: check.tried || check.cause ? '1fr 1fr' : '1fr' }, gap: 2.5 }}>
          {check.tried || check.cause ? (
            <Box>
              {check.tried ? (
                <>
                  <Typography sx={label}>What we tried</Typography>
                  <CodeBlock>{check.tried}</CodeBlock>
                </>
              ) : null}
              {check.cause ? (
                <>
                  <Typography sx={{ ...label, mt: check.tried ? 2 : 0 }}>Likely cause</Typography>
                  <Typography sx={{ fontSize: 14 }}>{check.cause}</Typography>
                </>
              ) : null}
            </Box>
          ) : null}
          <Box>
            <Typography sx={label}>{fixLabel(check)}</Typography>
            <Box component="ol" sx={{ m: 0, pl: 2.5, fontSize: 14, '& li': { my: 0.5 } }}>
              {(check.fix ?? []).map((step) => (
                <li key={step}>{step}</li>
              ))}
            </Box>
            {check.snippet ? <CodeBlock>{check.snippet}</CodeBlock> : null}
            {check.docs ? (
              <Typography sx={{ fontSize: 13, color: ui.muted, mt: 1.25 }}>
                Full guide:{' '}
                <Link href={setupDocsUrl(check.docs)} target="_blank" rel="noreferrer">
                  {check.docs.replace(/^docs\//, '')}
                </Link>
              </Typography>
            ) : null}
          </Box>
        </Box>
      ) : null}
    </Box>
  );
}

function Tile({ value, label, color, progress }: { value: string; label: string; color?: string; progress?: number }) {
  return (
    <WorkspacePanel sx={{ p: 2 }}>
      <Typography sx={{ fontSize: 24, fontWeight: 800, color: color ?? ui.text }}>{value}</Typography>
      <Typography sx={{ color: ui.muted, fontSize: 13 }}>{label}</Typography>
      {progress !== undefined ? (
        <Box sx={{ height: 6, borderRadius: 3, bgcolor: ui.border, mt: 1, overflow: 'hidden' }}>
          <Box sx={{ height: '100%', width: `${Math.round(progress * 100)}%`, bgcolor: progress === 1 ? ui.green : ui.yellow }} />
        </Box>
      ) : null}
    </WorkspacePanel>
  );
}

export function SetupCheckPage() {
  const query = useQuery({ queryKey: SETUP_CHECK_QUERY_KEY, queryFn: api.setupCheck, retry: false });
  const [copied, setCopied] = useState('');
  const result = query.data ?? (query.error ? unreachableSetupResult(query.error, 'the backend') : null);

  const copyReport = async () => {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(setupReport(result));
      setCopied('Copied. Paste it into a GitHub issue or a message to your admin.');
    } catch {
      setCopied("Couldn't copy: your browser blocked the clipboard.");
    }
  };

  const summary = result ? setupSummary(result) : null;

  return (
    <Stack spacing={3}>
      <PageHeader
        title="Setup check"
        subtitle="Checks each part of Ops Signals and tells you what to fix. Nothing here changes your settings."
        action={
          <Stack direction="row" spacing={1} alignItems="center">
            {copied ? <Typography role="status" sx={{ fontSize: 13, color: ui.muted }}>{copied}</Typography> : null}
            <Button variant="outlined" sx={buttonSx} disabled={!result} onClick={copyReport}>
              Copy report
            </Button>
            <Button variant="contained" disableElevation sx={buttonSx} disabled={query.isFetching} onClick={() => query.refetch()}>
              {query.isFetching ? 'Checking…' : 'Check again'}
            </Button>
          </Stack>
        }
      />

      {!result ? (
        <Typography sx={{ color: ui.muted }}>Checking every part of your setup… this takes a few seconds.</Typography>
      ) : (
        <>
          {summary ? (
            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(3, 1fr)' }, gap: 2 }}>
              <Tile
                value={`${summary.requiredDone} of ${summary.requiredTotal}`}
                label="needed to start: done"
                progress={summary.requiredTotal ? summary.requiredDone / summary.requiredTotal : 0}
              />
              <Tile value={String(summary.recommendedOpen)} label="recommended before others use it" color={summary.recommendedOpen ? ui.yellow : ui.green} />
              <Tile value={String(summary.optionalOff)} label="optional extras not set up" color={ui.muted} />
            </Box>
          ) : null}

          <WorkspacePanel sx={{ p: { xs: 2, md: 3 } }}>
            {SETUP_GROUPS.map((group) => {
              const checks = checksIn(result, group.id);
              if (!checks.length) return null;
              return (
                <Box key={group.id} component="section" aria-label={group.title} sx={{ '& + &': { mt: 3 } }}>
                  <Typography sx={{ fontSize: 12, letterSpacing: '.07em', textTransform: 'uppercase', color: ui.muted, fontWeight: 800, mb: 0.5 }}>
                    {group.title}{' '}
                    <Box component="span" sx={{ textTransform: 'none', letterSpacing: 0, fontWeight: 500, ml: 0.75 }}>
                      {group.hint}
                    </Box>
                  </Typography>
                  {checks.map((check) => (
                    <CheckRow key={check.id} check={check} />
                  ))}
                </Box>
              );
            })}
          </WorkspacePanel>

          <Typography sx={{ color: ui.muted, fontSize: 13 }}>
            The MCP server isn't checked here: your AI client starts it itself. Its HTTP tools (/api/mcp) are part of this backend and work whenever Backend is green.
          </Typography>
        </>
      )}
    </Stack>
  );
}
