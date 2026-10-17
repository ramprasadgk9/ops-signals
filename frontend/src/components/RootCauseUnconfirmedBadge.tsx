import { Chip, Tooltip } from '@mui/material';

/** A resolved case whose root cause was never verified. A closing outcome closes a case on its own,
 * so this keeps the weaker evidence visible instead of making it a status. Imported cases arrive
 * with their postmortem's cause and never show it. */
export function isRootCauseUnconfirmed(item: { case_status?: string | null; rootCauseVerified?: boolean | null; source?: string | null }) {
  const imported = Boolean(item.source && item.source !== 'detected');
  return !imported && (item.case_status ?? '').toLowerCase() === 'resolved' && item.rootCauseVerified === false;
}

export function RootCauseUnconfirmedBadge() {
  return (
    <Tooltip title="Resolved, but the root cause wasn't verified. Tick Verified under Root Cause once it's confirmed.">
      <Chip size="small" variant="outlined" color="warning" label="Root cause unconfirmed" sx={{ fontWeight: 800 }} />
    </Tooltip>
  );
}
