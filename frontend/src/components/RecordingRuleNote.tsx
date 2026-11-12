import type { ReactNode } from 'react';
import { Alert, Box, Chip, Link, Tooltip, Typography } from '@mui/material';

import type { RecordingRule } from '../types';
import { NO_SERVICE_LABEL_NOTE, RECORDING_RULE_TOOLTIP, ruleAlertSentence, ruleNoteLead } from '../utils/recordingRules';

const mono = 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace';

function QueryBlock({ children }: { children: string }) {
  return (
    <Box component="code" sx={{ display: 'block', mt: 0.5, px: 1, py: 0.75, borderRadius: '4px', bgcolor: 'rgba(0,0,0,0.18)', fontFamily: mono, fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
      {children}
    </Box>
  );
}

/** The "Recording rule" tag next to a name in the Metrics list. */
export function RecordingRuleTag({ rule }: { rule: RecordingRule }) {
  return (
    <Tooltip title={RECORDING_RULE_TOOLTIP} arrow>
      <Chip size="small" variant="outlined" color="info" label="Recording rule" sx={{ height: 20, fontSize: 11, fontWeight: 700, ml: 1, flexShrink: 0 }} aria-label={`Recording rule in group ${rule.group}`} />
    </Tooltip>
  );
}

/** Under the PromQL box: what a picked recording rule measures. `noServiceLabel` when the rule's
 * result has no service label: it can be previewed but not analyzed. */
export function RecordingRuleNote({ rule, noServiceLabel }: { rule: RecordingRule; noServiceLabel?: boolean }) {
  const severity = rule.health === 'err' ? 'error' : noServiceLabel ? 'warning' : 'info';
  return (
    <Alert severity={severity} variant="outlined" data-testid="recording-rule-note" sx={{ '& .MuiAlert-message': { width: '100%', minWidth: 0 } }}>
      <Typography sx={{ fontSize: 13 }}>
        <strong>{rule.name}</strong>: {ruleNoteLead(rule)}
      </Typography>
      {rule.health === 'err' && rule.last_error ? <QueryBlock>{rule.last_error}</QueryBlock> : null}
      <QueryBlock>{rule.query}</QueryBlock>
      {rule.source_metrics.length ? (
        <Typography sx={{ mt: 0.5, fontSize: 12, color: 'var(--os-muted)' }}>Built from {rule.source_metrics.join(', ')}</Typography>
      ) : null}
      {(rule.alerts ?? []).map((alert) => (
        <Typography key={alert.name} sx={{ mt: 0.5, fontSize: 12.5 }} data-testid="recording-rule-alert">
          {ruleAlertSentence(alert)}
          {alert.runbook_url ? (
            <>
              {' '}
              <Link href={alert.runbook_url} target="_blank" rel="noopener noreferrer">Runbook</Link>
            </>
          ) : null}
        </Typography>
      ))}
      {noServiceLabel ? <Typography sx={{ mt: 0.5, fontSize: 12.5 }}>{NO_SERVICE_LABEL_NOTE}</Typography> : null}
    </Alert>
  );
}

/** Finding details: the recording rule behind the analyzed metric. */
export function RecordingRuleMeasured({ rule, promql }: { rule: RecordingRule; promql?: string | null }) {
  const row = (label: string, value: ReactNode) => (
    <>
      <Typography sx={{ fontSize: 12.5, color: 'var(--os-muted)' }}>{label}</Typography>
      <Box sx={{ fontSize: 12.5, minWidth: 0, wordBreak: 'break-word' }}>{value}</Box>
    </>
  );
  return (
    <Box data-testid="recording-rule-measured">
      <Typography variant="h6" sx={{ mb: 1 }}>How this was measured</Typography>
      <Box sx={{ display: 'grid', gridTemplateColumns: '130px 1fr', gap: 0.75, alignItems: 'baseline' }}>
        {row('Recording rule', <><Box component="code" sx={{ fontFamily: mono }}>{rule.name}</Box>{rule.group ? <Chip size="small" variant="outlined" label={rule.group} sx={{ ml: 1, height: 20, fontSize: 11 }} /> : null}</>)}
        {row('Saved query', <Box component="code" sx={{ fontFamily: mono }}>{rule.query}</Box>)}
        {rule.source_metrics.length ? row('Built from', rule.source_metrics.join(', ')) : null}
        {promql ? row('Query used', <Box component="code" sx={{ fontFamily: mono }}>{promql}</Box>) : null}
      </Box>
      <Typography sx={{ mt: 0.75, fontSize: 12, color: 'var(--os-muted)' }}>This is the rule as it is now. If someone changed it since this run, older points used the old query.</Typography>
    </Box>
  );
}
