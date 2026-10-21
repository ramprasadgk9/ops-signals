import { useState } from 'react';
import {
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  ClickAwayListener,
  IconButton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import { ui } from '../standalone/theme';
import type { AnalyzerExecution, CsvAnalyzerRoutingDecision } from '../types';
import { useWebPermissions } from '../hooks/useWebPermissions';
import { buildAnalyzerRunView, type RanTone } from '../utils/analyzerRuns';

// What ran on the series and why, a fix for anything that couldn't run when one exists, and the
// router's full scoring folded below. Built from the same analyzerRuns view as the Grafana plugin.

const DETAILS_OPEN_KEY = 'ops-signals.router-details-open';
const HIDDEN_LIBRARY_KEY = 'ops-signals.hide-missing-library.';

function readFlag(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === '1';
  } catch {
    return false;
  }
}

function writeFlag(key: string, value: boolean) {
  try {
    if (value) window.localStorage.setItem(key, '1');
    else window.localStorage.removeItem(key);
  } catch {
    // Storage can be blocked; the panel works without it.
  }
}

const TONE_SX: Record<RanTone, object> = {
  pick: { bgcolor: 'var(--os-tint-cyan)', color: 'var(--os-ink-brand)' },
  cover: { bgcolor: 'var(--os-tint-green)', color: 'var(--os-ink-green)' },
  always: { bgcolor: 'var(--os-surface-alt)', color: 'var(--os-text-2)' },
  failed: { bgcolor: 'var(--os-tint-rose)', color: 'var(--os-ink-red)' },
};

/** What the analyzer looks for, on hover, keyboard focus or tap, so nobody has to open the docs. */
function AnalyzerTip({ name, text }: { name: string; text: string | null }) {
  const [open, setOpen] = useState(false);
  if (!text) return null;
  return (
    <ClickAwayListener onClickAway={() => setOpen(false)}>
      <span>
        <Tooltip title={text} open={open} onOpen={() => setOpen(true)} onClose={() => setOpen(false)} arrow describeChild>
          <IconButton size="small" aria-label={`What ${name} does`} onClick={() => setOpen((value) => !value)} sx={{ p: 0.25, color: ui.muted }}>
            <InfoOutlinedIcon sx={{ fontSize: 15 }} />
          </IconButton>
        </Tooltip>
      </span>
    </ClickAwayListener>
  );
}

function AnalyzerName({ name, description, bold = true }: { name: string; description: string | null; bold?: boolean }) {
  return (
    <Stack direction="row" alignItems="center" spacing={0.5} sx={{ minWidth: 0 }}>
      <Typography component="span" sx={{ fontSize: 13, fontWeight: bold ? 800 : 500 }}>{name}</Typography>
      <AnalyzerTip name={name} text={description} />
    </Stack>
  );
}

function MissingLibraryHint({ name, library }: { name: string; library: string }) {
  const [showHow, setShowHow] = useState(false);
  const [hidden, setHidden] = useState(() => readFlag(HIDDEN_LIBRARY_KEY + library));
  if (hidden) return null;
  return (
    <Box
      data-testid={`missing-library-${library}`}
      sx={{ border: '1px solid var(--os-tint-amber-border)', bgcolor: 'var(--os-tint-amber)', borderRadius: '8px', px: 2, py: 1.5 }}
    >
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} justifyContent="space-between" alignItems={{ sm: 'center' }}>
        <Box sx={{ minWidth: 0 }}>
          <Typography sx={{ fontSize: 13, fontWeight: 850, color: 'var(--os-ink-amber)' }}>
            {name} didn't run: its library isn't installed
          </Typography>
          <Typography sx={{ fontSize: 12, color: ui.muted }}>
            An admin can install it where the Ops Signals backend runs. Only admins see this.
          </Typography>
        </Box>
        <Stack direction="row" spacing={1} flexShrink={0}>
          <Button size="small" variant="contained" onClick={() => setShowHow((value) => !value)} sx={{ textTransform: 'none' }}>
            {showHow ? 'Hide steps' : 'Show how to install'}
          </Button>
          <Button
            size="small"
            onClick={() => {
              writeFlag(HIDDEN_LIBRARY_KEY + library, true);
              setHidden(true);
            }}
            sx={{ textTransform: 'none' }}
          >
            Don't show again
          </Button>
        </Stack>
      </Stack>
      {showHow ? (
        <Typography component="div" sx={{ fontSize: 12, color: ui.text, mt: 1.2 }}>
          Install the Python package in the backend's environment, then restart the backend:
          <Box component="code" sx={{ display: 'block', mt: 0.6, px: 1, py: 0.6, borderRadius: '6px', bgcolor: 'var(--os-surface-alt)', fontFamily: 'monospace' }}>
            pip install {library}
          </Box>
          {name} runs on the next analysis.
        </Typography>
      ) : null}
    </Box>
  );
}

export function RouterDecisionPanel({
  decisions,
  executions = [],
  executedAnalyzers = [],
  findingCount = null,
}: {
  decisions: CsvAnalyzerRoutingDecision[];
  executions?: AnalyzerExecution[];
  executedAnalyzers?: string[];
  findingCount?: number | null;
}) {
  const { me, canAdmin } = useWebPermissions();
  // Wait for the signed-in user: before /api/me answers, nothing is locked and viewers would see it.
  const showAdminHints = me !== undefined && canAdmin;
  const [detailsOpen, setDetailsOpen] = useState(() => readFlag(DETAILS_OPEN_KEY));
  const view = buildAnalyzerRunView(decisions, executions, findingCount);
  const toggleDetails = () => {
    writeFlag(DETAILS_OPEN_KEY, !detailsOpen);
    setDetailsOpen(!detailsOpen);
  };

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack spacing={2}>
          <Stack direction="row" flexWrap="wrap" justifyContent="space-between" alignItems="baseline" gap={1}>
            <Typography variant="h6">Router Decisions</Typography>
            {decisions.length ? (
              <Stack direction="row" flexWrap="wrap" gap={2} sx={{ fontSize: 13, color: ui.muted }}>
                <span><strong>{view.ran.length || executedAnalyzers.length}</strong> ran</span>
                {view.detectedShapes.length ? <span>Shapes detected: <strong>{view.detectedShapes.join(', ')}</strong></span> : null}
                {findingCount !== null ? <span><strong>{findingCount}</strong> finding{findingCount === 1 ? '' : 's'}</span> : null}
              </Stack>
            ) : null}
          </Stack>

          {decisions.length === 0 ? (
            <Typography variant="body2" color="text.secondary">No router decisions returned yet.</Typography>
          ) : (
            <>
              {view.ran.length ? (
                <Box sx={{ border: `1px solid ${ui.border}`, borderRadius: '8px', overflow: 'hidden' }}>
                  {view.ran.map((row, index) => (
                    <Box
                      key={row.id}
                      data-testid={`ran-analyzer-${row.id}`}
                      sx={{
                        display: 'grid',
                        gridTemplateColumns: { xs: '1fr auto', md: '200px 190px minmax(0, 1fr) 110px' },
                        gap: 1.5,
                        alignItems: 'center',
                        px: 2,
                        py: 1.2,
                        borderTop: index === 0 ? 'none' : `1px solid ${ui.border}`,
                      }}
                    >
                      <AnalyzerName name={row.name} description={row.description} />
                      <Chip size="small" label={row.label} sx={{ ...TONE_SX[row.tone], fontWeight: 800, justifySelf: 'start' }} />
                      <Typography sx={{ fontSize: 12, color: row.tone === 'failed' ? ui.red : ui.muted, gridColumn: { xs: '1 / -1', md: 'auto' }, minWidth: 0 }}>
                        {row.reason}
                      </Typography>
                      <Typography sx={{ fontSize: 12, fontWeight: row.inFinding ? 800 : 500, color: row.inFinding ? ui.text : ui.muted, whiteSpace: 'nowrap' }}>
                        {row.outcome ?? ''}
                      </Typography>
                    </Box>
                  ))}
                </Box>
              ) : executedAnalyzers.length ? (
                <Typography sx={{ fontSize: 13 }}>Ran: {executedAnalyzers.join(', ')}</Typography>
              ) : (
                <Typography variant="body2" color="text.secondary">No analyzer ran on this series.</Typography>
              )}

              {showAdminHints
                ? view.missingLibraries.map((item) => <MissingLibraryHint key={item.id} name={item.name} library={item.library} />)
                : null}

              <Box sx={{ borderTop: `1px solid ${ui.border}`, pt: 1.5 }}>
                <Button size="small" onClick={toggleDetails} aria-expanded={detailsOpen} sx={{ textTransform: 'none', px: 0 }}>
                  {detailsOpen ? '▾' : '▸'} How the router scored this series
                </Button>
                {detailsOpen ? (
                  <Stack spacing={2} sx={{ mt: 1.5 }}>
                    <Box sx={{ overflowX: 'auto' }}>
                      <Table size="small" sx={{ minWidth: 560 }}>
                        <TableHead>
                          <TableRow>
                            <TableCell>Analyzer</TableCell>
                            <TableCell>Score</TableCell>
                            <TableCell>Router rating</TableCell>
                            <TableCell>Matched shapes</TableCell>
                            <TableCell>Outcome</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {view.scored.map((row) => (
                            <TableRow key={row.id} data-testid={`router-score-${row.id}`}>
                              <TableCell><AnalyzerName name={row.name} description={row.description} bold={row.ran} /></TableCell>
                              <TableCell sx={{ fontVariantNumeric: 'tabular-nums' }}>{row.score === null ? '—' : row.score.toFixed(2)}</TableCell>
                              <TableCell data-testid={`router-rating-${row.id}`}>{row.rating}</TableCell>
                              <TableCell sx={{ color: ui.muted }}>{row.shapes.length ? row.shapes.join(', ') : '—'}</TableCell>
                              <TableCell>{row.outcome}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </Box>
                    {view.notBuiltIn.length ? (
                      <Stack spacing={1}>
                        <Typography sx={{ fontSize: 12, fontWeight: 850, color: ui.muted, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                          In the router's catalog, not built into Ops Signals yet
                        </Typography>
                        <Stack direction="row" flexWrap="wrap" gap={1}>
                          {view.notBuiltIn.map((item) => (
                            <Chip key={item.id} data-testid={`router-not-built-in-${item.id}`} size="small" variant="outlined" label={item.name} sx={{ borderStyle: 'dashed' }} />
                          ))}
                        </Stack>
                        <Typography sx={{ fontSize: 12, color: ui.muted }}>
                          The router scores these for reference only; they can't run here.
                        </Typography>
                      </Stack>
                    ) : null}
                  </Stack>
                ) : null}
              </Box>
            </>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}
