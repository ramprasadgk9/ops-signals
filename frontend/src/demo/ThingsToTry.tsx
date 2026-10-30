import { useCallback, useEffect, useState } from 'react';
import { Box, Button, LinearProgress, Paper, Stack, Typography } from '@mui/material';
import CheckRoundedIcon from '@mui/icons-material/CheckRounded';
import { useLocation, useNavigate } from 'react-router-dom';
import { api } from '../api/queries';
import { DEMO_STEP_EVENT, DEMO_STEPS, OPEN_HANDOFF_EVENT, loadProgress, saveProgress, stepDoneBy, stepTarget, useDemo } from './demo';
import type { DemoProgress, DemoStep } from './demo';
import { OPEN_GUIDE_EVENT } from './DemoBanner';

/** The "Things to try" guide in demo mode: ten steps through the demo story. Each has a button that
 * goes there and ticks itself off when the visitor does it (a page visit or a markDemoStep). */
export function ThingsToTry() {
  const demo = useDemo();
  if (!demo) return null;
  return <Guide period={demo.resets_at ?? 'demo'} />;
}

function Guide({ period }: { period: string }) {
  const [progress, setProgress] = useState<DemoProgress>(() => loadProgress(period));
  const location = useLocation();
  const navigate = useNavigate();

  const update = useCallback((change: (current: DemoProgress) => DemoProgress) => {
    setProgress((current) => {
      const next = change(current);
      saveProgress(next);
      return next;
    });
  }, []);

  const complete = useCallback((event: { page?: string; mark?: string }) => {
    update((current) => {
      const done = DEMO_STEPS.filter((step) => !current.done.includes(step.id) && stepDoneBy(step, event)).map((step) => step.id);
      return done.length ? { ...current, done: [...current.done, ...done] } : current;
    });
  }, [update]);

  useEffect(() => complete({ page: location.pathname }), [complete, location.pathname]);
  useEffect(() => {
    const onMark = (event: Event) => complete({ mark: String((event as CustomEvent).detail) });
    const onOpen = () => update((current) => ({ ...current, hidden: false }));
    window.addEventListener(DEMO_STEP_EVENT, onMark);
    window.addEventListener(OPEN_GUIDE_EVENT, onOpen);
    return () => {
      window.removeEventListener(DEMO_STEP_EVENT, onMark);
      window.removeEventListener(OPEN_GUIDE_EVENT, onOpen);
    };
  }, [complete, update]);

  const go = async (step: DemoStep) => {
    navigate(await stepTarget(step, () => api.findings(step.finding?.service), (findingId) => api.createCase(findingId)));
    // After the page has rendered its button.
    if (step.open === 'handoff') window.setTimeout(() => window.dispatchEvent(new Event(OPEN_HANDOFF_EVENT)), 300);
  };

  // A finding's details or a dialog opens over the right of the page, where the guide sits: shrink to
  // the button while one is open so it doesn't cover what the step sent the visitor to see.
  const panelOpen = useModalOpen();

  const doneCount = DEMO_STEPS.filter((step) => progress.done.includes(step.id)).length;
  const current = DEMO_STEPS.find((step) => !progress.done.includes(step.id));
  const position = { position: 'fixed', right: 20, bottom: 20, zIndex: 1250 } as const;

  if (progress.hidden || panelOpen) {
    return (
      <Button variant="contained" onClick={() => update((value) => ({ ...value, hidden: false }))} data-testid="demo-guide-pill"
        sx={{ ...position, borderRadius: 999, px: 2.25, py: 1.1, textTransform: 'none', fontWeight: 850, boxShadow: '0 12px 30px rgba(79,70,229,.35)' }}>
        Things to try · {doneCount} of {DEMO_STEPS.length}
      </Button>
    );
  }

  return (
    <Paper role="complementary" aria-label="Things to try" data-testid="demo-guide" elevation={8}
      sx={{ ...position, width: 340, maxWidth: 'calc(100vw - 40px)', borderRadius: '12px', overflow: 'hidden', border: '1px solid var(--os-border)' }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ px: 1.75, py: 1.25, bgcolor: 'var(--os-surface-alt)' }}>
        <Typography sx={{ fontWeight: 850, fontSize: 14 }}>
          Things to try <Box component="span" sx={{ color: 'var(--os-muted)', fontWeight: 700, fontSize: 12 }}>· {doneCount} of {DEMO_STEPS.length}</Box>
        </Typography>
        <Button size="small" onClick={() => update((value) => ({ ...value, hidden: true }))} sx={{ textTransform: 'none', color: 'var(--os-muted)', fontWeight: 700, minWidth: 0 }}>Hide</Button>
      </Stack>
      <LinearProgress variant="determinate" value={(doneCount / DEMO_STEPS.length) * 100} sx={{ height: 4 }} aria-label="Steps done" />
      <Box component="ol" sx={{ listStyle: 'none', m: 0, p: 0, py: 0.75, maxHeight: '55vh', overflowY: 'auto' }}>
        {DEMO_STEPS.map((step, index) => {
          const done = progress.done.includes(step.id);
          const now = step.id === current?.id;
          return (
            <Box component="li" key={step.id} data-testid={`demo-step-${step.id}`} data-done={done || undefined}
              sx={{ display: 'grid', gridTemplateColumns: '24px 1fr', gap: 1, px: 1.75, py: 0.85, bgcolor: now ? 'var(--os-surface-alt)' : 'transparent' }}>
              <Box aria-hidden sx={{
                width: 20, height: 20, mt: '1px', borderRadius: '50%', display: 'grid', placeItems: 'center', fontSize: 11, fontWeight: 900, color: '#fff',
                bgcolor: done ? 'success.main' : now ? 'primary.main' : 'transparent', border: done || now ? 'none' : '2px solid var(--os-border)',
              }}>
                {done ? <CheckRoundedIcon sx={{ fontSize: 14 }} /> : now ? index + 1 : ''}
              </Box>
              <Box>
                <Typography sx={{ fontSize: 13, fontWeight: now ? 850 : 700, color: done ? 'var(--os-muted)' : 'inherit', textDecoration: done ? 'line-through' : 'none' }}>
                  {step.title}
                </Typography>
                {now ? (
                  <>
                    <Typography sx={{ fontSize: 12, color: 'var(--os-muted)', mt: 0.25, mb: 0.75 }}>{step.how}</Typography>
                    <Button size="small" variant="contained" onClick={() => void go(step)} sx={{ textTransform: 'none', fontWeight: 800 }}>{step.goLabel}</Button>
                  </>
                ) : null}
              </Box>
            </Box>
          );
        })}
      </Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ px: 1.75, py: 1, borderTop: '1px solid var(--os-border)' }}>
        <Typography sx={{ fontSize: 12, color: 'var(--os-muted)' }}>{current ? 'Do them in any order.' : 'All done. Thanks for trying it!'}</Typography>
        <Button size="small" onClick={() => update((value) => ({ ...value, done: [] }))} sx={{ textTransform: 'none', fontWeight: 700 }}>Start over</Button>
      </Stack>
    </Paper>
  );
}

/** Whether an MUI drawer or dialog is open over the page. */
function useModalOpen(): boolean {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const check = () => setOpen(Boolean(document.querySelector('.MuiDrawer-modal, .MuiDialog-root')));
    check();
    const observer = new MutationObserver(check);
    observer.observe(document.body, { childList: true });
    return () => observer.disconnect();
  }, []);
  return open;
}
