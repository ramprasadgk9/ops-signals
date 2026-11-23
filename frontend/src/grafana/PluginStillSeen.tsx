import React, { useEffect, useState } from 'react';
import type { CaseStillSeen } from '../types';
import { getCaseStillSeen } from './backendClient';
import { styles } from './plainUi';

// The Resolution step's warning before Resolved, in the Grafana plugin's own styling. Same endpoint
// and wording as the web UI's case page (pages/CaseDetailsPage StillSeenWarning). Advice only: a
// failed check shows nothing and never blocks the save.

export function PluginStillSeen({ backendUrl, caseId }: { backendUrl: string; caseId: number }) {
  const [stillSeen, setStillSeen] = useState<CaseStillSeen | null>(null);

  useEffect(() => {
    let active = true;
    setStillSeen(null);
    getCaseStillSeen(backendUrl, caseId)
      .then((data) => { if (active) setStillSeen(data); })
      .catch(() => undefined);
    return () => { active = false; };
  }, [backendUrl, caseId]);

  if (!stillSeen?.still_seen) return null;
  const when = stillSeen.seen_at
    ? new Date(stillSeen.seen_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    : null;
  return (
    <div data-testid="plugin-still-seen" role="alert" style={{ ...styles.infoNote, color: '#ffb357', borderColor: 'rgba(255, 179, 87, 0.4)' }}>
      <strong>This problem is still showing up.</strong> The check {when ? `at ${when} ` : ''}still found it
      {stillSeen.finding_id ? ` (finding #${stillSeen.finding_id})` : ''}. If you resolve now, the fix you write may not have
      worked yet. Wait for the next check, or choose Mitigated if it has only eased.
    </div>
  );
}
