import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Avatar, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, Typography } from '@mui/material';
import { useQueryClient } from '@tanstack/react-query';
import { useLocation } from 'react-router-dom';
import { api } from '../api/queries';
import { SIGNED_OUT_EVENT } from '../api/client';
import { ME_QUERY_KEY, useWebPermissions, type Me } from '../hooks/useWebPermissions';
import { ui } from '../standalone/theme';

// The web UI's side of the backend's own sign-in (OPS_SIGNALS_AUTH_MODE=oidc; backend/app/api/auth.py).
// Nobody signed in sees the sign-in page instead of the app; /sign-in shows why a sign-in failed;
// /signed-out says what signing out did. Other modes are untouched.

export const SIGN_IN_DONE_PATH = '/sign-in/done';

function signInHref(me: Me | undefined, next: string): string {
  return `${me?.login_url ?? '/api/auth/login'}?next=${encodeURIComponent(next)}`;
}

function Card({ children }: { children: ReactNode }) {
  return (
    <Box sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center', px: 2, bgcolor: ui.bg, color: ui.text }}>
      <Stack spacing={2} sx={{ width: '100%', maxWidth: 400, p: 3.5, bgcolor: 'var(--os-surface, #fff)', border: `1px solid ${ui.border}`, borderRadius: '12px', textAlign: 'center', boxShadow: '0 10px 30px rgba(15,23,42,.06)' }}>
        <Stack direction="row" spacing={1.25} alignItems="center" justifyContent="center">
          <Avatar sx={{ width: 36, height: 36, bgcolor: ui.red, fontSize: 13, fontWeight: 900 }}>OS</Avatar>
          <Typography sx={{ fontSize: 19, fontWeight: 900 }}>Ops Signals</Typography>
        </Stack>
        {children}
      </Stack>
    </Box>
  );
}

function Problem({ tone, title, children, errorId }: { tone: 'rose' | 'amber'; title: string; children: ReactNode; errorId?: string | null }) {
  const colors = tone === 'rose'
    ? { bg: 'var(--os-tint-rose, #fff1f2)', ink: 'var(--os-ink-rose, #881337)' }
    : { bg: 'var(--os-tint-amber, #fff7ed)', ink: 'var(--os-ink-amber, #7c2d12)' };
  return (
    <Box role="alert" sx={{ textAlign: 'left', borderRadius: '8px', px: 1.5, py: 1.25, bgcolor: colors.bg, color: colors.ink }}>
      <Typography sx={{ fontWeight: 800 }}>{title}</Typography>
      <Typography sx={{ fontSize: 14 }}>{children}</Typography>
      {errorId ? <Typography sx={{ mt: 0.75, fontSize: 12, fontFamily: 'ui-monospace, Menlo, monospace', opacity: 0.8 }}>Error id {errorId}</Typography> : null}
    </Box>
  );
}

const buttonSx = { textTransform: 'none', fontWeight: 800 } as const;

/** Screen A, and the failed sign-in screens E1-E4 from /sign-in?error=... */
export function SignInPage({ me, next, error, errorId, said, as }: { me: Me | undefined; next: string; error?: string | null; errorId?: string | null; said?: string | null; as?: string | null }) {
  const signIn = signInHref(me, next);
  const provider = me?.provider_name ?? 'your company account';
  if (error === 'groups') {
    return (
      <Card>
        <Problem tone="amber" title="Signed in, but your groups didn't come through">
          You're a Viewer for now. Your company's sign-in didn't send your groups. Ask your Ops Signals admin; Setup check → Login shows the fix.
        </Problem>
        <Button variant="contained" disableElevation sx={buttonSx} href={next}>Continue as Viewer</Button>
      </Card>
    );
  }
  if (error === 'not_allowed') {
    return (
      <Card>
        <Problem tone="rose" title="You can't use Ops Signals yet" errorId={errorId}>
          You signed in{as ? ` as ${as}` : ''}, but you aren't in a group that may use Ops Signals. Ask your Ops Signals admin to add you.
        </Problem>
        <Button variant="outlined" sx={buttonSx} href={signIn}>Sign in as someone else</Button>
      </Card>
    );
  }
  if (error === 'expired') {
    return (
      <Card>
        <Problem tone="amber" title="That sign-in took too long">
          For your safety a sign-in has to finish within 10 minutes in the same browser. Start again.
        </Problem>
        <Button variant="contained" disableElevation sx={buttonSx} href={signIn}>Sign in</Button>
      </Card>
    );
  }
  if (error === 'provider') {
    return (
      <Card>
        <Problem tone="rose" title="Your company's sign-in didn't let you in" errorId={errorId}>
          {said ? `It said: "${said}" ` : ''}Ask your Ops Signals admin; they can see the details under this error id.
        </Problem>
        <Button variant="outlined" sx={buttonSx} href={signIn}>Try again</Button>
      </Card>
    );
  }
  if (error || me?.problem) {
    return (
      <Card>
        <Problem tone="rose" title="Sign-in isn't set up yet" errorId={errorId}>
          {me?.problem ?? 'Ask your Ops Signals admin: Setup check → Login says what is missing.'}
        </Problem>
      </Card>
    );
  }
  return (
    <Card>
      <Typography>Sign in to see findings, cases and alerts.</Typography>
      <Button variant="contained" disableElevation size="large" sx={buttonSx} href={signIn}>Sign in with {provider}</Button>
      <Typography sx={{ fontSize: 13, color: ui.muted }}>You'll go to your company's sign-in page and come straight back here.</Typography>
    </Card>
  );
}

/** Screen D. */
export function SignedOutPage({ me }: { me: Me | undefined }) {
  return (
    <Card>
      <Typography sx={{ fontWeight: 800 }}>You're signed out of Ops Signals.</Typography>
      <Typography sx={{ fontSize: 13, color: ui.muted }}>
        Your company account may still be signed in for other tools. Sign out there too if this is a shared computer.
      </Typography>
      <Button variant="outlined" sx={buttonSx} href={signInHref(me, '/')}>Sign in again</Button>
    </Card>
  );
}

/** The tab "Sign in again" opens: the page that ran out of time picks the new session up by itself. */
function SignInDonePage() {
  return (
    <Card>
      <Typography sx={{ fontWeight: 800 }}>You're signed in again.</Typography>
      <Typography sx={{ fontSize: 13, color: ui.muted }}>Close this tab and carry on where you were; nothing you typed there was lost.</Typography>
    </Card>
  );
}

/** Screen C: a 401 while working means the session ended. Signing in again happens in a new tab, so
 * unsaved text here survives; the dialog closes by itself once the new session works. */
function SessionEndedDialog({ me }: { me: Me }) {
  const queryClient = useQueryClient();
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    const ended = () => setOpen(true);
    window.addEventListener(SIGNED_OUT_EVENT, ended);
    return () => window.removeEventListener(SIGNED_OUT_EVENT, ended);
  }, []);

  useEffect(() => {
    if (!waiting) return undefined;
    timer.current = window.setInterval(async () => {
      try {
        const fresh = await api.me();
        if (fresh.signed_in) {
          queryClient.setQueryData(ME_QUERY_KEY, fresh);
          setWaiting(false);
          setOpen(false);
          void queryClient.invalidateQueries({ predicate: (query) => query.queryKey[0] !== ME_QUERY_KEY[0] });
        }
      } catch {
        // Still signed out, or the backend is restarting: ask again shortly.
      }
    }, 3000);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [waiting, queryClient]);

  const signInAgain = () => {
    window.open(signInHref(me, SIGN_IN_DONE_PATH), '_blank', 'noopener');
    setWaiting(true);
  };

  return (
    <Dialog open={open} onClose={() => setOpen(false)} aria-labelledby="session-ended-title" maxWidth="xs" fullWidth>
      <DialogTitle id="session-ended-title" sx={{ fontWeight: 850 }}>Your sign-in has ended</DialogTitle>
      <DialogContent>
        <Typography sx={{ fontSize: 14 }}>
          Sessions last a working day. Sign in again and you'll come back to {pathname === '/' ? 'Overview' : 'this page'}. Text you typed and haven't saved stays in this tab while you sign in.
        </Typography>
        {waiting ? <Typography role="status" sx={{ mt: 1.5, fontSize: 13, color: ui.muted }}>Waiting for you to finish signing in in the new tab…</Typography> : null}
      </DialogContent>
      <DialogActions>
        <Button sx={buttonSx} onClick={() => setOpen(false)}>Not now</Button>
        <Button variant="contained" disableElevation sx={buttonSx} onClick={signInAgain}>Sign in again</Button>
      </DialogActions>
    </Dialog>
  );
}

/** With the backend's own sign-in, shows the sign-in pages until someone is signed in; otherwise just the app. */
export function SignInGate({ children }: { children: ReactNode }) {
  const { pathname, search } = useLocation();
  const { me, loading } = useWebPermissions();
  const params = new URLSearchParams(search);
  const oidc = me?.mode === 'oidc';

  useEffect(() => {
    if (oidc && me && !me.signed_in && me.auto_redirect && me.login_url && pathname !== '/sign-in' && pathname !== '/signed-out') {
      window.location.assign(signInHref(me, `${pathname}${search}`));
    }
  }, [oidc, me, pathname, search]);

  if (pathname === '/signed-out') return <SignedOutPage me={me} />;
  if (loading) return null;
  if (!oidc) return <>{children}</>;
  if (pathname === '/sign-in') {
    const next = params.get('next') ?? '/';
    return <SignInPage me={me} next={next} error={params.get('error')} errorId={params.get('id')} said={params.get('said')} as={params.get('as')} />;
  }
  if (!me?.signed_in) {
    if (me?.auto_redirect && me.login_url) return null;
    return <SignInPage me={me} next={`${pathname}${search}`} />;
  }
  if (pathname === SIGN_IN_DONE_PATH) return <SignInDonePage />;
  return (
    <>
      {children}
      <SessionEndedDialog me={me} />
    </>
  );
}
