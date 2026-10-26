import { useState } from 'react';
import { Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Link, Stack, Typography } from '@mui/material';
import { useMutation } from '@tanstack/react-query';
import { api } from '../api/queries';
import { useWebPermissions } from '../hooks/useWebPermissions';
import { ui } from '../standalone/theme';
import { setupDocsUrl } from '../utils/setupCheck';

// Setup check → Login, with the backend's own sign-in (backend/app/api/setup_check.py action "sign_in"):
// the address to register with the provider, Test sign-in, and how to set it up - next to the row.

const SETTINGS = `OPS_SIGNALS_AUTH_MODE=oidc
OPS_SIGNALS_OIDC_ISSUER_URL=https://your-provider/…
OPS_SIGNALS_OIDC_CLIENT_ID=…
OPS_SIGNALS_OIDC_CLIENT_SECRET=…
OPS_SIGNALS_AUTH_ADMIN_GROUPS=…
OPS_SIGNALS_AUTH_EDITOR_GROUPS=…`;

const buttonSx = { textTransform: 'none', fontWeight: 750, whiteSpace: 'nowrap' } as const;
const codeSx = { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12.5, px: 1, py: 0.5, borderRadius: '6px', bgcolor: 'rgba(15, 23, 42, 0.06)', overflowWrap: 'anywhere' } as const;

export function callbackAddress(origin: string = window.location.origin): string {
  return `${origin}/api/auth/callback`;
}

function CopyLine({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  return (
    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
      <Box component="code" sx={codeSx}>{value}</Box>
      <Button size="small" variant="outlined" sx={buttonSx} onClick={copy}>{copied ? 'Copied' : 'Copy'}</Button>
    </Stack>
  );
}

function SetUpDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth aria-labelledby="set-up-sign-in-title">
      <DialogTitle id="set-up-sign-in-title" sx={{ fontWeight: 850 }}>Set up company sign-in</DialogTitle>
      <DialogContent>
        <Typography sx={{ fontSize: 14, color: ui.muted, mb: 1.5 }}>
          Works with any provider that supports OpenID Connect. Takes about 10 minutes; you need someone who can register apps in your provider.
        </Typography>
        <Box component="ol" sx={{ m: 0, pl: 2.5, display: 'grid', gap: 1.25, fontSize: 14 }}>
          <li>
            <b>Register Ops Signals as a web app</b> in your provider, with this redirect address:
            <Box sx={{ mt: 0.75 }}><CopyLine value={callbackAddress()} /></Box>
          </li>
          <li><b>Add a groups claim</b> to the ID token, and note the client ID, a client secret and the issuer address.</li>
          <li>
            <b>Set them on the backend</b>, with OPS_SIGNALS_API_TOKEN, and restart it:
            <Box component="pre" sx={{ ...codeSx, m: 0, mt: 0.75, p: 1.25, whiteSpace: 'pre-wrap' }}>{SETTINGS}</Box>
          </li>
          <li><b>Click Test sign-in</b> on this row. It checks Ops Signals can reach your provider, then you sign in in a new tab and this row shows who you are and the group that gave your role.</li>
        </Box>
        <Typography sx={{ fontSize: 13, color: ui.muted, mt: 1.5 }}>
          No provider yet? Set OPS_SIGNALS_TEST_SIGN_IN=true in .env and restart scripts/run_all.sh to try sign-in with test accounts on this computer.
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button sx={buttonSx} onClick={onClose}>Close</Button>
        <Link href={setupDocsUrl('docs/web-ui-sign-in.md')} target="_blank" rel="noreferrer" sx={{ px: 1, fontWeight: 700 }}>Full guide</Link>
      </DialogActions>
    </Dialog>
  );
}

export function SignInSetupHelp() {
  const { me } = useWebPermissions();
  const [open, setOpen] = useState(false);
  const oidcOn = me?.mode === 'oidc';
  const test = useMutation({ mutationFn: api.testSignIn });
  return (
    <Box sx={{ ml: { md: 4.5 }, mb: 1.5, display: 'grid', gap: 1 }}>
      {oidcOn ? (
        <Stack spacing={0.5}>
          <Typography sx={{ fontSize: 13, color: ui.muted }}>Redirect address registered with your provider:</Typography>
          <CopyLine value={callbackAddress()} />
        </Stack>
      ) : null}
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        {oidcOn ? (
          <Button size="small" variant="outlined" sx={buttonSx} disabled={test.isPending} onClick={() => test.mutate()}>
            {test.isPending ? 'Testing…' : 'Test sign-in'}
          </Button>
        ) : null}
        <Button size="small" variant="outlined" sx={buttonSx} onClick={() => setOpen(true)}>How to set up company sign-in</Button>
      </Stack>
      {test.data ? (
        <Typography role="status" sx={{ fontSize: 13, fontWeight: 700, color: test.data.reachable ? ui.green : ui.red }}>
          {test.data.reachable ? (
            <>
              {test.data.detail}{' '}
              <Link href={`${me?.login_url ?? '/api/auth/login'}?next=${encodeURIComponent('/setup-check')}`} target="_blank" rel="noopener">Sign in in a new tab</Link>
              , then check again here to see who signed in.
            </>
          ) : `Test sign-in failed: ${test.data.detail}`}
        </Typography>
      ) : test.error ? (
        <Typography role="status" sx={{ fontSize: 13, fontWeight: 700, color: ui.red }}>Test sign-in failed: {(test.error as Error).message}</Typography>
      ) : null}
      <SetUpDialog open={open} onClose={() => setOpen(false)} />
    </Box>
  );
}
