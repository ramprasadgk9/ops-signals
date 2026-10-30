import { useEffect, useState } from 'react';
import { Box, Button, Chip, Link, Typography } from '@mui/material';
import { resetText, useDemo } from './demo';

export const OPEN_GUIDE_EVENT = 'ops-signals:demo-open-guide';

/** The thin bar above every page in demo mode: sample data, when it resets, the way to the guide. */
export function DemoBanner() {
  const demo = useDemo();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  if (!demo) return null;
  const reset = resetText(demo.resets_at, now);
  return (
    <Box
      role="note"
      aria-label="Demo"
      data-testid="demo-banner"
      sx={{
        display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap', px: { xs: 2, md: 4 }, py: 1,
        bgcolor: 'var(--os-tint-indigo, #eef0ff)', borderBottom: '1px solid var(--os-border)', fontSize: 13,
      }}
    >
      <Typography component="span" sx={{ fontWeight: 900, fontSize: 13, color: 'var(--os-ink-brand, #2e2a8f)' }}>Demo</Typography>
      <Typography component="span" sx={{ fontSize: 13 }}>
        Sample data from four services of an online shop. Nothing here is real, and nothing you do leaves this site.
      </Typography>
      {reset ? <Chip size="small" label={reset} data-testid="demo-reset" sx={{ fontWeight: 800, bgcolor: 'var(--os-surface)' }} /> : null}
      <Box sx={{ ml: 'auto', display: 'flex', gap: 2, alignItems: 'center' }}>
        <Button size="small" onClick={() => window.dispatchEvent(new Event(OPEN_GUIDE_EVENT))} sx={{ textTransform: 'none', fontWeight: 800, p: 0, minWidth: 0 }}>
          Things to try
        </Button>
        {demo.run_yourself_url ? (
          <Link href={demo.run_yourself_url} target="_blank" rel="noopener" underline="hover" sx={{ fontWeight: 800, fontSize: 13 }}>
            Run it yourself ↗
          </Link>
        ) : null}
      </Box>
    </Box>
  );
}
