import { Alert, Link } from '@mui/material';
import { useLocation } from 'react-router-dom';
import { turnedOffReason, useDemo } from './demo';

/** Top of a page that's view-only in demo mode: why, and where to try it for real. */
export function DemoTurnedOff() {
  const demo = useDemo();
  const location = useLocation();
  const reason = demo ? turnedOffReason(location.pathname) : null;
  if (!reason) return null;
  return (
    <Alert severity="info" icon={<span aria-hidden>🔒</span>} data-testid="demo-turned-off" sx={{ mb: 2 }}>
      <strong>Turned off in the demo.</strong> {reason}{' '}
      {demo?.run_yourself_url ? <Link href={demo.run_yourself_url} target="_blank" rel="noopener" sx={{ fontWeight: 800 }}>Run it yourself ↗</Link> : null}
    </Alert>
  );
}
