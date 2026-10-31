import { useState, type ReactNode } from 'react';
import { Box, Button, Link, Stack, Typography } from '@mui/material';
import PlayCircleOutlineRoundedIcon from '@mui/icons-material/PlayCircleOutlineRounded';
import { ui } from '../standalone/theme';
import { ACCESS_DOC, LOGIN_STEPS, loginStepStates, setupDocsUrl, type LoginStepState, type SetupCheck } from '../utils/setupCheck';
import { callbackAddress, CopyLine, SetUpDialog } from './SignInSetupHelp';
import { WalkthroughVideoDialog } from './WalkthroughVideoDialog';

// Setup check → Login: the three steps of docs/access.md as a strip, and step 2's three ways to sign
// people in. Each step says where it happens, so nobody looks for "register" inside Ops Signals.

const buttonSx = { textTransform: 'none', fontWeight: 750, whiteSpace: 'nowrap' } as const;

const STEP_LOOK: Record<LoginStepState, { mark?: string; bg: string; color: string; border: string }> = {
  done: { mark: '✓', bg: ui.green, color: '#fff', border: ui.green },
  now: { bg: 'transparent', color: ui.yellow, border: ui.yellow },
  fail: { mark: '!', bg: ui.red, color: '#fff', border: ui.red },
  todo: { bg: 'transparent', color: ui.muted, border: ui.border },
};

const STATE_LABEL: Record<LoginStepState, string> = { done: 'done', now: 'next', fail: 'needs fixing', todo: 'not yet' };

export function LoginStepStrip({ check }: { check: SetupCheck }) {
  const states = loginStepStates(check);
  if (!states) return null;
  return (
    <Box component="ol" aria-label="Steps to control who can use Ops Signals" sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 1, m: 0, p: 0, pt: 1.5, pl: 0.5, listStyle: 'none' }}>
      {LOGIN_STEPS.map((label, index) => {
        const state = states[index];
        const look = STEP_LOOK[state];
        return (
          <Box component="li" key={label} aria-label={`Step ${index + 1}, ${label}: ${STATE_LABEL[state]}`} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            {index > 0 ? <Box aria-hidden sx={{ width: 36, height: 2, bgcolor: states[index - 1] === 'done' && state !== 'todo' ? ui.green : ui.border }} /> : null}
            <Box aria-hidden sx={{ width: 22, height: 22, borderRadius: '50%', display: 'grid', placeItems: 'center', fontSize: 12, fontWeight: 900, bgcolor: look.bg, color: look.color, border: `1.5px solid ${look.border}` }}>
              {look.mark ?? index + 1}
            </Box>
            <Typography sx={{ fontSize: 13, fontWeight: state === 'now' || state === 'fail' ? 800 : 600, color: state === 'todo' ? ui.muted : ui.text }}>{label}</Typography>
          </Box>
        );
      })}
    </Box>
  );
}

// Recorded on a throwaway install by scripts/record_access_walkthrough.sh.
export const ACCESS_WALKTHROUGH = {
  title: 'Lock it down in three steps',
  description: 'Lock the API, give people roles, check it: recorded on a throwaway install with a test company login. Each step says where it happens.',
  videoPath: 'walkthroughs/access.webm',
  posterPath: 'walkthroughs/access-poster.png',
  videoLabel: 'Walkthrough video: who can use Ops Signals',
};

/** "Watch how" on the Login row while a step is left. */
export function AccessWalkthroughButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button size="small" variant="outlined" sx={buttonSx} startIcon={<PlayCircleOutlineRoundedIcon />} onClick={() => setOpen(true)}>
        Watch how (2 min)
      </Button>
      <WalkthroughVideoDialog open={open} onClose={() => setOpen(false)} {...ACCESS_WALKTHROUGH} />
    </>
  );
}

export type Where = 'server' | 'grafana' | 'company' | 'ops';

const WHERE: Record<Where, { label: string; bg: string; title: string }> = {
  server: { label: 'Server', bg: '#64748b', title: 'The machine or cluster running Ops Signals' },
  grafana: { label: 'Grafana', bg: '#ea580c', title: 'In Grafana' },
  company: { label: 'Company login', bg: '#9333ea', title: "The admin console of the system behind your company's sign-in page, outside Ops Signals" },
  ops: { label: 'Ops Signals', bg: '#2563eb', title: 'Here, in Ops Signals' },
};

export function WhereTag({ where }: { where: Where }) {
  const tag = WHERE[where];
  return (
    <Box component="span" title={tag.title} sx={{ display: 'inline-block', fontSize: 11, fontWeight: 800, color: '#fff', bgcolor: tag.bg, borderRadius: '3px', px: 0.75, mr: 0.75, lineHeight: '18px', whiteSpace: 'nowrap', verticalAlign: 'baseline' }}>
      {tag.label}
    </Box>
  );
}

function Path({ title, meta, recommended, picked, children, actions }: { title: string; meta: string; recommended?: boolean; picked?: boolean; children: ReactNode; actions: ReactNode }) {
  return (
    <Box component="section" aria-label={title} sx={{ border: `1px solid ${picked ? ui.blue : ui.border}`, bgcolor: picked ? 'rgba(79, 70, 229, 0.03)' : 'transparent', borderRadius: '6px', p: 1.75, display: 'flex', flexDirection: 'column', gap: 0.75 }}>
      <Typography sx={{ fontWeight: 800, fontSize: 14 }}>
        {title}
        {recommended ? <Box component="span" sx={{ ml: 1, fontSize: 11, fontWeight: 700, color: ui.green, border: `1px solid ${ui.green}`, borderRadius: '3px', px: 0.5 }}>recommended</Box> : null}
      </Typography>
      <Typography sx={{ fontSize: 12.5, color: ui.muted }}>{meta}</Typography>
      <Box component="ol" sx={{ m: 0, pl: 2.25, fontSize: 13, '& li': { my: 0.6 } }}>{children}</Box>
      <Stack direction="row" spacing={1} sx={{ mt: 'auto', pt: 1 }} flexWrap="wrap" useFlexGap>{actions}</Stack>
    </Box>
  );
}

function GuideLink({ anchor, children = 'Details' }: { anchor: string; children?: ReactNode }) {
  return (
    <Button size="small" variant="outlined" sx={buttonSx} href={`${setupDocsUrl(ACCESS_DOC)}#${anchor}`} target="_blank" rel="noreferrer">
      {children}
    </Button>
  );
}

/** Step 2 with nobody signing in: how does the team open Ops Signals? One card each, as in docs/access.md. */
export function SignInPaths() {
  const [dialog, setDialog] = useState(false);
  return (
    <Box sx={{ ml: { md: 4.5 }, mb: 1.5, p: 2, borderRadius: '6px', border: `1px solid ${ui.border}` }}>
      <Typography sx={{ fontSize: 11.5, letterSpacing: '.06em', textTransform: 'uppercase', color: ui.muted, fontWeight: 800, mb: 1 }}>
        How does your team open Ops Signals?
      </Typography>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(3, 1fr)' }, gap: 1.5 }}>
        <Path title="Grafana plugin" meta="2 min · people sign in with Grafana" actions={<GuideLink anchor="2a-grafana-plugin" />}>
          <li><WhereTag where="grafana" />Administration → Plugins and data → Plugins → Ops Signals → <b>Configuration</b></li>
          <li><WhereTag where="grafana" /><b>Connect through: Grafana</b>, paste the API token</li>
          <li><WhereTag where="grafana" /><b>Save settings</b>. Roles come from Grafana.</li>
        </Path>
        <Path
          title="Web UI · company login"
          meta="15 min · people sign in with their company account"
          recommended
          picked
          actions={
            <>
              <Button size="small" variant="contained" disableElevation sx={buttonSx} onClick={() => setDialog(true)}>How to set up company sign-in</Button>
              <GuideLink anchor="2b-web-ui-with-company-login" />
            </>
          }
        >
          <li>
            <WhereTag where="company" />Add a web app (your identity team can). Redirect address:
            <Box sx={{ mt: 0.5 }}><CopyLine value={callbackAddress()} /></Box>
          </li>
          <li><WhereTag where="company" />Add a <code>groups</code> claim</li>
          <li><WhereTag where="server" />Set the issuer, client ID, secret and the Editor and Admin groups; restart</li>
          <li><WhereTag where="ops" />Come back here and click <b>Test sign-in</b></li>
        </Path>
        <Path title="Web UI · sign-in proxy" meta="10 min · you already run one" actions={<GuideLink anchor="2c-web-ui-behind-your-sign-in-proxy" />}>
          <li><WhereTag where="server" />Make the proxy the <b>only</b> way to reach the web UI</li>
          <li><WhereTag where="server" />Have it pass the user and groups headers</li>
          <li><WhereTag where="server" />Set <code>OPS_SIGNALS_AUTH_MODE=proxy-headers</code> and the two group lists; restart</li>
        </Path>
      </Box>
      <Typography sx={{ fontSize: 13, color: ui.muted, mt: 1.5 }}>
        Not ready for your real login system?{' '}
        <Link href={setupDocsUrl('docs/try-company-sign-in.md')} target="_blank" rel="noreferrer">Try it with test accounts</Link>{' '}
        (a Viewer, an Editor and an Admin) on this computer first.
      </Typography>
      <SetUpDialog open={dialog} onClose={() => setDialog(false)} />
    </Box>
  );
}
